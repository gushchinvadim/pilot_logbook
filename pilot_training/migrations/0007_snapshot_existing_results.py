import hashlib
import json
from django.db import migrations
from django.utils import timezone


def snapshot_existing(apps, schema_editor):
    db = schema_editor.connection.alias
    Rating = apps.get_model('pilot_training', 'RatingSession')
    Revision = apps.get_model('pilot_training', 'ResultRevision')
    PrintToken = apps.get_model('pilot_training', 'PrintToken')
    for rating in Rating.objects.using(db).select_related('pilot', 'instructor', 'session').iterator():
        exercises=[]
        for item in rating.ratingexercise_set.using(db).select_related('assignment__exercise').order_by('assignment__order', 'pk'):
            ex=item.assignment.exercise
            row={key:getattr(item,key) for key in ['score','completed']+[f'{k}_{suffix}' for k in ('pro','com','fpa','fpm','ltw','psd','saw','wlm') for suffix in ('score','remarks')]}
            row.update(assignment_id=item.assignment_id, exercise_id=ex.pk, exercise_name=ex.name,
                phase_of_flight=ex.phase_of_flight, order=item.assignment.order,
                exercise_description=ex.description,duration_minutes=ex.duration_minutes,
                min_score=ex.min_score,progress_sheet_number=ex.progress_sheet_number,skilltest_position=ex.skilltest_position)
            exercises.append(row)
        snapshot={'pilot':{'id':rating.pilot_id,'name':rating.pilot.name,'user_id':rating.pilot.user_id},
            'instructor':{'id':rating.instructor_id,'name':rating.instructor.name},
            'session':{'id':rating.session_id,'title':rating.session.title,'description':rating.session.description},
            'training_id':rating.training_session_id,'created_at':rating.created_at.isoformat(),
            'general_notes':rating.general_notes,'exercises':exercises}
        checksum=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        revision,_=Revision.objects.using(db).get_or_create(rating_id=rating.pk,version=1,defaults={
            'snapshot':snapshot,'content_hash':checksum,'published_at':timezone.now(),
            'reason':'Первичная фиксация ранее сохранённого результата.'})
        PrintToken.objects.using(db).filter(rating_session_id=rating.pk,revision__isnull=True).update(revision_id=revision.pk)


class Migration(migrations.Migration):
    dependencies=[('pilot_training','0006_result_versions')]
    operations=[migrations.RunPython(snapshot_existing,migrations.RunPython.noop)]
