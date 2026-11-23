from django.test import TestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from copy import deepcopy
from unittest.mock import patch
from . import tests_atcd as fixtures
from .models import ATCDPilotLink, ATCDImportLog, Pilot, TrainingSession


class ATCDPilotCreationTests(TestCase):
    """Source-bound account creation, validation and permissions."""
    def setUp(self):
        fixtures.ATCDImportTests.setUp(self)
        patch('pilot_training.atcd_people.fetch_schedule', side_effect=lambda *args: [deepcopy(self.row)]).start()

    preview = fixtures.ATCDImportTests.preview
    apply = fixtures.ATCDImportTests.apply

    def person_payload(self):
        return {'start':self.payload['start'],'end':self.payload['end'],'source_id':21,
                'username':'new_atcd_pilot','license':'NEW-SIM-LIC', 'password':'Synthetic-Strong-Pilot-9387'}

    def create(self, **changes):
        return self.client.post('/api/atcd/pilots/create/',{**self.person_payload(),**changes},format='json')

    def test_creates_pilot_and_independent_account_without_assignments(self):
        result=self.create()
        self.assertEqual(result.status_code,201,result.data)
        link=ATCDPilotLink.objects.select_related('pilot__user').get(source_id=21)
        pilot=link.pilot; user=pilot.user
        self.assertEqual(pilot.name,'Pilot1')
        self.assertTrue(user.check_password(self.person_payload()['password']))
        self.assertFalse(user.is_staff);self.assertFalse(user.is_superuser)
        self.assertFalse(user.user_permissions.exists());self.assertFalse(user.groups.exists())
        self.assertFalse(TrainingSession.objects.exists())
        self.assertEqual(result['Cache-Control'],'no-store')
        self.assertNotIn('password',str(result.data).lower())
        audit=ATCDImportLog.objects.get()
        self.assertEqual(audit.changes[0]['event'],'pilot_created')
        self.assertNotIn(self.person_payload()['password'],str(audit.changes))
        self.client.force_authenticate(user)
        me=self.client.get('/api/auth/me/')
        self.assertEqual(me.data['roles'],['student'])
        self.assertEqual(me.data['pilot_id'],pilot.pk)

    def test_created_pilot_is_available_for_mapping_and_import(self):
        result=self.create();pilot=result.data['pilot']
        self.payload['mappings']['pilots']['21']=pilot['id']
        self.assertEqual(self.apply().status_code,200)
        self.assertEqual(TrainingSession.objects.filter(pilot_id=pilot['id']).count(),1)
        options=self.client.get('/api/atcd/options/').data
        self.assertTrue(options['can_create_pilot'])
        self.assertEqual(options['mappings']['pilots']['21'],pilot['id'])

    def test_repeated_creation_does_not_rotate_password_or_create_duplicate(self):
        self.assertEqual(self.create().status_code,201)
        count=get_user_model().objects.count()
        result=self.create(password='Other-Strong-Password-8765')
        self.assertEqual(result.status_code,409)
        self.assertEqual(get_user_model().objects.count(),count)
        self.assertTrue(ATCDPilotLink.objects.get(source_id=21).pilot.user.check_password(self.person_payload()['password']))

    def test_source_identity_is_checked_and_full_name_not_taken_from_browser(self):
        count=get_user_model().objects.count()
        self.assertEqual(self.create(source_id=99999).status_code,409)
        self.assertEqual(get_user_model().objects.count(),count)
        result=self.create(name='Forged person',is_staff=True,is_superuser=True)
        self.assertEqual(result.status_code,201)
        user=ATCDPilotLink.objects.get(source_id=21).pilot.user
        self.assertFalse(user.is_superuser);self.assertFalse(user.is_staff)
        self.assertEqual(ATCDPilotLink.objects.get(source_id=21).pilot.name,'Pilot1')

    def test_license_and_username_collisions_do_not_create_partial_accounts(self):
        count=get_user_model().objects.count()
        self.assertEqual(self.create(license=self.pilots[0].license.lower()).status_code,400)
        self.assertEqual(self.create(username=self.instructor.user.username.upper()).status_code,400)
        self.assertEqual(get_user_model().objects.count(),count)
        self.assertFalse(ATCDPilotLink.objects.exists())

    def test_weak_password_is_rejected(self):
        count=get_user_model().objects.count()
        self.assertEqual(self.create(password='123').status_code,400)
        self.assertEqual(get_user_model().objects.count(),count)

    def test_instructor_and_sync_only_manager_cannot_create_accounts(self):
        self.client.force_authenticate(self.instructor.user)
        self.assertEqual(self.create().status_code,403)
        manager=get_user_model().objects.create_user('sync-only')
        manager.user_permissions.add(Permission.objects.get(codename='sync_atcd'))
        self.client.force_authenticate(manager)
        self.assertFalse(self.client.get('/api/atcd/options/').data['can_create_pilot'])
        self.assertEqual(self.create().status_code,403)
        manager.user_permissions.add(Permission.objects.get(codename='add_pilot'),Permission.objects.get(content_type__app_label='auth',codename='add_user'))
        # Permission caches are per User instance.
        self.client.force_authenticate(get_user_model().objects.get(pk=manager.pk))
        self.assertEqual(self.create().status_code,201)

    def test_long_source_name_is_preserved(self):
        name='VeryLongPilotName '*14
        self.row['pilots'][0]['name']=name.strip()
        self.assertEqual(self.create().status_code,201)
        self.assertEqual(ATCDPilotLink.objects.get(source_id=21).pilot.name,name.strip())
