"""Publish immutable result snapshots; acknowledge only the exact version viewed."""
import copy
import hashlib
import json
from types import SimpleNamespace
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError, PermissionDenied, APIException
from .models import RatingSession, RatingExercise, ResultRevision, ResultAcknowledgement, Exercise
from .serializers import RatingExerciseSerializer


class VersionConflict(APIException):
    status_code = 409
    default_detail = 'Версия результата изменилась. Обновите страницу и ознакомьтесь с актуальной версией.'


def can_revise(user):
    return user.is_authenticated and user.is_active and (user.is_superuser or user.has_perm('pilot_training.revise_result'))


def digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def live_snapshot(rating):
    exercises = []
    for item in rating.ratingexercise_set.select_related('assignment__exercise').order_by('assignment__order', 'pk'):
        data = dict(RatingExerciseSerializer(item).data)
        ex = item.assignment.exercise
        data.update(exercise_name=ex.name, phase_of_flight=ex.phase_of_flight,
                    order=item.assignment.order, exercise_id=ex.pk,
                    exercise_description=ex.description, duration_minutes=ex.duration_minutes,
                    min_score=ex.min_score, progress_sheet_number=ex.progress_sheet_number,
                    skilltest_position=ex.skilltest_position)
        exercises.append(data)
    return {'pilot': {'id': rating.pilot_id, 'name': rating.pilot.name, 'user_id': rating.pilot.user_id},
            'instructor': {'id': rating.instructor_id, 'name': rating.instructor.name},
            'session': {'id': rating.session_id, 'title': rating.session.title, 'description': rating.session.description},
            'training_id': rating.training_session_id, 'created_at': rating.created_at.isoformat(),
            'general_notes': rating.general_notes, 'exercises': exercises}


@transaction.atomic
def publish_initial(rating, actor=None):
    rating = RatingSession.objects.select_for_update().get(pk=rating.pk)
    existing = rating.revisions.first()
    if existing:
        return existing
    snapshot = live_snapshot(rating)
    return ResultRevision.objects.create(rating=rating, version=1, snapshot=snapshot,
        content_hash=digest(snapshot), created_by=actor)


def revision_data(revision, user):
    data = copy.deepcopy(revision.snapshot)
    data['pilot'].pop('user_id', None)
    try:
        ack = revision.acknowledgement
    except ResultAcknowledgement.DoesNotExist:
        ack = None
    latest_id = revision.rating.revisions.values_list('id', flat=True).first()
    data.update(id=revision.rating_id, revision_id=revision.pk, version=revision.version,
        content_hash=revision.content_hash, published_at=revision.published_at,
        change_reason=revision.reason, is_current=revision.pk == latest_id,
        acknowledgement=None if ack is None else {'name': ack.name, 'acknowledged_at': ack.acknowledged_at},
        can_acknowledge=ack is None and revision.pk == latest_id and revision.rating.pilot.user_id == user.pk
            and revision.snapshot['pilot'].get('user_id') == user.pk,
        can_revise=revision.pk == latest_id and can_revise(user))
    return data


@transaction.atomic
def acknowledge(rating_id, user, payload):
    rating = RatingSession.objects.select_for_update().select_related('pilot').get(pk=rating_id)
    if rating.pilot.user_id != user.pk:
        raise PermissionDenied('Ознакомление подтверждает только сам слушатель.')
    revision = rating.revisions.filter(pk=payload['revision_id']).first()
    if not revision or revision.content_hash != payload['content_hash']:
        raise VersionConflict()
    if revision.snapshot['pilot'].get('user_id') != user.pk:
        raise PermissionDenied('Эта версия выпущена для другой учётной записи слушателя.')
    replay = ResultAcknowledgement.objects.filter(event_id=payload['event_id']).first()
    if replay:
        if replay.user_id != user.pk or replay.revision_id != revision.pk:
            raise ValidationError({'error': 'Идентификатор события уже использован.'})
        return revision
    if rating.revisions.first().pk != revision.pk:
        raise VersionConflict()
    existing = ResultAcknowledgement.objects.filter(revision=revision).first()
    if existing:
        return revision
    ResultAcknowledgement.objects.create(revision=revision, user=user, name=rating.pilot.name,
        event_id=payload['event_id'], content_hash=revision.content_hash, client_time=payload.get('client_time'))
    return revision


@transaction.atomic
def correct(rating_id, user, payload):
    if not can_revise(user):
        raise PermissionDenied('Исправление доступно только ответственному с правом создания версии результата.')
    rating = RatingSession.objects.select_for_update().get(pk=rating_id)
    previous = rating.revisions.first()
    if not previous or previous.pk != payload['revision_id'] or previous.content_hash != payload['content_hash']:
        raise VersionConflict()
    old = previous.snapshot
    expected = {item['assignment_id'] for item in old['exercises']}
    rows = payload['exercises']
    ids = [item['assignment_id'] for item in rows]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValidationError({'error': 'Исправление должно содержать тот же полный набор упражнений.'})
    updated = {item['assignment_id']: item for item in rows}
    snapshot = copy.deepcopy(old)
    snapshot['general_notes'] = payload['general_notes']
    for item in snapshot['exercises']:
        item.update(updated[item['assignment_id']])
    revision = ResultRevision.objects.create(rating=rating, version=previous.version+1,
        snapshot=snapshot, content_hash=digest(snapshot), created_by=user, reason=payload['reason'])
    # Keep the legacy reporting projection in sync; the immutable snapshot remains authoritative.
    RatingSession.objects.filter(pk=rating.pk).update(general_notes=snapshot['general_notes'])
    mutable = ['score', 'completed'] + [f'{key}_{suffix}' for key in ('pro','com','fpa','fpm','ltw','psd','saw','wlm') for suffix in ('score','remarks')]
    for item in snapshot['exercises']:
        RatingExercise.objects.filter(rating_session=rating, assignment_id=item['assignment_id']).update(
            **{key: item[key] for key in mutable if key in item})
    return revision


def print_context(revision):
    data = revision.snapshot
    rating = SimpleNamespace(id=revision.rating_id,
        pilot=SimpleNamespace(**data['pilot']), instructor=SimpleNamespace(**data['instructor']),
        session=SimpleNamespace(**data['session']), created_at=parse_datetime(data['created_at']),
        general_notes=data['general_notes'])
    rows=[]
    for item in data['exercises']:
        exercise = Exercise(id=item.get('exercise_id'), name=item['exercise_name'],
            phase_of_flight=item.get('phase_of_flight',''), description=item.get('exercise_description',''),
            duration_minutes=item.get('duration_minutes'), min_score=item.get('min_score',3),
            progress_sheet_number=item.get('progress_sheet_number'), skilltest_position=item.get('skilltest_position'))
        rows.append(SimpleNamespace(**item, assignment=SimpleNamespace(order=item.get('order'),exercise=exercise)))
    title=data['session']['title']; description=data['session'].get('description','')
    template = 'ftd_s5_print_assignment.html' if 'FTD Сессия 5' in title else 'ftd_print_assignment.html' if 'FTD' in title else 'print_assignment_loft.html' if 'LOFT' in description else 'print_assignment.html'
    return 'pilot_training/'+template, {'rating': rating,'rating_exercises':rows}
