# your_app/management/commands/load_pilots.py
import pandas as pd
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from pilot_training.models import Pilot  # ← замените your_app на имя вашего приложения

def to_bool(val):
    if pd.isna(val):
        return False
    if isinstance(val, bool):
        return val
    v = str(val).lower().strip()
    return v in ('1', 'true', 'да', 'yes', 'y')

class Command(BaseCommand):
    help = 'Загружает пилотов из Excel-файла (лист "Лист1")'

    def add_arguments(self, parser):
        parser.add_argument('file_path', type=str, help='Путь к Excel-файлу (.xlsx)')

    def handle(self, *args, **options):
        file_path = options['file_path']
        try:
            df = pd.read_excel(file_path, sheet_name='Лист1', engine='openpyxl')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Ошибка чтения файла: {e}'))
            return

        # Нормализуем колонки
        df.columns = df.columns.str.strip().str.lower()

        # 🔥 Обязательные поля: username, name, license, date_of_birth
        required_cols = {'username', 'name', 'license', 'date_of_birth'}
        missing = required_cols - set(df.columns)
        if missing:
            self.stdout.write(self.style.ERROR(f'Не хватает обязательных колонок: {missing}'))
            return

        # Обрезаем "мусор" — оставляем строки до последнего непустого license
        last_valid_idx = df['license'].dropna().last_valid_index()
        if last_valid_idx is None:
            self.stdout.write(self.style.ERROR('Ни одна строка не содержит license — файл пуст?'))
            return
        df = df.loc[:last_valid_idx].copy()

        created_count = 0
        updated_count = 0

        for idx, row in df.iterrows():
            line_num = idx + 2  # Excel: 1 — заголовок, 2 — первая строка данных

            # Обязательные поля
            username = str(row['username']).strip()
            name = str(row.get('name', '')).strip()
            license_num = str(row['license']).strip()

            # Проверка даты рождения
            dob = None
            if pd.notna(row.get('date_of_birth')):
                try:
                    dob = pd.to_datetime(row['date_of_birth']).date()
                except Exception:
                    self.stdout.write(self.style.WARNING(f'Неверный формат даты в строке {line_num}'))
                    continue  # Пропускаем строку без валидной даты
            else:
                self.stdout.write(self.style.WARNING(f'Пропущена строка {line_num}: отсутствует date_of_birth'))
                continue

            # Получаем или создаём пользователя
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={'email': f"{username}@test.ru"}
            )

            # Опциональные поля
            experience = int(row.get('experience', 0)) if pd.notna(row.get('experience')) else 0
            graduated_at = str(row.get('graduated_at', 'Unknown')).strip() or 'Unknown'
            glass_cockpit = to_bool(row.get('glass_cockpit'))
            is_captain = to_bool(row.get('is_captain'))
            contract = row.get('contract') or None
            is_active = to_bool(row.get('is_active', True))

            # Создаём или обновляем пилота
            pilot, created = Pilot.objects.update_or_create(
                license=license_num,
                defaults={
                    'user': user,
                    'name': name,
                    'date_of_birth': dob,
                    'graduated_at': graduated_at,
                    'experience': experience,
                    'glass_cockpit': glass_cockpit,
                    'is_captain': is_captain,
                    'contract': contract,
                    'is_active': is_active,
                }
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'✅ Загружено: {created_count} новых, {updated_count} обновлено пилотов'
            )
        )