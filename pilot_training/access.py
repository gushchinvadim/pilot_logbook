"""Object scopes shared by the API and document views."""
from django.db.models import Q
from .models import Pilot, Instructor, TrainingSession, RatingSession, Session


def authenticated(user):
    return user.is_authenticated and user.is_active


def can_manage(user, model, action="view"):
    return authenticated(user) and (user.is_superuser or user.has_perm(
        f"pilot_training.{action}_{model._meta.model_name}"
    ))


def training_sessions_for(user):
    qs = TrainingSession.objects.all()
    if not authenticated(user):
        return qs.none()
    if can_manage(user, TrainingSession):
        return qs
    return qs.filter(Q(instructor__user=user) | Q(pilot__user=user))


def pilots_for(user):
    qs = Pilot.objects.all()
    if not authenticated(user):
        return qs.none()
    if can_manage(user, Pilot):
        return qs
    return qs.filter(Q(user=user) | Q(
        pk__in=TrainingSession.objects.filter(instructor__user=user).values("pilot_id")
    )).distinct()


def ratings_for(user):
    qs = RatingSession.objects.all()
    if not authenticated(user):
        return qs.none()
    if can_manage(user, RatingSession) or (authenticated(user) and user.has_perm('pilot_training.revise_result')):
        return qs
    return qs.filter(Q(pilot__user=user) | Q(instructor__user=user) | Q(
        pilot_id__in=TrainingSession.objects.filter(instructor__user=user).values('pilot_id')
    )).distinct()


def templates_for(user):
    qs = Session.objects.all()
    if can_manage(user, Session):
        return qs
    return qs.filter(pk__in=training_sessions_for(user).values("session_id"))


def instructors_for(user):
    qs = Instructor.objects.all()
    if can_manage(user, Instructor):
        return qs
    if not authenticated(user):
        return qs.none()
    return qs.filter(Q(user=user) | Q(
        pk__in=training_sessions_for(user).values("instructor_id")
    )).distinct()
