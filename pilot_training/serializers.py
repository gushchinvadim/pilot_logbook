from rest_framework import serializers
from pilot_training.models import Pilot, Instructor, Exercise, Session, RatingExercise, AssignmentExercise


class PilotSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pilot
        fields = ['id',
                  'name',
                  'date_of_birth',
                  'license',
                  'graduated_at',
                  'experience',
                  'glass_cockpit',
                  'is_captain',
                  'contract',
              ]

class InstructorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instructor
        fields = ['id', 'name', 'license']

class ExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exercise
        fields = ['name','description','duration_minutes','min_score', 'progress_sheet_number','skilltest_position',]

class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Session
        fields = ['title', 'description']


class RatingExerciseSerializer(serializers.ModelSerializer):
    assignment_id = serializers.PrimaryKeyRelatedField(
        queryset=AssignmentExercise.objects.all(),
        source='assignment'
    )

    class Meta:
        model = RatingExercise
        fields = [
            'assignment_id',
            'score',
            'completed',
            # EBT компетенции
            'pro_score', 'pro_remarks',
            'com_score', 'com_remarks',
            'fpa_score', 'fpa_remarks',
            'fpm_score', 'fpm_remarks',
            'ltw_score', 'ltw_remarks',
            'psd_score', 'psd_remarks',
            'saw_score', 'saw_remarks',
            'wlm_score', 'wlm_remarks',
        ]

    def create(self, validated_data):
        # Убираем completed, если не передано
        validated_data.setdefault('completed', False)
        return super().create(validated_data)

class RatingSubmissionSerializer(serializers.Serializer):
    pilot_id = serializers.IntegerField(min_value=1)
    session_id = serializers.IntegerField(min_value=1)
    general_notes = serializers.CharField(required=False, default='', allow_blank=True)
    exercises = RatingExerciseSerializer(many=True, allow_empty=False)
