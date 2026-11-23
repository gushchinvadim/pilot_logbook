"""Read API for the separate instructor/student React portal."""
from django.shortcuts import get_object_or_404
from django.db.models import Q
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.authentication import BaseAuthentication, TokenAuthentication
from django.core import signing
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .access import training_sessions_for, ratings_for, can_manage, pilots_for
from .models import Pilot, Instructor, TrainingSession
from .serializers import RatingExerciseSerializer
from .views import print_rating_clean
from .result_versions import revision_data, can_revise, print_context
from django.shortcuts import render


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def current_user(request):
    instructor = Instructor.objects.filter(user=request.user).first()
    pilot = Pilot.objects.filter(user=request.user).first()
    roles = []
    if instructor:
        roles.append('instructor')
    if pilot:
        roles.append('student')
    if can_manage(request.user, TrainingSession) or can_revise(request.user) or request.user.has_perm('pilot_training.sync_atcd'):
        roles.append('manager')
    return Response({'id': request.user.pk, 'username': request.user.username,
        'name': (instructor.name if instructor else pilot.name if pilot else request.user.get_full_name()) or request.user.username,
        'can_sync_atcd': request.user.has_perm('pilot_training.sync_atcd'), 'roles': roles, 'instructor_id': instructor.pk if instructor else None,
        'pilot_id': pilot.pk if pilot else None, 'can_revise_results': can_revise(request.user)})


def result_data(result, user=None):
    revision = result.revisions.select_related('acknowledgement').first()
    if revision and user:
        return revision_data(revision, user)
    exercises = []
    for item in result.ratingexercise_set.all():
        data = dict(RatingExerciseSerializer(item).data)
        data.update(exercise_name=item.assignment.exercise.name,
                    phase_of_flight=item.assignment.exercise.phase_of_flight)
        exercises.append(data)
    return {'id': result.pk, 'training_id': result.training_session_id,
        'pilot': {'id': result.pilot_id, 'name': result.pilot.name},
        'session': {'id': result.session_id, 'title': result.session.title},
        'instructor': {'id': result.instructor_id, 'name': result.instructor.name},
        'created_at': result.created_at, 'general_notes': result.general_notes, 'exercises': exercises}


def result_queryset(user):
    return ratings_for(user).select_related('pilot', 'session', 'instructor').prefetch_related(
        'ratingexercise_set__assignment__exercise').order_by('-created_at', '-pk')


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def results(request):
    qs = result_queryset(request.user)
    pilot_id = request.GET.get('pilot_id')
    if pilot_id:
        try:
            pilot_id = int(pilot_id)
        except (TypeError, ValueError):
            return Response({'error': 'pilot_id должен быть числом'}, status=400)
        get_object_or_404(pilots_for(request.user), pk=pilot_id)
        qs = qs.filter(pilot_id=pilot_id)
    return Response([result_data(item, request.user) for item in qs])


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def training_detail(request, pk):
    row = get_object_or_404(training_sessions_for(request.user).select_related('pilot', 'instructor', 'session'), pk=pk)
    result = result_queryset(request.user).filter(training_session=row).first()
    exercises = row.session.assignmentexercise_set.select_related('exercise').prefetch_related('exercise__competencies').order_by('order', 'pk')
    return Response({'id': row.pk, 'status': row.status, 'planned_at': row.planned_at, 'ends_at': row.ends_at, 'schedule_timezone': row.schedule_timezone,
        'venue': row.venue, 'is_extra': row.is_extra, 'extra_reason': row.extra_reason, 'crew_id': row.crew_session_id,
        'pilot': {'id': row.pilot_id, 'name': row.pilot.name},
        'instructor': {'id': row.instructor_id, 'name': row.instructor.name},
        'session': {'id': row.session_id, 'title': row.session.title, 'description': row.session.description},
        'exercises': [{'id': ae.pk, 'order': ae.order, 'name': ae.exercise.name,
            'description': ae.exercise.description, 'phase_of_flight': ae.exercise.phase_of_flight,
            'duration_minutes': ae.exercise.duration_minutes, 'min_score': ae.exercise.min_score,
            'required_competencies': list(ae.exercise.competencies.values_list('code', flat=True))} for ae in exercises],
        'result': result_data(result, request.user) if result else None})


class PrintCookieAuthentication(BaseAuthentication):
    """Short-lived access to one result's HTML; never authenticates other APIs."""
    def authenticate(self, request):
        if request.method != 'GET':
            return None
        try:
            grant = signing.loads(request.COOKIES.get('result_print', ''),
                                  salt='result-print', max_age=300)
            if grant['rating'] != request.parser_context['kwargs']['pk']:
                return None
            user = get_user_model().objects.get(pk=grant['user'], is_active=True)
            if not user.get_session_auth_hash() == grant.get('auth'):
                return None
        except (signing.BadSignature, KeyError, TypeError, get_user_model().DoesNotExist):
            return None
        return user, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def prepare_result_print(request, pk):
    get_object_or_404(ratings_for(request.user), pk=pk)
    path = reverse('pilot_training:print_result', kwargs={'pk': pk})
    response = Response({'url': path})
    response.set_cookie('result_print', signing.dumps({'user': request.user.pk, 'rating': pk, 'auth': request.user.get_session_auth_hash()},
                        salt='result-print'), max_age=300, path=path,
                        httponly=True, secure=request.is_secure(), samesite='Strict')
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['GET'])
@authentication_classes([TokenAuthentication, PrintCookieAuthentication])
@permission_classes([IsAuthenticated])
def print_result(request, pk):
    rating = get_object_or_404(ratings_for(request.user), pk=pk)
    revision_id = request.GET.get('revision')
    if revision_id:
        try:
            revision_id = int(revision_id)
        except (TypeError, ValueError):
            return Response({'error': 'Неверная версия'}, status=400)
        revision = get_object_or_404(rating.revisions, pk=revision_id)
    else:
        revision = rating.revisions.first()
    if not revision:
        response = print_rating_clean(request._request, pk)
        response['Cache-Control'] = 'no-store'
        return response
    template, context = print_context(revision)
    response = render(request, template, context)
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_training_sessions(request):
    # Personal calendar stays personal even for superusers and managers.
    rows = TrainingSession.objects.filter(Q(instructor__user=request.user) | Q(pilot__user=request.user)).select_related('pilot', 'session').order_by('planned_at', 'pk')
    return Response([{'id': row.pk, 'crew_id': row.crew_session_id, 'is_extra': row.is_extra,
        'instructor_id': row.instructor_id,
        'session': {'id': row.session_id, 'title': row.session.title},
        'pilot': {'id': row.pilot_id, 'name': row.pilot.name},
        'planned_at': row.planned_at, 'ends_at': row.ends_at, 'schedule_timezone': row.schedule_timezone, 'venue': row.venue, 'status': row.status} for row in rows])
