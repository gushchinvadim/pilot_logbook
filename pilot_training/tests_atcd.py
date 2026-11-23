from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from .models import Pilot, Instructor, Session, TrainingSession, RatingSession, ATCDScheduleLink, ATCDImportLog


class ATCDImportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('sync-manager', 'manager@example.test', 'test')
        self.client = APIClient(); self.client.force_authenticate(self.user)
        self.pilots = [Pilot.objects.create(user=get_user_model().objects.create_user('pilot'+str(n)), name='Pilot '+str(n), license='SIM'+str(n)) for n in (1,2)]
        self.instructor = Instructor.objects.create(user=get_user_model().objects.create_user('teacher'), name='Instructor', license='SIMI')
        self.session = Session.objects.create(title='FFS Session 1')
        start = (timezone.now()+timedelta(days=5)).replace(microsecond=0)
        self.row = {'id': 71, 'group_id': 9, 'group': 'TEST-9', 'module_id': 1, 'module': 'PPP11M1',
            'template_key': '1:2:3', 'title': 'FFS Session 1', 'starts_at': start.isoformat(), 'ends_at': (start+timedelta(hours=4)).isoformat(),
            'timezone': 'Asia/Krasnoyarsk', 'venue': 'FFS KJA', 'status': 'planned', 'errors': [],
            'instructor': {'id': 11, 'name': 'Instructor'}, 'pilots': [{'id': 21, 'name': 'Pilot1'}, {'id': 22, 'name': 'Pilot2'}]}
        self.payload = {'start': start.date().isoformat(), 'end': start.date().isoformat(), 'mappings': {
            'pilots': {'21': self.pilots[0].pk, '22': self.pilots[1].pk},
            'instructors': {'11': self.instructor.pk}, 'templates': {'1:2:3': self.session.pk}}}
        self.remote = patch('pilot_training.atcd_views.fetch_schedule', side_effect=lambda *args: [deepcopy(self.row)]).start()
        self.addCleanup(patch.stopall)

    def preview(self):
        result = self.client.post('/api/atcd/schedule/', self.payload, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        return result.data

    def apply(self, preview=None):
        preview = preview or self.preview()
        return self.client.post('/api/atcd/schedule/', {**self.payload, 'confirmation': preview['confirmation']}, format='json')

    def test_preview_does_not_write_and_import_is_idempotent(self):
        preview = self.preview(); self.assertTrue(preview['can_apply']); self.assertEqual(TrainingSession.objects.count(),0)
        result = self.apply(preview); self.assertEqual(result.status_code,200,result.data)
        self.assertEqual(TrainingSession.objects.count(),2); self.assertEqual(ATCDImportLog.objects.count(),1)
        self.assertEqual(TrainingSession.objects.first().schedule_timezone,'Asia/Krasnoyarsk')
        self.assertEqual(self.apply().data['applied'],0); self.assertEqual(ATCDImportLog.objects.count(),1)

    def test_previous_result_does_not_block_import_or_reschedule(self):
        RatingSession.objects.create(pilot=self.pilots[0], instructor=self.instructor, session=self.session)
        self.assertEqual(self.apply().status_code, 200)
        from django.utils.dateparse import parse_datetime
        self.row['starts_at'] = (parse_datetime(self.row['starts_at']) + timedelta(hours=1)).isoformat()
        self.row['ends_at'] = (parse_datetime(self.row['ends_at']) + timedelta(hours=1)).isoformat()
        preview = self.preview()
        self.assertTrue(preview['can_apply'], preview)
        self.assertEqual(self.apply(preview).status_code, 200)
        self.assertEqual(RatingSession.objects.count(), 1)

    def test_single_pilot_is_supported(self):
        self.row['pilots'] = self.row['pilots'][:1]
        self.assertEqual(self.apply().status_code,200); self.assertEqual(TrainingSession.objects.count(),1)

    def test_changed_source_requires_new_preview(self):
        preview = self.preview(); self.row['venue'] = 'Changed venue'
        self.assertEqual(self.apply(preview).status_code,409); self.assertFalse(TrainingSession.objects.exists())

    def test_missing_mapping_blocks_whole_import(self):
        self.payload['mappings']['pilots'] = {}
        p = self.preview(); self.assertFalse(p['can_apply']); self.assertEqual(self.apply(p).status_code,409)

    def test_future_reschedule_updates_existing_ids(self):
        self.apply(); ids = list(TrainingSession.objects.values_list('id',flat=True))
        self.row['venue'] = 'New FFS'
        self.assertEqual(self.apply().data['applied'],1)
        self.assertEqual(list(TrainingSession.objects.values_list('id',flat=True)),ids)
        self.assertTrue(all(r.venue == 'New FFS' for r in TrainingSession.objects.all()))

    def test_started_session_and_results_cannot_be_changed(self):
        self.apply(); row = TrainingSession.objects.first()
        row.planned_at = timezone.now()-timedelta(minutes=1); row.save()
        self.row['venue'] = 'Wrong FFS'
        self.assertFalse(self.preview()['can_apply']); self.assertEqual(self.apply().status_code,409)
        row.refresh_from_db(); self.assertEqual(row.venue,'FFS KJA')

    def test_result_prevents_future_changes(self):
        self.apply(); row = TrainingSession.objects.first()
        RatingSession.objects.create(training_session=row,pilot=row.pilot,session=row.session,instructor=row.instructor)
        self.row['venue'] = 'Wrong FFS'; self.assertEqual(self.apply().status_code,409)
        self.assertEqual(RatingSession.objects.count(),1)

    def test_cancellation_preserves_assignments_and_is_idempotent(self):
        self.apply(); self.row['status'] = 'cancelled'; self.assertEqual(self.apply().data['applied'],1)
        self.assertEqual(TrainingSession.objects.filter(status='cancelled').count(),2)
        self.assertEqual(self.apply().data['applied'],0)

    def test_absence_from_export_does_not_cancel(self):
        self.apply(); self.remote.side_effect = lambda *args: []
        self.assertEqual(self.apply().data['applied'],0)
        self.assertEqual(TrainingSession.objects.filter(status='planned').count(),2)

    def test_overlapping_manual_assignment_blocks_import(self):
        TrainingSession.objects.create(session=self.session, pilot=self.pilots[0], instructor=self.instructor,
            planned_at=self.row['starts_at'],ends_at=self.row['ends_at'])
        self.assertFalse(self.preview()['can_apply']); self.assertEqual(self.apply().status_code,409)

    def test_inactive_pilot_and_three_people_are_blocked(self):
        self.pilots[0].is_active=False; self.pilots[0].save()
        self.assertFalse(self.preview()['can_apply'])
        self.pilots[0].is_active=True; self.pilots[0].save()
        self.row['pilots'].append(self.row['pilots'][0]); self.assertFalse(self.preview()['can_apply'])

    def test_instructor_cannot_read_options_or_import(self):
        self.client.force_authenticate(self.instructor.user)
        self.assertEqual(self.client.get('/api/atcd/options/').status_code,403)
        self.assertEqual(self.client.post('/api/atcd/schedule/',self.payload,format='json').status_code,403)

    def test_confirmation_cannot_be_reused_by_other_user(self):
        preview=self.preview()
        other=get_user_model().objects.create_superuser('second-manager','second@example.test','test')
        self.client.force_authenticate(other)
        self.assertEqual(self.apply(preview).status_code,409)

    def test_period_limit_and_personal_calendar(self):
        self.payload['end'] = (timezone.now()+timedelta(days=150)).date().isoformat()
        self.assertEqual(self.client.post('/api/atcd/schedule/',self.payload,format='json').status_code,400)
        self.assertEqual(self.client.get('/api/my-training-sessions/').data,[])

    def test_update_cannot_move_a_future_session_into_the_past(self):
        self.apply()
        past = timezone.now()-timedelta(days=1)
        self.row['starts_at'] = past.isoformat()
        self.row['ends_at'] = (past+timedelta(hours=4)).isoformat()
        self.assertFalse(self.preview()['can_apply'])
        self.assertEqual(self.apply().status_code,409)

    def test_single_import_is_visible_as_one_participant_to_instructor(self):
        self.row['pilots'] = self.row['pilots'][:1]
        self.apply()
        self.client.force_authenticate(self.instructor.user)
        response=self.client.get('/api/crew-sessions/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.data['sessions'][0]['participants']),1)
        self.assertEqual(response.data['sessions'][0]['participants'][0]['schedule_timezone'],'Asia/Krasnoyarsk')
