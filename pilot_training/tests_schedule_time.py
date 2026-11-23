from datetime import datetime, timedelta, timezone as utc
from zoneinfo import ZoneInfo
from django.contrib import admin
from django.test import TestCase
from . import tests_atcd as fixtures
from .admin import TrainingSessionForm
from .models import TrainingSession
from .schedule_time import ScheduleDateTimeField


class ScheduleTimeTests(TestCase):
    def setUp(self):
        fixtures.ATCDImportTests.setUp(self)
        self.row.update(starts_at='2027-02-17T05:00:00+00:00', ends_at='2027-02-17T11:00:00+00:00', timezone='Europe/Ulyanovsk')
        self.assertEqual(self.apply().status_code,200)
        self.assignment=TrainingSession.objects.order_by('pk').first()

    preview=fixtures.ATCDImportTests.preview
    apply=fixtures.ATCDImportTests.apply

    def test_confirmed_time_update_keeps_assignment_ids_and_changes_saved_calendar(self):
        ids=list(TrainingSession.objects.values_list('pk',flat=True))
        self.row.update(starts_at='2027-02-16T22:00:00+00:00',ends_at='2027-02-17T04:00:00+00:00')
        preview=self.preview()
        self.assertEqual(preview['rows'][0]['action'],'update')
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.planned_at.hour,5)  # Preview never writes.
        self.assertEqual(self.apply(preview).data['applied'],1)
        self.assertEqual(list(TrainingSession.objects.values_list('pk',flat=True)),ids)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.planned_at,datetime(2027,2,16,22,tzinfo=utc.utc))
        self.client.force_authenticate(self.instructor.user)
        result=self.client.get('/api/my-training-sessions/').data
        self.assertEqual(result[0]['planned_at'],self.assignment.planned_at)
        self.assertEqual(result[0]['schedule_timezone'],'Europe/Ulyanovsk')
        model_admin=admin.site._registry[TrainingSession]
        self.assertEqual(model_admin.planned_local(self.assignment),'17.02.2027 02:00 (UTC+04:00)')

    def test_list_and_object_label_use_device_timezone(self):
        model_admin=admin.site._registry[TrainingSession]
        self.assertEqual(model_admin.planned_local(self.assignment),'17.02.2027 09:00 (UTC+04:00)')
        self.assertEqual(model_admin.ends_local(self.assignment),'17.02.2027 15:00 (UTC+04:00)')
        self.assertIn('17.02.2027 09:00 Europe/Ulyanovsk',str(self.assignment))
        form=TrainingSessionForm(instance=self.assignment)
        parts=form.fields['planned_at'].widget.decompress(self.assignment.planned_at)
        self.assertEqual(parts[1].hour,9)
        self.assertIn('Europe/Ulyanovsk',form.fields['planned_at'].label)

    def form_data(self):
        a=self.assignment
        return {'session':a.session_id,'pilot':a.pilot_id,'instructor':a.instructor_id,'venue':a.venue,'status':'planned',
                'schedule_timezone':'Europe/Ulyanovsk','planned_at_0':'2027-02-17','planned_at_1':'09:00:00',
                'ends_at_0':'2027-02-17','ends_at_1':'15:00:00'}

    def test_admin_form_roundtrip_does_not_shift_instant(self):
        form=TrainingSessionForm(data=self.form_data(),instance=self.assignment)
        self.assertTrue(form.is_valid(),form.errors)
        saved=form.save()
        self.assertEqual(saved.planned_at,datetime(2027,2,17,5,tzinfo=utc.utc))
        self.assertEqual(saved.ends_at,datetime(2027,2,17,11,tzinfo=utc.utc))

    def test_admin_form_edits_wall_time_in_selected_zone(self):
        data=self.form_data();data['planned_at_1']='06:00:00'
        form=TrainingSessionForm(data=data,instance=self.assignment)
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.cleaned_data['planned_at'],datetime(2027,2,17,2,tzinfo=utc.utc))

    def test_admin_form_rejects_invalid_zone_and_dst_ambiguity(self):
        data=self.form_data();data['schedule_timezone']='Invalid/Zone'
        form=TrainingSessionForm(data=data,instance=self.assignment)
        self.assertFalse(form.is_valid());self.assertIn('schedule_timezone',form.errors)
        field=ScheduleDateTimeField(ZoneInfo('Europe/Berlin'))
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError): field.clean(['2027-03-28','02:30:00'])

    def test_admin_calendar_uses_device_date_and_real_end_time(self):
        self.assignment.planned_at=datetime(2027,2,16,22,tzinfo=utc.utc)
        self.assignment.ends_at=datetime(2027,2,17,4,tzinfo=utc.utc)
        self.assignment.save()
        self.client.force_login(self.user)
        result=self.client.get('/admin/pilot_training/trainingsession/api/calendar-events/')
        self.assertEqual(result.status_code,200)
        event=next(r for r in result.json() if r['id']==self.assignment.pk)
        self.assertEqual(event['start'],'2027-02-17T02:00:00')
        self.assertEqual(event['end'],'2027-02-17T08:00:00')
        self.assertEqual(event['extendedProps']['timezone'],'Europe/Ulyanovsk')

    def test_admin_pages_render_local_clock_and_timezone(self):
        self.client.force_login(self.user)
        result=self.client.get('/admin/pilot_training/trainingsession/')
        self.assertEqual(result.status_code,200)
        self.assertContains(result,'17.02.2027 09:00 (UTC+04:00)')
        result=self.client.get(f'/admin/pilot_training/trainingsession/{self.assignment.pk}/change/')
        self.assertEqual(result.status_code,200)
        self.assertContains(result,'value="09:00:00"')
        self.assertContains(result,'Europe/Ulyanovsk')
