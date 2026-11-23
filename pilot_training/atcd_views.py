"""Explicit preview/confirmation of ATCD assignments; no grading data is imported."""
import hashlib
import json
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.core import signing
from django.db import transaction, IntegrityError
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from .atcd_client import fetch_schedule
from .models import (Pilot, Instructor, Session, TrainingSession, CrewSession, RatingSession,
    ATCDPilotLink, ATCDInstructorLink, ATCDTemplateLink, ATCDScheduleLink, ATCDImportLog)


class CanSync(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_active and request.user.has_perm('pilot_training.sync_atcd')


class ImportInput(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    mappings = serializers.DictField(child=serializers.DictField(child=serializers.IntegerField(min_value=1)), default=dict)
    confirmation = serializers.CharField(required=False, max_length=1000)

    def validate(self, value):
        if not 0 <= (value['end'] - value['start']).days <= 92:
            raise serializers.ValidationError('Выберите период до 93 дней.')
        if set(value['mappings']) - {'pilots', 'instructors', 'templates'}:
            raise serializers.ValidationError('Неизвестный вид сопоставления.')
        return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def mappings_for(overrides):
    result = {
        'pilots': {str(r.source_id): r.pilot_id for r in ATCDPilotLink.objects.all()},
        'instructors': {str(r.source_id): r.instructor_id for r in ATCDInstructorLink.objects.all()},
        'templates': {r.source_key: r.session_id for r in ATCDTemplateLink.objects.all()},
    }
    for kind, values in overrides.items(): result[kind].update(values)
    return result


def plan(rows, mappings):
    output = []
    for row in rows:
        link = ATCDScheduleLink.objects.filter(source_id=row['id']).select_related('crew').first()
        current = list(link.crew.participants.select_related('pilot', 'session')) if link else []
        item = {'source': row, 'action': 'create', 'errors': []}
        if row.get('status') == 'cancelled':
            if not link:
                item.update(action='skip', state=None)
                output.append(item)
                continue
            state = {**link.snapshot, 'status': 'cancelled'}
        else:
            item['errors'].extend(row.get('errors', []))
            try:
                pilots = [mappings['pilots'][str(p['id'])] for p in row['pilots']]
                instructor = mappings['instructors'][str(row['instructor']['id'])]
                session = mappings['templates'][row['template_key']]
                if len(pilots) not in (1, 2) or len(set(pilots)) != len(pilots): raise ValueError()
                if Pilot.objects.filter(pk__in=pilots, is_active=True, user__is_active=True).count() != len(pilots): raise ValueError()
                if not Instructor.objects.filter(pk=instructor, user__is_active=True).exists() or not Session.objects.filter(pk=session).exists(): raise ValueError()
                start, end = parse_datetime(row['starts_at']), parse_datetime(row['ends_at'])
                if not start or not end or timezone.is_naive(start) or timezone.is_naive(end) or end <= start: raise ValueError()
                ZoneInfo(row['timezone'])
                if len(row['venue']) > 100: raise ValueError('Название места длиннее 100 символов.')
                state = {'pilots': sorted(pilots), 'instructor': instructor, 'session': session,
                         'starts_at': start.isoformat(), 'ends_at': end.isoformat(),
                         'timezone': row['timezone'], 'venue': row['venue'], 'status': 'planned'}
            except (KeyError, ValueError, TypeError) as error:
                item['errors'].append(str(error) if isinstance(error, ValueError) and str(error) else 'Сопоставьте пилотов, инструктора и задание; проверьте время и активность учётных записей.')
                item['action'] = 'blocked'
                output.append(item)
                continue
        item['state'] = state
        matches_current = current and len(current) == len(state['pilots']) and sorted(r.pilot_id for r in current) == state['pilots'] and all(
            r.instructor_id == state['instructor'] and r.session_id == state['session'] and
            r.planned_at == parse_datetime(state['starts_at']) and r.ends_at == parse_datetime(state['ends_at']) and
            r.schedule_timezone == state['timezone'] and r.venue == state['venue'] and
            (r.status == state['status'] or r.status == 'completed' and state['status'] == 'planned') for r in current)
        if link and link.snapshot == state and matches_current:
            item['action'] = 'unchanged'
        elif link:
            item['action'] = 'update'
            if any(r.status != 'planned' or not r.planned_at or r.planned_at <= timezone.now() for r in current) or RatingSession.objects.filter(training_session__in=current).exists():
                item['errors'].append('Сессия уже началась, отменена или содержит результат. Изменение требует ответственного.')
        if item['action'] in ('create', 'update') and state['status'] == 'planned' and parse_datetime(state['starts_at']) <= timezone.now():
            item['errors'].append('Прошедшие сессии не создаются через импорт расписания.')
        if item['errors']: item['action'] = 'blocked'
        output.append(item)
    # Check both incoming rows and existing assignments, including manual ones.
    changing = [i for i in output if i['action'] in ('create', 'update') and i['state']['status'] == 'planned']
    for item in changing:
        state = item['state']; start, end = (parse_datetime(state[k]) for k in ('starts_at', 'ends_at'))
        candidates = TrainingSession.objects.filter(status='planned', planned_at__lt=end).exclude(crew_session__atcdschedulelink__source_id=item['source']['id'])
        conflict = any((r.ends_at or r.planned_at + timedelta(minutes=30)) > start and
                       (r.pilot_id in state['pilots'] or r.instructor_id == state['instructor']) for r in candidates)
        for other in changing:
            if other is item: continue
            b = other['state']
            conflict |= (parse_datetime(b['starts_at']) < end and parse_datetime(b['ends_at']) > start and
                         (b['instructor'] == state['instructor'] or bool(set(b['pilots']) & set(state['pilots']))))
        if conflict:
            item['errors'].append('Пересечение времени пилота или инструктора с другим назначением.')
            item['action'] = 'blocked'
    return output


def save_mapping(rows, mappings):
    used = {'pilots': set(), 'instructors': set(), 'templates': set()}
    for row in rows:
        if row.get('status') == 'cancelled': continue
        used['pilots'].update(str(p['id']) for p in row['pilots'])
        used['instructors'].add(str(row['instructor']['id']))
        used['templates'].add(row['template_key'])
    for kind, model, source, target in (
        ('pilots', ATCDPilotLink, 'source_id', 'pilot_id'),
        ('instructors', ATCDInstructorLink, 'source_id', 'instructor_id'),
        ('templates', ATCDTemplateLink, 'source_key', 'session_id')):
        for key in used[kind]:
            model.objects.update_or_create(**{source: key}, defaults={target: mappings[kind][key]})


@api_view(['GET'])
@permission_classes([CanSync])
def options(request):
    from .atcd_people import can_create_pilot
    return Response({'can_create_pilot': can_create_pilot(request.user), 'pilots': list(Pilot.objects.filter(is_active=True, user__is_active=True).values('id', 'name')),
        'instructors': list(Instructor.objects.filter(user__is_active=True).values('id', 'name')),
        'templates': list(Session.objects.values('id', 'title')), 'mappings': mappings_for({})})


@api_view(['POST'])
@permission_classes([CanSync])
def synchronize(request):
    data = ImportInput(data=request.data); data.is_valid(raise_exception=True); value = data.validated_data
    rows = fetch_schedule(value['start'].isoformat(), value['end'].isoformat())
    try:
        # Serialize imports across managers; also lock the existing assignment rows.
        with transaction.atomic():
            first_user = get_user_model().objects.order_by('pk').values_list('pk', flat=True).first()
            list(get_user_model().objects.select_for_update().filter(pk=first_user))
            links = list(ATCDScheduleLink.objects.select_for_update().filter(source_id__in=[r['id'] for r in rows]))
            list(TrainingSession.objects.select_for_update().filter(crew_session_id__in=[l.crew_id for l in links]).order_by('pk'))
            maps = mappings_for(value['mappings'])
            for kind in ('pilots', 'instructors'):
                if len(set(maps[kind].values())) != len(maps[kind]):
                    return Response({'error': 'Одна учётная запись SIM Training сопоставлена разным людям ATCD. Проверьте соответствия.'}, status=400)
            fingerprint = {'source': digest(rows), 'maps': digest(maps), 'user': request.user.pk,
                           'start': value['start'].isoformat(), 'end': value['end'].isoformat()}
            preview = plan(rows, maps)
            if 'confirmation' not in value:
                return Response({'rows': preview, 'confirmation': signing.dumps(fingerprint, salt='atcd-preview'),
                                 'can_apply': not any(i['errors'] for i in preview) and any(i['action'] in ('create', 'update') for i in preview)})
            try:
                previous = signing.loads(value['confirmation'], salt='atcd-preview', max_age=900)
            except signing.BadSignature:
                return Response({'error': 'Предпросмотр устарел. Получите расписание заново.'}, status=409)
            if previous != fingerprint or any(i['errors'] for i in preview):
                return Response({'error': 'Данные или сопоставления изменились. Проверьте расписание заново.', 'rows': preview}, status=409)
            changes = []
            for item in preview:
                if item['action'] not in ('create', 'update'): continue
                state = item['state']; source_id = item['source']['id']
                link = ATCDScheduleLink.objects.filter(source_id=source_id).first()
                old = link.snapshot if link else None
                crew = link.crew if link else CrewSession.objects.create()
                existing = list(crew.participants.order_by('pilot_id'))
                for index, pilot in enumerate(state['pilots']):
                    assignment = existing[index] if index < len(existing) else TrainingSession(crew_session=crew)
                    assignment.pilot_id = pilot; assignment.session_id = state['session']; assignment.instructor_id = state['instructor']
                    assignment.planned_at = parse_datetime(state['starts_at']); assignment.ends_at = parse_datetime(state['ends_at'])
                    assignment.schedule_timezone = state['timezone']; assignment.venue = state['venue']; assignment.status = state['status']
                    assignment.save()
                for extra in existing[len(state['pilots']):]:
                    # Preserve the old assignment ID/history rather than deleting it.
                    extra.crew_session = None; extra.status = 'cancelled'; extra.save(update_fields=['crew_session', 'status'])
                ATCDScheduleLink.objects.update_or_create(source_id=source_id,
                    defaults={'crew': crew, 'snapshot': state, 'imported_by': request.user})
                changes.append({'source_id': source_id, 'before': old, 'after': state})
            save_mapping(rows, maps)
            if changes: ATCDImportLog.objects.create(user=request.user, changes=changes)
            return Response({'applied': len(changes), 'unchanged': sum(i['action'] == 'unchanged' for i in preview)})
    except IntegrityError:
        return Response({'error': 'Конфликт сопоставлений или параллельный импорт. Получите расписание заново.'}, status=409)
