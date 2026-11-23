from django.db import migrations, models


def check_existing_links(apps, schema_editor):
    Rating = apps.get_model('pilot_training', 'RatingSession')
    duplicates = (Rating.objects.using(schema_editor.connection.alias)
        .exclude(training_session_id=None).values('training_session_id')
        .annotate(total=models.Count('pk')).filter(total__gt=1))
    if duplicates.exists():
        raise RuntimeError('Multiple results reference one training assignment. Review these links before migrating; no results were changed.')


class Migration(migrations.Migration):
    dependencies = [('pilot_training', '0011_manual_extra_sessions')]
    operations = [
        migrations.RunPython(check_existing_links, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='ratingsession',
            constraint=models.UniqueConstraint(fields=('training_session',), name='unique_rating_per_training')),
        migrations.AlterUniqueTogether(name='ratingsession', unique_together=set()),
    ]
