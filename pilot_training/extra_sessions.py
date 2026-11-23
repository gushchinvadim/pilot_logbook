"""Validation for local, manually scheduled out-of-programme training."""
from datetime import timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.core.exceptions import ValidationError


def validate_extra(row):
    from .models import TrainingSession, RatingSession, ATCDScheduleLink, AssignmentExercise
    errors = {}
    if row.crew_session_id and ATCDScheduleLink.objects.filter(crew_id=row.crew_session_id).exists():
        errors['is_extra'] = 'Назначение из ATCD нельзя превращать в EXTRA. Создайте отдельное назначение в SIM Training.'
    if not row.planned_at: errors['planned_at'] = 'Укажите начало EXTRA-сессии.'
    if not row.ends_at: errors['ends_at'] = 'Укажите окончание EXTRA-сессии.'
    if row.planned_at and row.ends_at and row.ends_at <= row.planned_at:
        errors['ends_at'] = 'Окончание должно быть позже начала.'
    try:
        ZoneInfo(row.schedule_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        errors['schedule_timezone'] = 'Укажите действительный часовой пояс тренажёра.'
    if row.session_id and not AssignmentExercise.objects.filter(session_id=row.session_id).exists():
        errors['session'] = 'Сначала добавьте нужные упражнения в шаблон EXTRA-задания.'
    if row.pilot_id and row.session_id:
        other = TrainingSession.objects.filter(pilot_id=row.pilot_id, session_id=row.session_id).exclude(pk=row.pk).exclude(status='cancelled')
        ratings = RatingSession.objects.filter(pilot_id=row.pilot_id, session_id=row.session_id)
        if row.pk: ratings = ratings.exclude(training_session_id=row.pk)
        if other.exists() or ratings.exists():
            errors['session'] = 'Для EXTRA создайте отдельный шаблон задания с нужными упражнениями: выбранное задание уже назначалось этому пилоту.'
    if errors: raise ValidationError(errors)
    if row.status != 'planned': return
    candidates = TrainingSession.objects.filter(status='planned', planned_at__lt=row.ends_at).exclude(pk=row.pk)
    if row.crew_session_id: candidates = candidates.exclude(crew_session_id=row.crew_session_id)
    same_meeting = []
    conflicts = []
    for other in candidates.select_related('pilot', 'instructor'):
        if (other.ends_at or other.planned_at + timedelta(hours=4)) <= row.planned_at: continue
        if other.pilot_id == row.pilot_id:
            conflicts.append('Пилот уже занят в это время.')
        if other.instructor_id == row.instructor_id:
            # Before explicit pairing, allow the matching second pilot's assignment only.
            if other.is_extra and other.session_id == row.session_id and other.planned_at == row.planned_at and other.ends_at == row.ends_at and other.venue == row.venue and other.schedule_timezone == row.schedule_timezone:
                same_meeting.append(other)
            else:
                conflicts.append('Инструктор уже занят в это время.')
    if len(same_meeting) > 1: conflicts.append('В EXTRA-сессии допускаются не более двух пилотов.')
    if conflicts: raise ValidationError(list(dict.fromkeys(conflicts)))
