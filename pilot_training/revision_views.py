from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .access import ratings_for
from .result_versions import acknowledge, correct, revision_data, can_revise


class AcknowledgementInput(serializers.Serializer):
    revision_id = serializers.IntegerField(min_value=1)
    content_hash = serializers.RegexField(r'^[0-9a-f]{64}$')
    event_id = serializers.UUIDField()
    client_time = serializers.DateTimeField(required=False, allow_null=True)


class ExerciseCorrection(serializers.Serializer):
    assignment_id = serializers.IntegerField(min_value=1)
    score = serializers.ChoiceField(choices=[2,3,4,5])


    def get_fields(self):
        fields = super().get_fields()
        for key in ('pro', 'com', 'fpa', 'fpm', 'ltw', 'psd', 'saw', 'wlm'):
            fields[key + '_score'] = serializers.ChoiceField(
                choices=[0, 1, 2, 3, 4, 5], required=False, allow_null=True)
            fields[key + '_remarks'] = serializers.CharField(
                required=False, allow_blank=True)
        return fields


class CorrectionInput(serializers.Serializer):
    revision_id = serializers.IntegerField(min_value=1)
    content_hash = serializers.RegexField(r'^[0-9a-f]{64}$')
    reason = serializers.CharField(allow_blank=False)
    general_notes = serializers.CharField(allow_blank=True)
    exercises = ExerciseCorrection(many=True, allow_empty=False)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def acknowledge_result(request, pk):
    rating = get_object_or_404(ratings_for(request.user), pk=pk)
    data = AcknowledgementInput(data=request.data)
    data.is_valid(raise_exception=True)
    revision = acknowledge(rating.pk, request.user, data.validated_data)
    return Response(revision_data(revision, request.user))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def revisions(request, pk):
    rating = get_object_or_404(ratings_for(request.user), pk=pk)
    if request.method == 'POST':
        if not can_revise(request.user):
            return Response({'error': 'Создание новой версии доступно только ответственному.'}, status=403)
        data = CorrectionInput(data=request.data)
        data.is_valid(raise_exception=True)
        revision = correct(rating.pk, request.user, data.validated_data)
        return Response(revision_data(revision, request.user), status=201)
    return Response([revision_data(rev, request.user) for rev in rating.revisions.select_related(
        'rating__pilot', 'acknowledgement').all()])
