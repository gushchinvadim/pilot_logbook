"""Run with `python manage.py shell < deploy/inventory.py`; outputs counts only, no personal data."""
import json
from django.apps import apps
from django.db.migrations.recorder import MigrationRecorder

result = {model._meta.label: model._default_manager.count()
    for model in apps.get_models() if model._meta.app_label in ('pilot_training', 'auth', 'authtoken')}
print(json.dumps({'record_counts': result, 'migrations': sorted(
    f'{app}.{name}' for app, name in MigrationRecorder.Migration.objects.values_list('app', 'name'))}, ensure_ascii=False, indent=2))
