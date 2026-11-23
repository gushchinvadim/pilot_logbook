from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from pilot_training.models import LoginBudget


class Command(BaseCommand):
    help = 'Remove login limit windows that expired more than a day ago; no user data or results are modified.'

    def handle(self, *args, **options):
        count, _ = LoginBudget.objects.filter(expires_at__lt=timezone.now() - timedelta(days=1)).delete()
        self.stdout.write(f'Expired login windows removed: {count}')
