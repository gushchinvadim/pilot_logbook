# management/commands/load_sessions.py
import pandas as pd
from django.core.management.base import BaseCommand
from pilot_training.models import Session, Exercise, AssignmentExercise, Competency  # ← добавлен Competency


def clean_excel_number(value):
    if pd.isna(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


class Command(BaseCommand):
    help = 'Загружает сессии, упражнения и компетенции из Excel-файла'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к Excel-файлу')

    def handle(self, *args, **options):
        file_path = options['file_path']

        try:
            df = pd.read_excel(file_path, sheet_name='Лист1', engine='openpyxl')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка чтения файла: {e}'))
            return

        # Очищаем названия колонок
        df.columns = df.columns.str.strip().str.upper()

        required_cols = {
            'SESSION_TITLE',
            'SESSION_DESC',
            'EXERCISE_NAME',
            'PHASE_OF_FLIGHT',
            'EXERCISE_TYPE',
            'DURATION',
            'ORDER',
            'SKILLTEST_POSITION',
            'PROGRESS_SHEET_NUMBER',
        }
        if not required_cols.issubset(df.columns):
            missing = required_cols - set(df.columns)
            self.stdout.write(self.style.ERROR(f'Не хватает колонок: {missing}'))
            return

        # 🔽 Ключевая часть: обрезаем "мусорные" строки
        last_valid_idx = df['EXERCISE_NAME'].dropna().last_valid_index()
        if last_valid_idx is None:
            self.stdout.write(self.style.ERROR('Файл не содержит ни одного упражнения (EXERCISE_NAME пуст везде)'))
            return

        df = df.loc[:last_valid_idx].copy()
        df.columns = df.columns.str.strip().str.upper()

        # Заполняем SESSION_TITLE и SESSION_DESC вниз
        df['SESSION_TITLE'] = df['SESSION_TITLE'].ffill()
        df['SESSION_DESC'] = df['SESSION_DESC'].ffill()

        # 🔑 Создаём/получаем все компетенции один раз
        competency_codes = ['PRO', 'COM', 'FPA', 'FPM', 'LTW', 'PSD', 'SAW', 'WLM']
        competency_map = {}

        for code in competency_codes:
            # Находим полное название из модели
            full_code = code.lower()
            name = dict(Competency.CODE_CHOICES).get(full_code, f'{code} — неизвестно')

            competency, created = Competency.objects.get_or_create(
                code=full_code,
                defaults={'name': name}
            )
            competency_map[code] = competency
            if created:
                self.stdout.write(self.style.SUCCESS(f'Создана компетенция: {competency}'))

        created_sessions = 0
        created_exercises = 0
        updated_competencies = 0

        for idx, row in df.iterrows():
            # Пропускаем строки без имени упражнения
            if pd.isna(row['EXERCISE_NAME']):
                self.stdout.write(self.style.WARNING(f"Пропущено: пустое имя упражнения в строке {idx + 2}"))
                continue

            # --- 1. Сессия ---
            session_title = str(row['SESSION_TITLE']).strip() if pd.notna(row['SESSION_TITLE']) else ''
            session_desc = str(row['SESSION_DESC']).strip() if pd.notna(row['SESSION_DESC']) else ''

            if not session_title:
                self.stdout.write(self.style.WARNING(f"Пропущено: пустой SESSION_TITLE в строке {idx + 2}"))
                continue

            session, created_s = Session.objects.get_or_create(
                title=session_title,
                defaults={'description': session_desc}
            )
            if created_s:
                created_sessions += 1

            # --- 2. Упражнение ---
            name = str(row['EXERCISE_NAME']).strip() if pd.notna(row['EXERCISE_NAME']) else ''
            phase = str(row['PHASE_OF_FLIGHT']).strip() if pd.notna(row['PHASE_OF_FLIGHT']) else ''
            ex_type = str(row['EXERCISE_TYPE']).strip() if pd.notna(row['EXERCISE_TYPE']) else ''
            desc = str(row.get('DESCRIPTION') or '').strip() if pd.notna(row.get('DESCRIPTION')) else ''

            # Проверка обязательных полей
            if not name:
                self.stdout.write(self.style.WARNING(f"Пропущено: пустое имя упражнения в строке {idx + 2}"))
                continue
            if not phase:
                self.stdout.write(self.style.WARNING(f"Пропущено: пустая фаза полёта для упражнения '{name}'"))
                continue
            if not ex_type:
                self.stdout.write(self.style.WARNING(f"Пропущено: пустой тип упражнения '{name}'"))
                continue

            exercise, created_e = Exercise.objects.update_or_create(
                name=name,
                phase_of_flight=phase,
                description=desc,
                defaults={
                    'exercise_type': ex_type,
                    'duration_minutes': int(row['DURATION']) if pd.notna(row['DURATION']) else None,
                    'min_score': int(row['MIN_SCORE']) if pd.notna(row['MIN_SCORE']) else 3,
                    'progress_sheet_number': clean_excel_number(row['PROGRESS_SHEET_NUMBER']),
                    'skilltest_position': clean_excel_number(row['SKILLTEST_POSITION']),
                }
            )
            if created_e:
                created_exercises += 1

            # 🔑 --- 3. Компетенции ---
            # Очищаем старые компетенции перед установкой новых (важно для повторной загрузки!)
            exercise.competencies.clear()

            added_competencies = []
            for code in competency_codes:
                if code in row and pd.notna(row[code]) and row[code] == 1:
                    exercise.competencies.add(competency_map[code])
                    added_competencies.append(code)

            if added_competencies:
                updated_competencies += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Упражнение '{name}' → компетенции: {', '.join(added_competencies)}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  Упражнение '{name}' → компетенции не назначены"
                    )
                )

            # --- 4. Связь сессия-упражнение ---
            order = int(row['ORDER']) if pd.notna(row['ORDER']) else 999
            AssignmentExercise.objects.update_or_create(
                session=session,
                exercise=exercise,
                defaults={'order': order}
            )

        self.stdout.write(
            self.style.SUCCESS(
                f'✅ Загружено: {created_sessions} сессий, {created_exercises} упражнений, '
                f'обновлено компетенций для {updated_competencies} упражнений'
            )
        )