"""Pair individual assignments explicitly, retaining dates, results and IDs."""
from django.db import transaction
from rest_framework.exceptions import ValidationError, NotFound
from .models import CrewSession, TrainingSession


@transaction.atomic
def pair_assignments(ids, *, instructor=None):
    if len(ids) != 2 or len(set(ids)) != 2:
        raise ValidationError({'error': 'Выберите ровно две разные записи занятия.'})
    # Lock in a deterministic order, including on concurrent pairing requests.
    rows = list(TrainingSession.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    if len(rows) != 2 or (instructor and any(row.instructor_id != instructor.pk for row in rows)):
        raise NotFound('Назначенные занятия не найдены.')
    first, second = rows
    if any(row.crew_session_id for row in rows):
        raise ValidationError({'error': 'Одно из занятий уже связано с экипажем.'})
    if first.pilot_id == second.pilot_id:
        raise ValidationError({'error': 'В экипаже должны быть два разных пилота.'})
    if first.session_id != second.session_id or first.instructor_id != second.instructor_id:
        raise ValidationError({'error': 'Нужны одинаковое задание и один инструктор.'})
    if any(row.status == 'cancelled' for row in rows):
        raise ValidationError({'error': 'Отменённые занятия нельзя объединять.'})
    group = CrewSession.objects.create()
    TrainingSession.objects.filter(pk__in=ids).update(crew_session=group)
    return group
