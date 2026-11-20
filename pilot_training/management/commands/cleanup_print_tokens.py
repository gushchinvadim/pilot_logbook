# pilot_training/management/commands/cleanup_print_tokens.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import models
from pilot_training.models import PrintToken


class Command(BaseCommand):
    help = "Удаляет все PrintToken, которые просрочены или уже использованы."

    def handle(self, *args, **options):
        now = timezone.now()
        deleted_count, _ = PrintToken.objects.filter(
            models.Q(expires_at__lt=now) | models.Q(used=True)
        ).delete()

        self.stdout.write(
            self.style.SUCCESS(f"Успешно удалено {deleted_count} неактивных токенов.")
        )

