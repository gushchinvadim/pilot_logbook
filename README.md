# Платформа для пилотов с элементами оценки компетенций, прогресса и анализа результатов.

1.	Основные сущности (модели)

Pilot - Пользователь-пилот
Instructor - Инструктор, который оценивает
Exercise - Упражнение (например, "Посадка в тумане", "Выход из штопора")
TrainingSession - Задание на тренировку (набор упражнений для пилота)
TrainingTask - Конкретное упражнение в рамках сессии
Rating - Оценка за выполнение упражнения
Skill - Навык (например, "управление на посадке", "навигация") — для анализа сильных/слабых сторон

2.	Модели Django (пример)
### models.py
from django.contrib.auth.models import User
from django.db import models

class Skill(models.Model):
    name = models.CharField("Название навыка", max_length=100, unique=True)
    description = models.TextField("Описание", blank=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Навык"
        verbose_name_plural = "Навыки"


class Exercise(models.Model):
    name = models.CharField("Название упражнения", max_length=200)
    description = models.TextField("Описание", blank=True)
    duration_minutes = models.PositiveIntegerField("Длительность (мин)", null=True, blank=True)
    skills = models.ManyToManyField(Skill, verbose_name="Ключевые навыки")
    max_score = models.PositiveSmallIntegerField("Макс. балл", default=0)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Упражнение"
        verbose_name_plural = "Упражнения"


class TrainingSession(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Ожидает'),
        ('in_progress', 'В процессе'),
        ('completed', 'Завершена'),
    ]

    pilot = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'groups__name': 'Pilots'}, related_name='training_sessions')
    instructor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, limit_choices_to={'groups__name': 'Instructors'}, related_name='sessions_as_instructor')
    title = models.CharField("Название сессии", max_length=200)
    deadline = models.DateTimeField("Срок выполнения")
    status = models.CharField("Статус", max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} — {self.pilot.get_full_name() or self.pilot.username}"

    class Meta:
        verbose_name = "Тренировочная сессия"
        verbose_name_plural = "Тренировочные сессии"


class TrainingTask(models.Model):
    session = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name='tasks')
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField("Порядок", default=1)

    class Meta:
        ordering = ['order']
        unique_together = ['session', 'exercise']
        verbose_name = "Задача в сессии"
        verbose_name_plural = "Задачи в сессии"

    def __str__(self):
        return f"{self.session} — {self.exercise}"


class Rating(models.Model):
    task = models.OneToOneField(TrainingTask, on_delete=models.CASCADE, related_name='rating')
    score = models.PositiveSmallIntegerField("Оценка")
    feedback = models.TextField("Комментарий", blank=True)
    evaluated_at = models.DateTimeField(auto_now=True)
    instructor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='ratings_given')

    def __str__(self):
        return f"Оценка: {self.score} за {self.task.exercise}"

    class Meta:
        verbose_name = "Оценка"
        verbose_name_plural = "Оценки"

3.	Пользователи и группы
•	Pilots, 
•	 Instructors,
•	Admins

4. Анализ сильных и слабых сторон

После выполнения сессий можно строить отчёты:
Пример: средний балл по навыкам
from django.db.models import Avg

### Получить средний балл пилота по каждому навыку
pilot = User.objects.get(username='ivan_pilot')
ratings = Rating.objects.filter(task__session__pilot=pilot).values(
    'task__exercise__skills__name'
).annotate(avg_score=Avg('score')).order_by('-avg_score')

for item in ratings:
    print(f"{item['task__exercise__skills__name']}: {item['avg_score']:.2f}")

→ Это даст вам рейтинг по навыкам: где пилот силён, а где — требует доработки.

5. Интерфейсы (views и шаблоны)
/dashboard/ - Личный кабинет пилота: текущие сессии, дедлайны, прогресс
/session/123/ - Детали сессии: список упражнений, статус выполнения
/instructor/sessions/ - Инструктор видит сессии, где он — оценщик
/instructor/evaluate/456/ - Форма для выставления оценки
/report/pilot/789/ - Отчёт по пилоту: график по навыкам, динамика оценок

6. Полезные возможности
Автоматическое создание сессий - Скрипт или Celery-задача
Напоминания о дедлайне - django-celery-beat+send_mail
Прогресс-бар - {{ session.tasks.completed.count }} / {{ session.tasks.count }}
Экспорт отчёта в PDF – weasyprintилиReportLab
История оценок - График с помощью Chart.js

7. Расширения (опционально)
•	Django REST Framework — если мобильное приложение
•	Channels — для уведомлений в реальном времени
•	Django-Q или Celery — фоновые задачи
•	Django Admin + django-import-export — загрузка упражнений из Excel

7. Расширения (опционально)
•	Django REST Framework — если мобильное приложение
•	Channels — для уведомлений в реальном времени
•	Django-Q или Celery — фоновые задачи
•	Django Admin + django-import-export — загрузка упражнений из Excel

# pilot_logbook


## Приложение для iPad

Первый этап рабочего места инструктора: [инструкция и проект Xcode](ipad/README.md). Код приложения расположен в `ipad/`; сервер и React остаются отдельными частями проекта.
