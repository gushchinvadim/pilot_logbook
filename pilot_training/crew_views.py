from django.db.models import Prefetch
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers
from .models import Instructor, TrainingSession, RatingSession
from .serializers import RatingExerciseSerializer
from .crew import pair_assignments


class PairInput(serializers.Serializer):
    training_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), min_length=2, max_length=2)


def own_assignments(instructor):
    return TrainingSession.objects.filter(instructor=instructor).select_related(
        'pilot', 'session'
    ).prefetch_related(Prefetch('ratingsession_set', queryset=RatingSession.objects.filter(instructor=instructor).prefetch_related(
        'ratingexercise_set__assignment'
    )))


def participant(row, *, include_result=False):
    results = list(row.ratingsession_set.all())
    item = {
        'id': row.pk, 'pilot': {'id': row.pilot_id, 'name': row.pilot.name},
        'status': row.status, 'planned_at': row.planned_at, 'ends_at': row.ends_at, 'schedule_timezone': row.schedule_timezone, 'venue': row.venue,
        'has_result': bool(results), 'is_extra': row.is_extra, 'extra_reason': row.extra_reason,
    }
    if include_result:
        result = results[0] if results else None
        item['result'] = None if result is None else {
            'id': result.pk, 'general_notes': result.general_notes,
            'exercises': RatingExerciseSerializer(result.ratingexercise_set.all(), many=True).data,
        }
    return item


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def crew_sessions(request):
    instructor = Instructor.objects.filter(user=request.user).first()
    if instructor is None:
        return Response({'error': 'Доступно назначенному инструктору.'}, status=403)
    if request.method == 'POST':
        data = PairInput(data=request.data)
        data.is_valid(raise_exception=True)
        group = pair_assignments(data.validated_data['training_ids'], instructor=instructor)
        return Response({'crew_id': group.pk}, status=201)
    rows = own_assignments(instructor).exclude(status='cancelled').order_by('planned_at', 'pk')
    groups = {}
    for row in rows:
        key = f'crew:{row.crew_session_id}' if row.crew_session_id else f'single:{row.pk}'
        if key not in groups:
            groups[key] = {
                'key': key, 'crew_id': row.crew_session_id, 'is_extra': row.is_extra,
                'session': {'id': row.session_id, 'title': row.session.title},
                'participants': [],
            }
        groups[key]['participants'].append(participant(row, include_result=True))
    return Response({'instructor_id': instructor.pk, 'sessions': list(groups.values())})
