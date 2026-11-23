# views.py
from dateutil.relativedelta import relativedelta
from datetime import timedelta
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import json
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.db.models.functions import TruncDate
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status, viewsets
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render
from django.contrib.auth import authenticate
from rest_framework.authtoken.models import Token
from .models import Pilot, Instructor, Exercise, Session, RatingSession, RatingExercise, AssignmentExercise, \
    TrainingSession, PrintToken
from .permissions import IsInstructorUser, ScopedModelPermission
from .login_security import LoginThrottle, release_success
from .access import pilots_for, instructors_for, templates_for, ratings_for, training_sessions_for, can_manage
from .serializers import PilotSerializer, InstructorSerializer, ExerciseSerializer, SessionSerializer, \
    RatingExerciseSerializer, RatingSubmissionSerializer
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import path, reverse
from django.utils.html import format_html, escape
from .forms import ExcelUploadForm
from .management.commands.load_sessions import Command  # ← используем существующий команд
import os
from django.http import FileResponse, Http404
from django.conf import settings
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, F, Case, When, FloatField
import pandas as pd
from django.http import JsonResponse, HttpResponse
from django.core.serializers.json import DjangoJSONEncoder
from docx.enum.text import WD_ALIGN_PARAGRAPH
from django.shortcuts import get_object_or_404
from django.db.models.functions import Lower
from collections import Counter
from docx import Document
from docx.shared import Pt
import io
import re
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.permissions import AllowAny
from django.db.models import Q


# --- ViewSets ---
class PilotViewSet(viewsets.ModelViewSet):
    queryset = Pilot.objects.all()
    serializer_class = PilotSerializer
    permission_classes = [IsAuthenticated, ScopedModelPermission]

    def get_queryset(self):
        return pilots_for(self.request.user)


class InstructorViewSet(viewsets.ModelViewSet):
    queryset = Instructor.objects.all()
    serializer_class = InstructorSerializer
    permission_classes = [IsAuthenticated, ScopedModelPermission]

    def get_queryset(self):
        return instructors_for(self.request.user)


class ExerciseViewSet(viewsets.ModelViewSet):
    queryset = Exercise.objects.all()
    serializer_class = ExerciseSerializer
    permission_classes = [IsAuthenticated, ScopedModelPermission]

    def get_queryset(self):
        if can_manage(self.request.user, Exercise):
            return self.queryset.all()
        return self.queryset.filter(session__in=templates_for(self.request.user)).distinct()


class SessionViewSet(viewsets.ModelViewSet):
    queryset = Session.objects.all()
    serializer_class = SessionSerializer
    permission_classes = [IsAuthenticated, ScopedModelPermission]

    def get_queryset(self):
        return templates_for(self.request.user)


class PublicObtainAuthToken(ObtainAuthToken):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [LoginThrottle]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'no-store'
        return response

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        release_success(getattr(request, 'login_reservation', None))
        response['Cache-Control'] = 'no-store'
        return response


# --- API: Авторизация ---
@api_view(['POST'])
def login_view(request):
    username = request.data.get("username")
    password = request.data.get("password")
    user = authenticate(username=username, password=password)
    if user and hasattr(user, 'instructor'):
        token, created = Token.objects.get_or_create(user=user)
        return Response({"token": token.key})
    return Response({"error": "Неверные учётные данные или вы не инструктор"}, status=status.HTTP_400_BAD_REQUEST)


# --- API: Информация о пользователе ---
@api_view(['GET'])
@permission_classes([IsAuthenticated, IsInstructorUser])
def current_instructor(request):
    try:
        instructor = Instructor.objects.get(user=request.user)
        serializer = InstructorSerializer(instructor)
        return Response(serializer.data)
    except Instructor.DoesNotExist:
        return Response({'error': 'Инструктор не найден'}, status=status.HTTP_404_NOT_FOUND)


# --- API: Данные для интерфейса ---
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def available_sessions(request):
    pilot_id = request.GET.get('pilot_id')
    if not pilot_id:
        return Response({'error': 'pilot_id обязателен'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        pilot_id = int(pilot_id)
    except:
        return Response({'error': 'pilot_id должен быть числом'}, status=status.HTTP_400_BAD_REQUEST)

    get_object_or_404(pilots_for(request.user), pk=pilot_id)
    completed_ids = ratings_for(request.user).filter(pilot_id=pilot_id).values_list('session_id', flat=True)
    sessions = templates_for(request.user).filter(
        pk__in=training_sessions_for(request.user).filter(pilot_id=pilot_id).values("session_id")
    ).exclude(id__in=completed_ids)
    return Response([{'id': s.id, 'title': s.title} for s in sessions])


@api_view(['GET'])
def session_exercises(request, session_id):
    get_object_or_404(templates_for(request.user), pk=session_id)
    exercises = AssignmentExercise.objects.filter(
        session_id=session_id
    ).select_related('exercise').prefetch_related('exercise__competencies').order_by('order')

    data = []
    for ae in exercises:
        exercise = ae.exercise
        # Получаем список кодов компетенций
        competencies = list(exercise.competencies.values_list('code', flat=True))

        data.append({
            'id': ae.id,
            'name': exercise.name,
            'phase_of_flight': exercise.phase_of_flight,
            'order': ae.order,
            'min_score': exercise.min_score,
            'duration_minutes': exercise.duration_minutes,
            'required_competencies': competencies,  # ← теперь содержит только нужные компетенции
        })

    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_rating_session(request):
    try:
        instructor = Instructor.objects.get(user=request.user)
    except Instructor.DoesNotExist:
        return Response({'error': 'Инструктор не найден'}, status=403)

    serializer = RatingSubmissionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    try:
        with transaction.atomic():
            # Serialise submissions for this scheduled individual result.
            training = get_object_or_404(
                TrainingSession.objects.select_for_update(),
                pk=data['session_id'], instructor=instructor, pilot_id=data['pilot_id'],
            )
            if training.status != 'planned' or RatingSession.objects.filter(
                training_session=training
            ).exists():
                return Response({'error': 'Сессия уже оценена или отменена'}, status=400)
            # The legacy schema allows only one result per pilot/template.
            # Keep this constraint until the separate attempts migration.
            if RatingSession.objects.filter(pilot_id=training.pilot_id, session=training.session).exists():
                return Response({'error': 'Для этого задания уже есть результат. Повторное прохождение требует отдельной попытки.'}, status=400)
            expected = set(AssignmentExercise.objects.filter(
                session_id=training.session_id
            ).values_list('id', flat=True))
            supplied = [item['assignment'].pk for item in data['exercises']]
            if len(supplied) != len(set(supplied)):
                return Response({'error': 'Упражнения не должны повторяться'}, status=400)
            if not expected or set(supplied) != expected:
                return Response({'error': 'Нужны оценки всех упражнений назначенного задания, без посторонних упражнений'}, status=400)
            rating = RatingSession.objects.create(
                pilot=training.pilot, instructor=instructor, session=training.session,
                training_session=training, general_notes=data['general_notes'],
            )
            for item in data['exercises']:
                item.pop('completed', None)
                RatingExercise.objects.create(rating_session=rating, completed=True, **item)
            from .result_versions import publish_initial
            publish_initial(rating, request.user)
            training.status = 'completed'
            training.save(update_fields=['status'])
    except IntegrityError:
        return Response({'error': 'Результат уже сохранён или конфликтует с существующими данными'}, status=409)
    return Response({
        'message': 'Оценка успешно сохранена', 'rating_session_id': rating.id,
        'exercises_saved': len(supplied),
    }, status=201)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def training_sessions_for_instructor(request):
    sessions = training_sessions_for(request.user).select_related(
        'session', 'instructor', 'pilot'
    ).order_by('planned_at', 'id')

    data = []
    for s in sessions:
        # Формируем данные пилота (может быть None? если null=True)
        pilot_data = {'id': s.pilot.id, 'name': s.pilot.name} if s.pilot else None

        data.append({
            'id': s.id,
            'session': {
            'id': s.session.id,
            'title': s.session.title
            },
            'pilot': pilot_data,  # ✅ Один пилот, а не список
            'planned_at': s.planned_at,
            'venue': s.venue,
            'status': s.status
        })

    return Response(data)

@api_view(['GET'])
def pilot_list(request):
    if not request.user.is_authenticated:
        return Response({'error': 'Unauthorized'}, status=401)

    try:
        instructor = request.user.instructor
    except User.instructor.RelatedObjectDoesNotExist:
        return Response({'error': 'У вас нет профиля инструктора.'}, status=403)

    # Получаем ID пилотов, с которыми у инструктора есть сессии (любые статусы)
    pilot_ids = TrainingSession.objects.filter(
        instructor=instructor
    ).values_list('pilot_id', flat=True).distinct()

    # Фильтруем только активных пилотов
    pilots = Pilot.objects.filter(
        id__in=pilot_ids,
        is_active=True
    ).order_by('name')

    return Response([
        {'id': p.id, 'name': p.name}
        for p in pilots
    ])


@api_view(['GET'])
def pilot_detail(request, pk):
    pilot = get_object_or_404(pilots_for(request.user), pk=pk)
    return Response({
        'name': pilot.name,
        'license': pilot.license,
        'experience': pilot.experience,
        'graduated_at': pilot.graduated_at,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ratings_by_pilot(request):
    pilot_id = request.GET.get('pilot_id')
    if not pilot_id:
        return Response({'error': 'pilot_id обязателен'}, status=400)
    try:
        pilot_id = int(pilot_id)
    except:
        return Response({'error': 'pilot_id должен быть числом'}, status=400)

    get_object_or_404(pilots_for(request.user), pk=pilot_id)
    ratings = ratings_for(request.user).filter(pilot_id=pilot_id).prefetch_related(
        'ratingexercise_set__assignment__exercise'
    ).order_by('-created_at')

    data = []
    for r in ratings:
        exercises = [
            {
                'exercise_name': re.assignment.exercise.name,

                'score': re.score
            }
            for re in r.ratingexercise_set.all()
        ]
        data.append({
            'session': {'title': r.session.title},
            'created_at': r.created_at.strftime('%d.%m.%Y %H:%M'),
            'general_notes': r.general_notes,
            'exercises': exercises
        })
    return Response(data)


# --- Веб-интерфейс ---
def index_page(request):
    return render(request, 'pilot_training/index.html')



# РАЗДЕЛ ЗАГРУЗКИ ДАННЫХ И ОТПРАВКИ ШАБЛОНА ИЗ АДМИНКИ-------------------------------------------
@staff_member_required
def upload_sessions_from_excel(request):
    if request.method == "POST":
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['file']
            try:
                # Проверим, что это xlsx
                if not file.name.endswith('.xlsx'):
                    messages.error(request, "Файл должен быть в формате .xlsx")
                    return redirect(request.path)

                # Сохраним во временный файл или передадим напрямую в pandas
                df = pd.read_excel(file, sheet_name='Лист1', engine='openpyxl')
                # Проверим колонки (повтори логику из команды)
                required_cols = {'SESSION_TITLE', 'SESSION_DESC','EXERCISE_TYPE', 'EXERCISE_NAME', 'PHASE_OF_FLIGHT',  'DURATION', 'MIN_SCORE', 'ORDER'}
                df.columns = df.columns.str.strip().str.upper()
                if not required_cols.issubset(df.columns):
                    missing = required_cols - set(df.columns)
                    messages.error(request, f"Не хватает колонок: {missing}")
                    return redirect(request.path)

                # Перезапустим команду, но с нашим файлом
                command = Command()
                # Мы не можем напрямую вызвать handle(), но можем передать путь или файл
                # Временное решение: сохраним файл и передадим путь

                import os
                from django.conf import settings
                upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                file_path = os.path.join(upload_dir, file.name)

                with open(file_path, 'wb+') as destination:
                    for chunk in file.chunks():
                        destination.write(chunk)

                # Теперь вызываем handle команды
                command.handle(file_path=file_path)

                messages.success(request, "✅ Данные успешно загружены из Excel!")
            except Exception as e:
                messages.error(request, f"Ошибка при обработке файла: {e}")
            return redirect(request.path)
    else:
        form = ExcelUploadForm()

    context = {
        'form': form,
        'title': 'Загрузка сессий из Excel',
    }
    return render(request, 'admin/excel_upload.html', context)



@staff_member_required
def upload_pilots_from_excel(request):
    if request.method == "POST":
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            file = request.FILES['file']
            if not file.name.endswith('.xlsx'):
                messages.error(request, "Файл должен быть в формате .xlsx")
                return redirect(request.path)

            upload_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            file_path = os.path.join(upload_dir, file.name)

            with open(file_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)

            try:
                # ВАЖНО: импортируем именно из нового файла!
                from pilot_training.management.commands.load_pilots import Command as LoadPilotsCommand
                cmd = LoadPilotsCommand()
                cmd.handle(file_path=file_path)
                messages.success(request, "✅ Пилоты успешно загружены!")
            except Exception as e:
                messages.error(request, f"Ошибка: {e}")
            return redirect(request.path)
    else:
        form = ExcelUploadForm()

    return render(request, 'admin/upload_pilots.html', {
        'form': form,
        'title': 'Загрузка пилотов из Excel',
    })

# управление и удаление exel
@staff_member_required
def manage_uploads(request):
    uploads_dir = os.path.join(settings.MEDIA_ROOT, 'uploads')

    if not os.path.exists(uploads_dir):
        os.makedirs(uploads_dir)

    # УДАЛЕНИЕ
    if request.method == 'POST':
        filename = request.POST.get('filename')
        if filename:
            if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
                messages.error(request, "Недопустимое имя файла.")
            else:
                file_path = os.path.join(uploads_dir, filename)
                if os.path.exists(file_path) and os.path.commonpath([file_path, uploads_dir]) == uploads_dir:
                    os.remove(file_path)
                    messages.success(request, f"Файл '{filename}' удалён из uploads.")
                else:
                    messages.warning(request, "Файл не найден.")
        return redirect('/admin/manage-uploads/')

    # СПИСОК ВСЕХ ФАЙЛОВ (не только PDF)
    try:
        files = [
            f for f in os.listdir(uploads_dir)
            if os.path.isfile(os.path.join(uploads_dir, f))
        ]
    except Exception:
        files = []

    return render(request, 'admin/manage_uploads.html', {'files': files})

# выгрузка шаблона

@staff_member_required
def download_template(request):
    # Ищем файл в MEDIA_ROOT/example/example.xlsx
    template_path = os.path.join(settings.MEDIA_ROOT, 'example', 'example.xlsx')

    if not os.path.exists(template_path):
        raise Http404("Шаблон не найден")

    response = FileResponse(
        open(template_path, 'rb'),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = 'attachment; filename="example_template.xlsx"'
    return response

# календарь сессий в админку
@staff_member_required
def training_session_calendar_data(request):
    start = request.GET.get('start')
    end = request.GET.get('end')

    # Фильтруем
    queryset = TrainingSession.objects.filter(status='planned') \
        .select_related('session', 'instructor', 'pilot')

    if start and end:
        queryset = queryset.filter(planned_at__range=[start, end])
    else:
        queryset = queryset.filter(planned_at__gte=timezone.now() - timezone.timedelta(days=30))

    events = []
    for s in queryset:
        # Получаем имена пилотов
        pilot_names = s.pilot.name
        title = f"{s.session.title} | {pilot_names} | {s.instructor.name}"

        events.append({
            'title': title,
            'start': s.planned_at.isoformat() if s.planned_at else None,
            'url': f'/admin/pilot_training/trainingsession/{s.id}/change/',
            'backgroundColor': '#28a745',  # Зелёный — всегда
            'borderColor': '#177bbb',
            'extendedProps': {
                'instructor': s.instructor.name,
                'venue': s.venue or '—',
            }
        })

    return JsonResponse(events, safe=False)

# КОНЕЦ РАЗДЕЛА---------------------------------------------------------------

# API-эндпоинт для сессий по пилоту-------------------------------

@login_required
def get_sessions_for_pilot(request):
    pilot_id = request.GET.get('pilot_id')
    if not pilot_id:
        return JsonResponse({'error': 'pilot_id обязателен'}, status=400)
    try:
        pilot_id = int(pilot_id)
    except (TypeError, ValueError):
        return JsonResponse({'error': 'pilot_id должен быть числом'}, status=400)
    get_object_or_404(pilots_for(request.user), pk=pilot_id)
    sessions = training_sessions_for(request.user).filter(
        status='planned', pilot_id=pilot_id
    ).select_related('session', 'instructor', 'pilot').order_by('planned_at')

    data = []
    for s in sessions:
        # Получаем имя пилота (может быть несколько, но раз фильтровали — один)
        pilot_name = s.pilot.name

        data.append({
            'id': s.id,
            'session_id': s.session.id,
            'session_title': s.session.title,
            'pilot_name': pilot_name,
            'planned_at': s.planned_at.isoformat() if s.planned_at else None,
            'venue': s.venue
        })

    return JsonResponse(data, safe=False)
# КОНЕЦ------------------------------


# АНАЛИТИКА---------------------


@login_required
def pilot_analytics_view(request):
    pilots = pilots_for(request.user)
    pilot = None
    progress_data_json = "[]"
    phase_data_json = "[]"
    type_data_json = "[]"
    ebt_data_json = "[]"
    competency_remarks_json = "{}"
    no_data = False
    error = None

    # ✅ Инициализируем переменную ЗАРЕНЕЕ
    general_notes_list = []

    pilot_id = request.GET.get('pilot_id')
    if pilot_id:
        try:
            pilot = get_object_or_404(pilots, id=pilot_id)
            ratings = RatingExercise.objects.filter(
                rating_session__in=ratings_for(request.user), rating_session__pilot=pilot
            ).select_related('rating_session', 'assignment__exercise')

            if not ratings.exists():
                no_data = True
            else:
                # --- Прогресс по времени ---
                progress_data = (
                    ratings
                    .annotate(day=TruncDate('rating_session__created_at'))
                    .values('day')
                    .annotate(date=F('day'), avg_score=Avg('score'))
                    .order_by('date')
                )
                progress_data_json = json.dumps(list(progress_data), default=str)

                # --- Средние по фазам полёта ---
                phase_data = (
                    ratings
                    .values('assignment__exercise__phase_of_flight')  # ← по фазе полёта
                    .annotate(avg_score=Avg('score'))
                    .order_by('-avg_score')
                )
                phase_data_json = json.dumps(list(phase_data))

                # --- По типам маневров ---
                type_data = (
                    ratings
                    .values('assignment__exercise__exercise_type')
                    .annotate(avg_score=Avg('score'))
                    .order_by('-avg_score')
                )
                type_data_json = json.dumps(list(type_data))



                # --- EBT Radar (исправлено) ---
                competency_fields = [
                    'pro_score', 'com_score', 'fpa_score', 'fpm_score',
                    'ltw_score', 'psd_score', 'saw_score', 'wlm_score'
                ]
                competency_labels = ['PRO', 'COM', 'FPA', 'FPM', 'LTW', 'PSD', 'SAW', 'WLM']

                # Создаём агрегации, которые игнорируют 0
                agg_kwargs = {}
                for field in competency_fields:
                    agg_kwargs[field] = Avg(
                        Case(
                            When(**{field + '__gt': 0}, then=field),
                            output_field=FloatField()
                        )
                    )

                agg_data = ratings.aggregate(**agg_kwargs)
                ebt_scores = [round(agg_data[f] or 0, 2) for f in competency_fields]
                ebt_data_json = json.dumps({
                    'labels': competency_labels,
                    'scores': ebt_scores
                })

                # --- Замечания по компетенциям ---
                competency_remarks = {}
                for field, label in zip(competency_fields, competency_labels):
                    remarks_field = field.replace('_score', '_remarks')
                    remarks = (
                        ratings
                        .exclude(**{remarks_field: ""})
                        .exclude(**{remarks_field: None})
                        .values_list(remarks_field, 'assignment__exercise__name', 'assignment__exercise__phase_of_flight')
                    )
                    competency_remarks[label] = [
                        {'remark': str(escape(r[0])), 'maneuver': str(escape(r[1] or '—')), 'phase': str(escape(r[2] or '—'))}
                        for r in remarks if r[0].strip()
                    ]
                competency_remarks_json = json.dumps(competency_remarks)

                # --- Общие замечания из RatingSession ---
                # ✅ Теперь безопасно: переменная уже объявлена выше
                # --- Общие замечания из RatingSession ---
                general_notes_list = (
                    ratings_for(request.user)
                    .filter(pilot=pilot)
                    .exclude(general_notes="")
                    .exclude(general_notes__isnull=True)
                    .select_related('session')  # ← если хочется названия сессии
                    .values(
                        'general_notes',
                        'created_at',
                        'session_id',  # ← ID сессии из TrainingSession
                    )
                    .order_by('-created_at')
                )

        except Pilot.DoesNotExist:
            error = "Пилот не найден."

    # Inline JSON is also used by existing print-independent analytics HTML.
    def script_safe(value):
        return value.replace('&', r'\u0026').replace('<', r'\u003C').replace('>', r'\u003E')
    progress_data_json = script_safe(progress_data_json)
    phase_data_json = script_safe(phase_data_json)
    type_data_json = script_safe(type_data_json)
    ebt_data_json = script_safe(ebt_data_json)
    competency_remarks_json = script_safe(competency_remarks_json)

    # ✅ Передаём в шаблон — даже если пилот не выбран или no_data
    return render(request, 'admin/pilot_analytics.html', {
        'pilots': pilots,
        'pilot': pilot,
        'progress_data_json': progress_data_json,
        'phase_data_json': phase_data_json,
        'type_data_json': type_data_json,
        'ebt_data_json': ebt_data_json,
        'competency_remarks_json': competency_remarks_json,
        'ebt_competencies': ['PRO', 'COM', 'FPA', 'FPM', 'LTW', 'PSD', 'SAW', 'WLM'],
        'general_notes_list': general_notes_list,  # ✅ Всегда определена
        'no_data': no_data,
        'error': error,
    })


# КОНЕЦ------------------------------



# распечатать задание на тренировку
@login_required(login_url="/admin/login/")
def print_rating_clean(request, rating_id):
    rating = get_object_or_404(ratings_for(request.user), id=rating_id)
    # Генерируем новый временный токен при каждом открытии
    token_obj = PrintToken.objects.create(
        rating_session=rating, revision=rating.revisions.first(),
        expires_at=timezone.now() + timedelta(hours=1)
        # НЕ помечаем как used — он станет недействительным после первого использования
    )
    # Ссылка по токену
    secure_print_url = request.build_absolute_uri(
        reverse('pilot_training:print_rating_token', kwargs={'token': token_obj.token})
    )
    rating_exercises = rating.ratingexercise_set.select_related(
        'assignment__exercise'
    ).order_by('assignment__order')

    revision = token_obj.revision
    if revision:
        from .result_versions import print_context
        template_name, context = print_context(revision)
        context['secure_print_url'] = secure_print_url
        return render(request, template_name, context)

    # Определяем тип сессии по title (или по session_type, если есть)
    session_title = rating.session.title
    session_describe = rating.session.description

    if "FTD Сессия 5" in session_title:
        template_name = 'pilot_training/ftd_s5_print_assignment.html'
    elif "FTD" in session_title:
        template_name = 'pilot_training/ftd_print_assignment.html'
    elif "LOFT" in session_describe:
        template_name = 'pilot_training/print_assignment_loft.html'
    else:
        template_name = 'pilot_training/print_assignment.html'

    return render(request, template_name, {
        'rating': rating,
        'rating_exercises': rating_exercises,
        'secure_print_url': secure_print_url,
    })


@login_required(login_url="/admin/login/")
def print_rating_by_token(request, token):
    try:
        token_obj = PrintToken.objects.select_related('rating_session').get(token=token)
    except PrintToken.DoesNotExist:
        return HttpResponse("Ссылка недействительна.", status=410)

    get_object_or_404(ratings_for(request.user), pk=token_obj.rating_session_id)

    if not token_obj.is_valid():
        token_obj.used = True
        token_obj.save(update_fields=['used'])
        return HttpResponse("Срок действия ссылки истёк.", status=403)

    consumed = PrintToken.objects.filter(
        pk=token_obj.pk, used=False, expires_at__gt=timezone.now()
    ).update(used=True)
    if not consumed:
        return HttpResponse('Ссылка уже использована или истекла.', status=403)

    if token_obj.revision_id:
        from .result_versions import print_context
        template_name, context = print_context(token_obj.revision)
        return render(request, template_name, context)
    rating = token_obj.rating_session
    rating_exercises = rating.ratingexercise_set.select_related(
        'assignment__exercise'
    ).order_by('assignment__order')

    # Выбираем шаблон, как в print_rating_clean
    session_title = rating.session.title
    session_describe = rating.session.description

    if "FTD Сессия 5" in session_title:
        template_name = 'pilot_training/ftd_s5_print_assignment.html'
    elif "FTD" in session_title:
        template_name = 'pilot_training/ftd_print_assignment.html'
    elif "LOFT" in session_describe:
        template_name = 'pilot_training/print_assignment_loft.html'
    else:
        template_name = 'pilot_training/print_assignment.html'

    return render(request, template_name, {
        'rating': rating,
        'rating_exercises': rating_exercises,
    })

# @login_required
def pilot_partial(request):
    # === 1. Аутентификация через токен ===
    auth_header = request.META.get('HTTP_AUTHORIZATION')
    if not auth_header or not auth_header.startswith('Token '):
        return HttpResponse("Unauthorized", status=401)

    token_key = auth_header.split(' ')[1]
    try:
        token = Token.objects.select_related('user').get(key=token_key)
        user = token.user
    except Token.DoesNotExist:
        return HttpResponse("Unauthorized", status=401)

    if not user.is_active:
        return HttpResponse('Unauthorized', status=401)

    # === 2. Проверка профиля инструктора ===
    try:
        instructor = user.instructor
    except Exception:
        return HttpResponse("Доступ запрещён: профиль инструктора не найден.", status=403)

    # === 3. Получение параметров ===
    pilot_id = request.GET.get('pilot_id')
    print_rating_id = request.GET.get('print_rating')

    # === 4. Обработка печати по рейтинг-сессии ===
    if print_rating_id:
        try:
            rating = ratings_for(user).get(id=print_rating_id)
        except RatingSession.DoesNotExist:
            return HttpResponse("Сессия не найдена.", status=404)

        # Проверка доступа к пилоту
        if not TrainingSession.objects.filter(
            instructor=instructor,
            pilot=rating.pilot
        ).exists():
            return HttpResponse("Доступ запрещён", status=403)

        rating_exercises = rating.ratingexercise_set.select_related(
            'assignment__exercise'
        ).order_by('assignment__order')
        html = render(request, 'pilot_training/partials/print_wrapper.html', {
            'rating': rating,
            'rating_exercises': rating_exercises,
            'pilot_id': rating.pilot.id,
        })
        return HttpResponse(html)

    # === 5. Просмотр данных пилота ===
    if pilot_id:
        try:
            pilot = Pilot.objects.get(id=pilot_id, is_active=True)
        except Pilot.DoesNotExist:
            return HttpResponse("Пилот не найден или неактивен.", status=404)

        if not TrainingSession.objects.filter(
            instructor=instructor,
            pilot=pilot
        ).exists():
            return HttpResponse("Доступ запрещён: у вас нет сессий с этим пилотом.", status=403)

        rating_sessions = ratings_for(user).filter(pilot=pilot).select_related(
            'session', 'instructor'
        ).order_by('-created_at')
        html = render(request, 'pilot_training/partials/pilot_sessions.html', {
            'pilot': pilot,
            'rating_sessions': rating_sessions,
        })
        return HttpResponse(html)

    # === 6. Список выбора пилотов (по умолчанию) ===
    pilot_ids = TrainingSession.objects.filter(
        instructor=instructor
    ).values_list('pilot_id', flat=True).distinct()

    pilots = Pilot.objects.filter(
        id__in=pilot_ids,
        is_active=True
    ).order_by('name')

    html = render(request, 'pilot_training/partials/pilot_select.html', {
        'pilots': pilots
    })
    return HttpResponse(html)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_docs_list(request):
    from .document_views import reference_filenames
    return JsonResponse({'files': reference_filenames()})

# загрузка pdf admin

@staff_member_required
def upload_pdf(request):
    if request.method == 'POST':
        pdf_file = request.FILES.get('pdf_file')
        if pdf_file:
            if not pdf_file.name.endswith('.pdf'):
                messages.error(request, "Можно загружать только PDF-файлы.")
            else:
                file_path = os.path.join('docs', pdf_file.name)
                default_storage.save(file_path, ContentFile(pdf_file.read()))
                messages.success(request, f"Файл '{pdf_file.name}' успешно загружен.")
                return redirect('/admin/upload-pdf/') # ← должно совпадать с name в urls.py
        else:
            messages.error(request, "Файл не выбран.")
    return render(request, 'admin/upload_pdf.html')

# pdf admin удаление


@staff_member_required
def manage_docs(request):
    docs_dir = os.path.join(settings.MEDIA_ROOT, 'docs')

    # Убедимся, что папка существует
    if not os.path.exists(docs_dir):
        os.makedirs(docs_dir)

    # УДАЛЕНИЕ
    if request.method == 'POST':
        filename = request.POST.get('filename')
        if filename:
            if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
                messages.error(request, "Недопустимое имя файла.")
            else:
                file_path = os.path.join(docs_dir, filename)
                if os.path.exists(file_path) and os.path.commonpath([file_path, docs_dir]) == docs_dir:
                    os.remove(file_path)
                    messages.success(request, f"Файл '{filename}' удалён.")
                else:
                    messages.warning(request, "Файл не найден.")
        return redirect('/admin/manage-docs/')

    # СПИСОК
    try:
        files = [
            f for f in os.listdir(docs_dir)
            if os.path.isfile(os.path.join(docs_dir, f)) and f.endswith('.pdf')
        ]
    except Exception:
        files = []

    return render(request, 'admin/manage_docs.html', {'files': files})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pilot_search(request):
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse([], safe=False)

    # Получаем всех активных пилотов (раз их не тысячи — приемлемо)
    all_pilots = pilots_for(request.user).filter(is_active=True).values('id', 'name')

    # Фильтруем в Python с учётом регистра (Unicode-safe!)
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    matched = [
                  p for p in all_pilots
                  if pattern.search(p['name'])
              ][:15]

    return JsonResponse(matched, safe=False)


@staff_member_required
def training_report(request, pilot_id):
    pilot = get_object_or_404(Pilot, id=pilot_id)

    training_sessions = TrainingSession.objects.filter(
        pilot=pilot,
        status='completed'
    ).select_related('session', 'instructor').order_by('planned_at')

    # 1. Задаём значение по умолчанию СРАЗУ
    ffs_instructor_name = "________________"

    ffs_session = TrainingSession.objects.filter(
        pilot=pilot,
        session__title__icontains='FFS'
    ).filter(
        session__title__icontains='11'
    ).select_related('instructor').first()

    # 2. Теперь безопасно обновляем, если нашли
    if ffs_session and ffs_session.instructor:
        ffs_instructor_name = ffs_session.instructor.name

    context = {
        'pilot': pilot,
        'training_sessions': training_sessions,
        'ffs_instructor_name': ffs_instructor_name,  # ✅ Теперь переменная всегда существует
    }

    return render(request, 'admin/reports/report.html', context)