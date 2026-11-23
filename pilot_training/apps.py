from django.apps import AppConfig


class PilotTrainingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'pilot_training'

    def ready(self):
        from . import signals  # noqa: F401
