from django.contrib import messages
# admin.py
from django.contrib import admin
from django.http import HttpResponseRedirect, JsonResponse
from django.template.response import TemplateResponse
from django.utils.html import format_html
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from . import views
from datetime import timedelta, timezone
from .models import Pilot, Instructor, Exercise, Session, AssignmentExercise, TrainingSession, RatingSession, \
    Competency, PrintToken
from django.urls import path, reverse
from .views import upload_sessions_from_excel, pilot_analytics_view, upload_pilots_from_excel
from django import forms
from django.contrib import admin
from django.shortcuts import render, get_object_or_404

# Настройки админки
admin.site.site_header = 'АУЦ переучивание пилотов'
admin.site.site_title = 'SIM Training'
admin.site.index_title = 'Добро пожаловать в админку'

# Сохраняем оригинальный get_urls
original_get_urls = admin.site.get_urls


def get_custom_urls():
    return [
        path('upload-sessions/', upload_sessions_from_excel, name='upload-sessions'),
        path('analytics/', pilot_analytics_view, name='pilot-analytics'),
        path('upload-pilots/', views.upload_pilots_from_excel, name='upload_pilots'),
    ]


def get_urls():
    return get_custom_urls() + original_get_urls()


# Заменяем метод
admin.site.get_urls = get_urls


# ============ Регистрация моделей ============

@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ('name', 'date_of_birth', 'license', 'company', 'get_token', 'token_actions')
    readonly_fields = ['get_token']
    actions = None

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<int:object_id>/generate-token/', self.admin_site.admin_view(self.generate_or_update_token),
                 name='generate-token'),
        ]
        return custom_urls + urls

    def token_actions(self, obj):
        return format_html(
            '<a class="button" href="{}">Сгенерировать токен</a>',
            reverse('admin:generate-token', args=[obj.id])
        )

    token_actions.short_description = 'Действия'

    def generate_or_update_token(self, request, object_id, *args, **kwargs):
        instructor = Instructor.objects.get(pk=object_id)
        user = instructor.user
        if not user:
            self.message_user(request, "Инструктор не связан с пользователем.")
            return HttpResponseRedirect(f"/admin/pilot_training/instructor/{object_id}")

        token, created = Token.objects.get_or_create(user=user)
        if not created:
            token.delete()
            token = Token.objects.create(user=user)

        self.message_user(request, f"Новый токен успешно сгенерирован: {token.key}")
        return HttpResponseRedirect(f"/admin/pilot_training/instructor/{object_id}")

    def get_token(self, obj):
        try:
            return obj.user.auth_token.key
        except Exception:
            return "—"

    get_token.short_description = 'Токен'


@admin.register(Pilot)
class PilotAdmin(admin.ModelAdmin):
    list_display = (
    'name', 'date_of_birth', 'license', 'graduated_at', 'experience', 'glass_cockpit', 'is_captain', 'contract', 'print_report_link',
    'analytics_link')
    search_fields = ('name', 'license')

    def print_report_link(self, obj):
        url = reverse('pilot_training:training_report', args=[obj.id])  # ← с префиксом!
        return format_html(
            '<a href="{}" target="_blank" class="button">📄 Печать отчёта</a>',
            url
        )
    print_report_link.short_description = 'Отчёт'

    @admin.display(description='Аналитика')
    def analytics_link(self, obj):
        return format_html(
            '<a href="/admin/analytics/?pilot_id={}" target="_blank">📈 Посмотреть</a>',
            obj.id
        )

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        try:
            pilot = Pilot.objects.get(id=object_id)
            extra_context['analytics_url'] = f'/admin/analytics/?pilot_id={pilot.id}'
        except Pilot.DoesNotExist:
            pass
        return super().change_view(request, object_id, form_url, extra_context)

    change_form_template = 'admin/pilot_change_form.html'


# ✅ НОВАЯ МОДЕЛЬ: Компетенции
@admin.register(Competency)
class CompetencyAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'exercises_count')
    search_fields = ('code', 'name')
    readonly_fields = ('code',)  # Код нельзя менять после создания

    def exercises_count(self, obj):
        """Показывает количество упражнений, использующих эту компетенцию"""
        count = obj.exercises.count()
        if count > 0:
            url = reverse('admin:pilot_training_exercise_changelist') + f'?competencies__id__exact={obj.id}'
            return format_html('<a href="{}">{}</a>', url, count)
        return count

    exercises_count.short_description = 'Используется в упражнениях'


# ✅ ОБНОВЛЁННАЯ МОДЕЛЬ: Упражнения с компетенциями
@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ('name', 'phase_of_flight', 'exercise_type', 'min_score', 'competencies_list', 'sessions_list')
    list_filter = ('exercise_type', 'phase_of_flight', 'competencies')
    search_fields = ('name', 'phase_of_flight')
    filter_horizontal = ('competencies',)  # ✅ Удобный виджет для ManyToMany

    fieldsets = (
        ('Основная информация', {
            'fields': ('name', 'phase_of_flight', 'exercise_type', 'description')
        }),
        ('Параметры упражнения', {
            'fields': ('duration_minutes', 'min_score', 'progress_sheet_number', 'skilltest_position')
        }),
        ('Компетенции EBT', {
            'fields': ('competencies',),
            'description': 'Выберите компетенции, которые оцениваются в данном упражнении'
        }),
    )

    def competencies_list(self, obj):
        """Отображает список компетенций в списке упражнений"""
        competencies = obj.competencies.all()
        if competencies.exists():
            return ", ".join([c.code.upper() for c in competencies])
        return "—"

    competencies_list.short_description = 'Компетенции'
    competencies_list.admin_order_field = 'competencies__code'

    def sessions_list(self, obj):
        sessions = Session.objects.filter(exercises=obj).distinct()
        return ", ".join([s.title for s in sessions]) if sessions.exists() else "—"

    sessions_list.short_description = "Сессии"


@admin.register(AssignmentExercise)
class AssignmentExerciseAdmin(admin.ModelAdmin):
    list_display = ('session', 'order', 'exercise')
    list_filter = ('session', 'exercise__exercise_type')


class AssignmentExerciseInline(admin.TabularInline):
    model = AssignmentExercise
    extra = 0
    fields = ('exercise', 'order')


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'exercise_count')
    inlines = [AssignmentExerciseInline]

    def exercise_count(self, obj):
        return obj.assignmentexercise_set.count()

    exercise_count.short_description = "Кол-во упражнений"


class TrainingSessionForm(forms.ModelForm):
    class Meta:
        model = TrainingSession
        fields = '__all__'


@admin.register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
    form = TrainingSessionForm
    list_display = ['__str__', 'instructor', 'planned_at', 'status']
    list_filter = ('session', 'instructor', 'planned_at', 'venue', 'pilot')
    search_fields = ('pilot__name', 'instructor__name', 'session__title')
    date_hierarchy = 'planned_at'
    ordering = ['-planned_at']
    readonly_fields = ['crew_session']
    actions = ['pair_selected_assignments']

    @admin.action(description="Объединить два выбранных занятия в экипаж", permissions=['change'])
    def pair_selected_assignments(self, request, queryset):
        from .crew import pair_assignments
        from rest_framework.exceptions import APIException
        try:
            group = pair_assignments(list(queryset.values_list('pk', flat=True)))
        except APIException as exc:
            self.message_user(request, str(exc.detail), level=messages.ERROR)
        else:
            self.message_user(request, f"Создана экипажная сессия {group.pk}. Результаты пилотов сохранены.")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "instructor":
            kwargs["queryset"] = Instructor.objects.filter(user__is_active=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('calendar/', self.admin_site.admin_view(self.calendar_view), name='training_session_calendar'),
            path('api/calendar-events/', self.admin_site.admin_view(self.calendar_events), name='calendar_events'),
        ]
        return custom_urls + urls

    def calendar_view(self, request):
        context = {
            **self.admin_site.each_context(request),
            'title': 'Календарь сессий',
        }
        return TemplateResponse(request, 'admin/trainingsession_calendar.html', context)

    def calendar_events(self, request):
        sessions = TrainingSession.objects.filter(
            status='planned',
            planned_at__isnull=False
        ).select_related('session', 'instructor', 'pilot')

        events = []
        for s in sessions:
            pilot_name = s.pilot.name if s.pilot else "Без пилота"
            instructor_name = s.instructor.name
            title = f"{s.session.title} | {pilot_name} | {instructor_name}"
            end = s.planned_at + timedelta(hours=4)

            events.append({
                'id': s.id,
                'title': title,
                'start': s.planned_at.isoformat(),
                'end': end.isoformat(),
                'url': reverse('admin:pilot_training_trainingsession_change', args=[s.id]),
                'extendedProps': {
                    'instructor': s.instructor.name,
                    'venue': s.venue or '—',
                }
            })

        return JsonResponse(events, safe=False)


@admin.register(RatingSession)
class RatingSessionAdmin(admin.ModelAdmin):
    list_display = ['session', 'pilot', 'instructor', 'created_at']
    list_filter = ['instructor', 'pilot']
    search_fields = ['pilot__name', 'instructor__name', 'session__title']
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('completed-list/', self.admin_site.admin_view(self.completed_list_view),
                 name='rating_session_completed_list'),
            path('completed/<int:rating_id>/', self.admin_site.admin_view(self.completed_detail_view),
                 name='rating_session_completed_detail'),
        ]
        return custom_urls + urls

    def completed_list_view(self, request):
        """Список всех выполненных заданий"""
        # Берём все, так как нет поля статуса
        ratings = RatingSession.objects.select_related(
            'session', 'pilot', 'instructor'
        ).order_by('-created_at')

        context = {
            **self.admin_site.each_context(request),
            'title': 'Выполненные задания',
            'ratings': ratings,
        }
        return render(request, 'admin/rating_completed_list.html', context)

    from django.shortcuts import redirect, reverse

    def completed_detail_view(self, request, rating_id):
        """Вызов функции печати напрямую"""
        from pilot_training.views import print_rating_clean
        return print_rating_clean(request, rating_id)