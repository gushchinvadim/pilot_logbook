
# pilot_training/models.py
import uuid
# from .models import RatingSession  # убедись, что это правильный импорт
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth.models import User
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from pilot_training import forms


class Pilot(models.Model):
    user = models.OneToOneField(User, on_delete=models.PROTECT,
                                help_text="Удаление пользователя запрещено, если он привязан к тренировке.", null=False)
    name = models.CharField("ФИО пилота", max_length=50)
    date_of_birth = models.DateField("Дата рождения", null=True, blank=True)
    graduated_at = models.CharField("Какое учебное заведение закончил, год окончания", max_length=50, default="Unknown")
    license = models.CharField("Номер лицензии, дата выдачи", max_length=20, unique=True)
    experience = models.PositiveIntegerField("Общий налет часов", default=0, null=False, blank=False)
    glass_cockpit = models.BooleanField("Опыт стеклянной кабины", default=False)
    is_captain = models.BooleanField("Является капитаном", default=False)
    contract = models.CharField("Номер договора на обучение, дата начала", max_length=50, null=True, blank=True)
    is_active = models.BooleanField("Активен", default=True)

    def __str__(self):
        if self.name:
            return str(self.name)
        return f"Пилот {self.user.username}"
    class Meta:
        verbose_name = "Пилот"
        verbose_name_plural = "Пилоты"

class Instructor(models.Model):
    user = models.OneToOneField(User, on_delete=models.PROTECT,
                                help_text="Удаление пользователя запрещено, если он привязан к тренировке.", null=False)
    name = models.CharField("ФИО инструктора", max_length=50)
    date_of_birth = models.DateField("Дата рождения", null=True, blank=True)
    license = models.CharField("Номер лицензии, дата выдачи", max_length=20, unique=True)
    company = models.CharField("Представляет организацию", default="NordStar")

    def __str__(self):
        if self.name:
            return str(self.name)
        return f"Пилот {self.user.username}"
    class Meta:
        verbose_name = "Инструктор"
        verbose_name_plural = "Инструкторы"

class Competency(models.Model):
    CODE_CHOICES = [
        ('pro', 'PRO — Процедуры'),
        ('com', 'COM — Коммуникация'),
        ('fpa', 'FPA — Управление траекторией (автоматика)'),
        ('fpm', 'FPM — Управление траекторией (ручное)'),
        ('ltw', 'LTW — Работа в команде, лидерство'),
        ('psd', 'PSD — Решение проблем'),
        ('saw', 'SAW — Ситуационная осведомлённость'),
        ('wlm', 'WLM — Управление нагрузкой'),
    ]
    code = models.CharField("Код", max_length=10, choices=CODE_CHOICES, unique=True)
    name = models.CharField("Название", max_length=100)

    def __str__(self):
        return self.get_code_display()

    class Meta:
        verbose_name = "Компетенция"
        verbose_name_plural = "Компетенции"

class Exercise(models.Model):
    name = models.CharField("Название упражнения", max_length=255)
    phase_of_flight = models.CharField("Фаза полёта", max_length=100, blank=True)
    exercise_type = models.CharField("Тип маневра", max_length=20, blank=False)
    description = models.TextField("Доп. описание", blank=True, help_text="Детали, например: 'встречный ветер', 'с отказом'")
    duration_minutes = models.PositiveIntegerField("Длительность (мин)", null=True, blank=True)
    min_score = models.PositiveSmallIntegerField("Мин. балл", default=3)
    progress_sheet_number = models.CharField("Пункт прогресса", null=True, blank=True)
    skilltest_position = models.CharField("Соответствие SKILL TEST", null=True, blank=True)
    competencies = models.ManyToManyField(
        Competency,
        verbose_name="Оцениваемые компетенции",
        blank=True,
        related_name='exercises'
    )

    def __str__(self):
        return f"{self.name} ({self.phase_of_flight})"

    class Meta:
        verbose_name = "Упражнение"
        verbose_name_plural = "Упражнения"
        # Уникальность по имени, чтобы избежать дубликатов
        unique_together = ('name', 'phase_of_flight', 'description')


class Session(models.Model):
    """
    Шаблон тренировочного задания — набор упражнений.
    Создаётся админом, не привязан к пилоту.
    """
    title = models.CharField("Название задания", max_length=200)
    description = models.TextField("Описание", blank=True)
    exercises = models.ManyToManyField(Exercise, through='AssignmentExercise', verbose_name="Упражнения")

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Тренировочное задание (шаблон)"
        verbose_name_plural = "Тренировочные задания (шаблоны)"

class AssignmentExercise(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)
    order = models.PositiveIntegerField("Порядок упражнения", null=True, blank=True)

    class Meta:
        unique_together = ('session', 'exercise')
        verbose_name = "Упражнение в сессии"
        verbose_name_plural = "Упражнения в сессиях"
        ordering = ['order']

    def __str__(self):
        return f"{self.session.title} → {self.exercise.name}"

class RatingSession(models.Model):
    """
    Оценка всей сессии пилота инструктором.
    Одна сессия — одна оценка.
    """
    pilot = models.ForeignKey(Pilot, on_delete=models.CASCADE, verbose_name="Пилот")
    session = models.ForeignKey(Session, on_delete=models.CASCADE, verbose_name="Сессия")
    instructor = models.ForeignKey(Instructor, on_delete=models.CASCADE, verbose_name="Инструктор")
    created_at = models.DateTimeField("Дата и время оценки", auto_now_add=True)
    general_notes = models.TextField("Общие замечания", blank=True)
    training_session = models.ForeignKey(
        'TrainingSession',
        on_delete=models.CASCADE,
        verbose_name="Запланированная сессия",
        null=True,
        blank=True
    )

    def save(self, *args, **kwargs):
        if self.pk and self.revisions.exists():
            raise ValidationError("Опубликованный результат изменяется только созданием новой версии через ответственного.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.pilot.name} — {self.session.title} ({self.instructor.name})"

    class Meta:
        verbose_name = "Оценка сессии"
        verbose_name_plural = "Оценки сессий"
        unique_together = ('pilot', 'session')  # Пилот не может проходить одну сессию дважды


class RatingExercise(models.Model):
    """
    Оценка одного упражнения в рамках сессии.
    Теперь — по компетенциям EBT: PRO, COM, FPA, FPM, LTW, PSD, SAW, WLM.
    """
    rating_session = models.ForeignKey(RatingSession, on_delete=models.CASCADE, verbose_name="Оценка сессии")
    assignment = models.ForeignKey(AssignmentExercise, on_delete=models.CASCADE, verbose_name="Упражнение в сессии")
    score = models.PositiveSmallIntegerField("Оценка", choices=[(2, '2'), (3, '3'), (4, '4'), (5, '5')])
    completed = models.BooleanField(default=False)

    # Выбор для оценок: 0–5
    SCORE_CHOICES = [
        (0, '0 : Не оценивалось'),
        (1, '1 : Небезопасный'),
        (2, '2 : Минимально допустимый'),
        (3, '3 : Стандартный'),
        (4, '4 : Эффективный'),
        (5, '5 : Образцовый'),
    ]

    # Каждая компетенция — пара: оценка + текстовые замечания
    pro_score = models.PositiveSmallIntegerField("PRO — Процедуры", choices=SCORE_CHOICES, default=0, null=True, blank=True)
    pro_remarks = models.TextField("Замечания по PRO", blank=True)

    com_score = models.PositiveSmallIntegerField("COM — Коммуникация", choices=SCORE_CHOICES, default=0, null=True, blank=True)
    com_remarks = models.TextField("Замечания по COM", blank=True)

    fpa_score = models.PositiveSmallIntegerField("FPA — Управление траекторией (автоматика)", choices=SCORE_CHOICES, default=0, null=True, blank=True)
    fpa_remarks = models.TextField("Замечания по FPA", blank=True)

    fpm_score = models.PositiveSmallIntegerField("FPM — Управление траекторией (ручное)", choices=SCORE_CHOICES, default=0, null=True, blank=True)
    fpm_remarks = models.TextField("Замечания по FPM", blank=True)

    ltw_score = models.PositiveSmallIntegerField("LTW — Работа в команде, лидерство", choices=SCORE_CHOICES, default=0, null=True, blank=True)
    ltw_remarks = models.TextField("Замечания по LTW", blank=True)

    psd_score = models.PositiveSmallIntegerField("PSD — Решение проблем", choices=SCORE_CHOICES, default=0, null=True, blank=True)
    psd_remarks = models.TextField("Замечания по PSD", blank=True)

    saw_score = models.PositiveSmallIntegerField("SAW — Ситуационная осведомлённость", choices=SCORE_CHOICES, default=0, null=True, blank=True)
    saw_remarks = models.TextField("Замечания по SAW", blank=True)

    wlm_score = models.PositiveSmallIntegerField("WLM — Управление нагрузкой", choices=SCORE_CHOICES, default=0, null=True, blank=True)
    wlm_remarks = models.TextField("Замечания по WLM", blank=True)

    def save(self, *args, **kwargs):
        if self.rating_session_id and ResultRevision.objects.filter(rating_id=self.rating_session_id).exists():
            raise ValidationError("Оценки опубликованы. Требуется новая версия результата.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if ResultRevision.objects.filter(rating_id=self.rating_session_id).exists():
            raise ValidationError("Нельзя удалить опубликованную оценку.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.assignment.exercise.name} — {self.overall_score()}"

    def overall_score(self):
        """Средняя оценка по всем компетенциям (игнорируя 0)"""
        scores = [
            self.pro_score, self.com_score, self.fpa_score, self.fpm_score,
            self.ltw_score, self.psd_score, self.saw_score, self.wlm_score
        ]
        non_zero = [s for s in scores if s is not None and s > 0]
        return round(sum(non_zero) / len(non_zero), 1) if non_zero else 0

    class Meta:
        verbose_name = "Оценка упражнения (EBT)"
        verbose_name_plural = "Оценки упражнений (EBT)"
        ordering = ['assignment__order']

class TrainingProgram(models.Model):
    name = models.CharField("Название программы", max_length=100)
    sessions = models.ManyToManyField(Session, verbose_name="Сессии программы")



class CrewSession(models.Model):
    """An explicit pair of existing individual assignments; no result is moved."""
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Экипажная сессия {self.pk}"

    class Meta:
        verbose_name = "Экипажная сессия"
        verbose_name_plural = "Экипажные сессии"


class TrainingSession(models.Model):
    """
    Конкретное запланированное занятие: сессия + пилот + инструктор + время + место
    """
    crew_session = models.ForeignKey(
        CrewSession, null=True, blank=True, on_delete=models.PROTECT,
        related_name='participants', verbose_name="Экипажная сессия", editable=False,
    )
    session = models.ForeignKey(Session, on_delete=models.CASCADE, verbose_name="Тренировочное задание")
    pilot = models.ForeignKey(Pilot, on_delete=models.CASCADE, verbose_name="Пилот")
    instructor = models.ForeignKey(Instructor, on_delete=models.CASCADE, verbose_name="Инструктор")
    venue = models.CharField("Место проведения", max_length=100, default="Тренажерный центр", null=True, blank=True)
    planned_at = models.DateTimeField("Дата и время", null=True, blank=True)

    STATUS_CHOICES = [
        ('planned', 'Запланирована'),
        ('completed', 'Проведена'),
        ('cancelled', 'Отменена'),
    ]
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default='planned')

    def __str__(self):
        if self.planned_at:
            return f"{self.session.title} — {self.pilot.name} ({self.planned_at.strftime('%d.%m.%Y %H:%M')})"
        return f"{self.session.title} — {self.pilot.name} (без времени)"

    def clean(self):
        from django.db.models import Q

        if self.crew_session_id:
            peers = TrainingSession.objects.filter(crew_session_id=self.crew_session_id).exclude(pk=self.pk)
            if peers.count() != 1 or peers.filter(pilot_id=self.pilot_id).exists() or peers.exclude(
                session_id=self.session_id, instructor_id=self.instructor_id
            ).exists():
                raise ValidationError(
                    "Участники экипажа должны иметь разных пилотов, одинаковое задание и одного инструктора. "
                    "Нельзя менять эти поля только у одного участника."
                )

        if not self.planned_at:
            return  # ошибка будет при валидации поля

        # Окно ±30 минут — для групповых сессий
        time_window = timedelta(minutes=30)
        start_window = self.planned_at - time_window
        end_window = self.planned_at + time_window

        errors = []

        # --- Проверка: пилот не занят в это время ---
        if self.pilot:
            pilot_conflicts = TrainingSession.objects.filter(
                pilot=self.pilot,
                planned_at__range=(start_window, end_window),
                status='planned'
            ).exclude(pk=self.pk)

            if pilot_conflicts.exists():
                conflict = pilot_conflicts.first()
                errors.append(f"Пилот '{self.pilot.name}' уже занят: {conflict}")

        # --- Проверка: инструктор не ведёт ДРУГУЮ сессию в это время ---
        if self.instructor and self.session:
            instructor_conflicts = TrainingSession.objects.filter(
                instructor=self.instructor,
                planned_at__range=(start_window, end_window),
                status='planned'
            ).exclude(pk=self.pk)

            # Проверяем, есть ли конфликт с ДРУГОЙ сессией
            has_real_conflict = False
            for ts in instructor_conflicts:
                if ts.session != self.session:
                    has_real_conflict = True
                    break

            if has_real_conflict:
                # Берём первую сессию с другим session
                conflict = instructor_conflicts.exclude(
                    session=self.session).first() or instructor_conflicts.first()
                errors.append(
                    f"Инструктор '{self.instructor.name}' уже ведёт другую сессию: {conflict}. "
                    "Нельзя вести две разные сессии одновременно."
                )

        if errors:
            raise ValidationError(errors)

        super().clean()

    class Meta:
        verbose_name = "Запланированная сессия"
        verbose_name_plural = "Запланированные сессии"
        ordering = ['planned_at']


class PrintToken(models.Model):
    revision = models.ForeignKey('ResultRevision', null=True, blank=True, on_delete=models.PROTECT)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    rating_session = models.ForeignKey(RatingSession, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    def is_valid(self):
        now = timezone.now()
        return not self.used and now <= self.expires_at

    def __str__(self):
        return f"PrintToken for {self.rating_session.id} (valid: {self.is_valid()})"










class ImmutableQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("История результата неизменяема.")

    def delete(self):
        raise ValidationError("История результата не удаляется.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("История результата неизменяема.")


class ImmutableRecord(models.Model):
    objects = ImmutableQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Запись истории неизменяема.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Запись истории не удаляется.")

    class Meta:
        abstract = True


class ResultRevision(ImmutableRecord):
    rating = models.ForeignKey(RatingSession, on_delete=models.PROTECT, related_name='revisions')
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    content_hash = models.CharField(max_length=64)
    published_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-version']
        constraints = [models.UniqueConstraint(fields=['rating', 'version'], name='unique_result_revision')]
        permissions = [('revise_result', 'Может создавать исправленную версию результата')]
        verbose_name = 'Версия результата'
        verbose_name_plural = 'Версии результатов'


class ResultAcknowledgement(ImmutableRecord):
    revision = models.OneToOneField(ResultRevision, on_delete=models.PROTECT, related_name='acknowledgement')
    user = models.ForeignKey(User, on_delete=models.PROTECT)
    name = models.CharField(max_length=200)
    event_id = models.UUIDField(unique=True)
    content_hash = models.CharField(max_length=64)
    acknowledged_at = models.DateTimeField(default=timezone.now)
    client_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Ознакомление с результатом'
        verbose_name_plural = 'Ознакомления с результатами'


class LoginBudget(models.Model):
    """Shared login attempt windows. Keys are HMACs, never raw IPs/usernames."""
    key = models.CharField(max_length=64, primary_key=True)
    scope = models.CharField(max_length=12)
    attempts = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        default_permissions = ()
