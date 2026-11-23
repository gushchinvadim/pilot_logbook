"""Create a local pilot/account only after an explicit manager action."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.views.decorators.debug import sensitive_variables, sensitive_post_parameters
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from .atcd_client import fetch_schedule
from .atcd_views import CanSync
from .models import ATCDPilotLink, ATCDImportLog, Pilot


def can_create_pilot(user):
    return bool(user.is_authenticated and user.is_active and user.has_perms(
        ['pilot_training.sync_atcd', 'pilot_training.add_pilot', 'auth.add_user']))


class CanCreatePilot(BasePermission):
    def has_permission(self, request, view):
        return can_create_pilot(request.user)


class PilotInput(serializers.Serializer):
    start = serializers.DateField()
    end = serializers.DateField()
    source_id = serializers.IntegerField(min_value=1)
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)
    license = serializers.CharField(max_length=20)

    def validate(self, value):
        if not 0 <= (value['end']-value['start']).days <= 92:
            raise serializers.ValidationError('Выберите период до 93 дней.')
        value['username'] = get_user_model().normalize_username(value['username'])
        user = get_user_model()(username=value['username'])
        try:
            user._meta.get_field('username').clean(value['username'], user)
        except DjangoValidationError as error:
            raise serializers.ValidationError({'username': error.messages})
        value['license'] = value['license'].strip().upper()
        return value


@sensitive_post_parameters('password')
@api_view(['POST'])
@permission_classes([CanSync, CanCreatePilot])
@sensitive_variables('value', 'password', 'user')
def create_pilot(request):
    data = PilotInput(data=request.data)
    data.is_valid(raise_exception=True)
    value = data.validated_data
    # Resolve identity from the authenticated source; never accept a name from the browser.
    rows = fetch_schedule(value['start'].isoformat(), value['end'].isoformat())
    names = {p['name'].strip() for row in rows if row.get('status') != 'cancelled'
             for p in row.get('pilots', []) if p['id'] == value['source_id']}
    if len(names) != 1:
        return Response({'error': 'Слушатель не найден однозначно в выбранном расписании ATCD. Получите расписание заново.'}, status=409)
    name = next(iter(names))
    if not name or len(name) > Pilot._meta.get_field('name').max_length:
        return Response({'error': 'Проверьте ФИО слушателя в ATCD.'}, status=400)
    User = get_user_model()
    user = User(username=value['username'], last_name=name.split(' ',1)[0][:150],
                first_name=(name.split(' ',1)[1] if ' ' in name else '')[:150])
    try:
        validate_password(value['password'], user=user)
    except DjangoValidationError as error:
        return Response({'password': error.messages}, status=400)
    try:
        with transaction.atomic():
            # Same lock as schedule confirmation, including concurrent onboarding requests.
            first_user = User.objects.order_by('pk').values_list('pk', flat=True).first()
            list(User.objects.select_for_update().filter(pk=first_user))
            existing = ATCDPilotLink.objects.select_related('pilot').filter(source_id=value['source_id']).first()
            if existing:
                return Response({'error': 'Этот слушатель уже связан с пилотом SIM Training. Обновите список соответствий.',
                                 'pilot_id': existing.pilot_id}, status=409)
            if User.objects.filter(username__iexact=value['username']).exists():
                return Response({'username': ['Такой логин уже существует. Укажите другой логин.']}, status=400)
            if Pilot.objects.filter(license__iexact=value['license']).exists():
                return Response({'license': ['Пилот с таким свидетельством уже существует. Выберите его в списке соответствий.']}, status=400)
            # No staff/superuser rights or permissions are copied from ATCD or request data.
            user.set_password(value['password'])
            user.save()
            pilot = Pilot.objects.create(user=user, name=name, license=value['license'])
            ATCDPilotLink.objects.create(source_id=value['source_id'], pilot=pilot)
            ATCDImportLog.objects.create(user=request.user, changes=[{
                'event': 'pilot_created', 'source_id': value['source_id'], 'pilot_id': pilot.pk, 'user_id': user.pk}])
    except IntegrityError:
        return Response({'error': 'Учётная запись или пилот уже созданы другим запросом. Обновите список соответствий.'}, status=409)
    response = Response({'pilot': {'id': pilot.pk, 'name': pilot.name}, 'source_id': value['source_id'],
                         'username': user.username}, status=201)
    response['Cache-Control'] = 'no-store'
    return response
