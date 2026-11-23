from datetime import timedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from rest_framework.test import APIClient
from django.utils import timezone
from .models import (Pilot, Instructor, Session, Exercise, AssignmentExercise, TrainingSession,
                     RatingSession, ATCDScheduleLink)
from .crew import pair_assignments
from . import tests_atcd as fixtures


class ManualExtraTests(TestCase):
    def setUp(self):
        User=get_user_model()
        self.manager=User.objects.create_superuser('extra-manager','extra@example.test','test')
        self.teacher=User.objects.create_user('extra-instructor')
        self.instructor=Instructor.objects.create(user=self.teacher,name='Extra instructor',license='EXT-I')
        self.pilots=[Pilot.objects.create(user=User.objects.create_user('extra-pilot-'+str(i)),name='Pilot '+str(i),license='EXT-P'+str(i)) for i in (1,2,3)]
        self.template=Session.objects.create(title='EXTRA — asymmetric approach')
        self.exercise=Exercise.objects.create(name='Extra exercise',exercise_type='SIM')
        self.assignment=AssignmentExercise.objects.create(session=self.template,exercise=self.exercise,order=1)
        self.start=(timezone.now()+timedelta(days=30)).replace(hour=9,minute=0,second=0,microsecond=0)
        self.client=APIClient()

    def extra(self,pilot=None,**kwargs):
        data=dict(pilot=pilot or self.pilots[0],instructor=self.instructor,session=self.template,
                  is_extra=True,extra_reason='Additional practice',planned_at=self.start,
                  ends_at=self.start+timedelta(hours=4),schedule_timezone='Europe/Moscow',venue='FFS')
        data.update(kwargs)
        row=TrainingSession(**data);row.full_clean();row.save();return row

    def test_extra_is_visible_only_to_its_pilot_and_instructor(self):
        row=self.extra()
        for user in (self.pilots[0].user,self.teacher):
            self.client.force_authenticate(user)
            data=self.client.get('/api/my-training-sessions/').data
            self.assertEqual([r['id'] for r in data],[row.pk]);self.assertTrue(data[0]['is_extra'])
            detail=self.client.get(f'/api/training-sessions/{row.pk}/').data
            self.assertTrue(detail['is_extra']);self.assertEqual(detail['extra_reason'],'Additional practice')
        self.client.force_authenticate(self.pilots[1].user)
        self.assertEqual(self.client.get('/api/my-training-sessions/').data,[])
        self.assertEqual(self.client.get(f'/api/training-sessions/{row.pk}/').status_code,404)

    def test_two_pilots_can_be_paired_and_keep_separate_results(self):
        first=self.extra();second=self.extra(self.pilots[1]);crew=pair_assignments([first.pk,second.pk],instructor=self.instructor)
        self.assertEqual(crew.participants.count(),2)
        self.client.force_authenticate(self.teacher)
        data=self.client.get('/api/crew-sessions/').data['sessions'][0]
        self.assertTrue(data['is_extra']);self.assertEqual(len(data['participants']),2)
        self.assertEqual(RatingSession.objects.count(),0)

    def test_third_pilot_at_the_same_time_is_rejected(self):
        self.extra();self.extra(self.pilots[1])
        with self.assertRaises(ValidationError):self.extra(self.pilots[2])

    def test_overlap_checks_whole_session_not_only_start(self):
        other=Session.objects.create(title='Programme training')
        TrainingSession.objects.create(session=other,pilot=self.pilots[1],instructor=self.instructor,
            planned_at=self.start,ends_at=self.start+timedelta(hours=4))
        with self.assertRaises(ValidationError):self.extra(planned_at=self.start+timedelta(hours=2),ends_at=self.start+timedelta(hours=6))

    def test_extra_requires_times_exercises_and_separate_template(self):
        for changes in ({'planned_at':None},{'ends_at':None},{'ends_at':self.start}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):self.extra(**changes)
        empty=Session.objects.create(title='Empty EXTRA')
        with self.assertRaises(ValidationError):self.extra(session=empty)
        TrainingSession.objects.create(session=self.template,pilot=self.pilots[0],instructor=self.instructor,status='completed')
        with self.assertRaises(ValidationError):self.extra()

    def test_extra_can_be_graded_independently_of_main_programme(self):
        main=Session.objects.create(title='Main training')
        RatingSession.objects.create(pilot=self.pilots[0],instructor=self.instructor,session=main)
        row=self.extra();self.client.force_authenticate(self.teacher)
        response=self.client.post('/api/rating-sessions/',{'pilot_id':row.pilot_id,'session_id':row.pk,
            'general_notes':'Extra completed','exercises':[{'assignment_id':self.assignment.pk,'score':4}]},format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(RatingSession.objects.count(),2)
        row.refresh_from_db();self.assertTrue(row.is_extra);self.assertEqual(row.status,'completed')
        self.assertTrue(RatingSession.objects.get(training_session=row).revisions.exists())

    def test_admin_extra_shortcut_prefills_flag_and_normal_add_is_unchanged(self):
        self.client.force_login(self.manager)
        response=self.client.get('/admin/pilot_training/trainingsession/')
        self.assertContains(response,'Добавить EXTRA-сессию')
        response=self.client.get('/admin/pilot_training/trainingsession/add/?is_extra=1')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['adminform'].form.initial['is_extra'])
        response=self.client.get('/admin/pilot_training/trainingsession/add/')
        self.assertFalse(response.context['adminform'].form.initial.get('is_extra',False))

    def test_admin_can_save_a_manual_extra_assignment(self):
        from zoneinfo import ZoneInfo
        start=timezone.localtime(self.start,ZoneInfo('Europe/Moscow'))
        end=start+timedelta(hours=4)
        self.client.force_login(self.manager)
        response=self.client.post('/admin/pilot_training/trainingsession/add/',{
            'session':self.template.pk,'pilot':self.pilots[0].pk,'instructor':self.instructor.pk,
            'venue':'FFS','is_extra':'on','extra_reason':'Additional practice','status':'planned',
            'schedule_timezone':'Europe/Moscow','planned_at_0':start.date().isoformat(),
            'planned_at_1':start.strftime('%H:%M:%S'),'ends_at_0':end.date().isoformat(),
            'ends_at_1':end.strftime('%H:%M:%S'),'_save':'Save'})
        self.assertEqual(response.status_code,302)
        row=TrainingSession.objects.get()
        self.assertTrue(row.is_extra);self.assertEqual(row.planned_at,self.start)
        self.assertFalse(ATCDScheduleLink.objects.exists())

    def test_mixed_extra_and_programme_assignments_cannot_be_paired(self):
        first=self.extra()
        second=TrainingSession.objects.create(session=self.template,pilot=self.pilots[1],instructor=self.instructor,planned_at=self.start)
        from rest_framework.exceptions import ValidationError as APIValidationError
        with self.assertRaises(APIValidationError):pair_assignments([first.pk,second.pk])


class ExtraATCDIsolationTests(TestCase):
    setUp=fixtures.ATCDImportTests.setUp
    preview=fixtures.ATCDImportTests.preview
    apply=fixtures.ATCDImportTests.apply

    def test_refresh_from_atcd_never_updates_manual_extra(self):
        self.apply()
        template=Session.objects.create(title='Local EXTRA')
        exercise=Exercise.objects.create(name='Local extra exercise',exercise_type='SIM')
        AssignmentExercise.objects.create(session=template,exercise=exercise)
        extra=TrainingSession(pilot=self.pilots[0],instructor=self.instructor,session=template,
            is_extra=True,extra_reason='Local reason',planned_at=timezone.now()+timedelta(days=20),
            ends_at=timezone.now()+timedelta(days=20,hours=4),schedule_timezone='Asia/Krasnoyarsk',venue='Local FFS')
        extra.full_clean();extra.save();old_start=extra.planned_at
        self.row['venue']='Updated ATCD venue'
        self.assertEqual(self.apply().data['applied'],1)
        extra.refresh_from_db()
        self.assertTrue(extra.is_extra);self.assertEqual(extra.extra_reason,'Local reason')
        self.assertEqual(extra.planned_at,old_start);self.assertEqual(extra.venue,'Local FFS')
        self.assertIsNone(extra.crew_session_id);self.assertEqual(ATCDScheduleLink.objects.count(),1)

    def test_atcd_assignment_cannot_be_relabelled_as_extra(self):
        self.apply()
        row=TrainingSession.objects.first();row.is_extra=True
        with self.assertRaises(ValidationError):row.full_clean()
