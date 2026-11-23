from unittest.mock import patch
from django.test import TestCase
from django.contrib.auth.models import User, Permission
from django.urls import reverse
from rest_framework.test import APIClient
from .models import (Pilot, Instructor, Session, Exercise, AssignmentExercise,
                     TrainingSession, RatingSession, RatingExercise, PrintToken)


class AccessAndSubmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = User.objects.create_user('instructor')
        cls.instructor = Instructor.objects.create(user=cls.teacher, name='Instructor', license='I1')
        cls.student = User.objects.create_user('student')
        cls.other = User.objects.create_user('other')
        cls.pilot = Pilot.objects.create(user=cls.student, name='Student', license='P1')
        cls.other_pilot = Pilot.objects.create(user=cls.other, name='Other', license='P2')
        cls.template = Session.objects.create(title='FTD training')
        cls.future = Session.objects.create(title='Future training')
        cls.hidden = Session.objects.create(title='Unassigned training')
        cls.exercise = Exercise.objects.create(name='Exercise', exercise_type='TEST')
        cls.assignment = AssignmentExercise.objects.create(session=cls.template, exercise=cls.exercise, order=1)
        cls.second = AssignmentExercise.objects.create(session=cls.template, exercise=Exercise.objects.create(name='Second', exercise_type='TEST'), order=2)
        cls.foreign = AssignmentExercise.objects.create(session=cls.hidden, exercise=cls.exercise)
        cls.training = TrainingSession.objects.create(session=cls.template, pilot=cls.pilot, instructor=cls.instructor)
        TrainingSession.objects.create(session=cls.future, pilot=cls.pilot, instructor=cls.instructor)

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def payload(self, **updates):
        data = {'pilot_id': self.pilot.pk, 'session_id': self.training.pk,
                'general_notes': 'Final notes', 'exercises': [
                    {'assignment_id': self.assignment.pk, 'score': 4, 'pro_score': 3, 'pro_remarks': 'Remark'},
                    {'assignment_id': self.second.pk, 'score': 5}]}
        data.update(updates)
        return data

    def submit(self, data):
        return self.api(self.teacher).post('/api/rating-sessions/', data, format='json')

    def result(self):
        return RatingSession.objects.create(pilot=self.pilot, session=self.template,
            instructor=self.instructor, training_session=self.training, general_notes='Private')

    def assert_no_result(self):
        self.assertFalse(RatingSession.objects.exists())
        self.assertFalse(RatingExercise.objects.exists())
        self.training.refresh_from_db()
        self.assertEqual(self.training.status, 'planned')

    def test_anonymous_search_and_print_are_closed(self):
        self.assertIn(self.client.get('/pilot-search/?q=Student').status_code, (401, 403))
        rating = self.result()
        self.assertEqual(self.client.get(f'/print-rating-unsafe/{rating.pk}/').status_code, 302)
        self.assertFalse(PrintToken.objects.exists())

    def test_student_sees_only_own_results_and_details(self):
        self.result()
        self.assertEqual(self.api(self.student).get('/api/rating-sessions/by-pilot/', {'pilot_id': self.pilot.pk}).status_code, 200)
        self.assertEqual(self.api(self.other).get('/api/rating-sessions/by-pilot/', {'pilot_id': self.pilot.pk}).status_code, 404)
        self.assertEqual(self.api(self.other).get(f'/api/pilots/{self.pilot.pk}/').status_code, 404)

    def test_students_cannot_modify_reference_data(self):
        client = self.api(self.student)
        self.assertEqual(client.patch(f'/api/exercises/{self.exercise.pk}/', {'name': 'Changed'}).status_code, 403)
        self.assertEqual(client.delete(f'/api/sessions/{self.template.pk}/').status_code, 403)
        self.assertEqual(client.patch(f'/api/instructors/{self.instructor.pk}/', {'name': 'Changed'}).status_code, 403)
        self.exercise.refresh_from_db()
        self.assertEqual(self.exercise.name, 'Exercise')

    def test_explicit_reference_data_permissions_work(self):
        manager = User.objects.create_user('manager')
        manager.user_permissions.add(Permission.objects.get(codename='view_exercise'), Permission.objects.get(codename='change_exercise'))
        self.assertEqual(self.api(manager).patch(f'/api/exercises/{self.exercise.pk}/', {'name': 'Updated'}).status_code, 200)

    def test_future_assignments_and_exercises_visible_only_to_participants(self):
        for user in (self.student, self.teacher):
            client = self.api(user)
            sessions = client.get('/api/training-sessions/')
            self.assertEqual(sessions.status_code, 200)
            self.assertEqual(len(sessions.data), 2)
            self.assertEqual(client.get(f'/api/session/{self.template.pk}/exercises/').status_code, 200)
            self.assertEqual(client.get(f'/api/session/{self.hidden.pk}/exercises/').status_code, 404)
        self.assertEqual(self.api(self.other).get('/api/training-sessions/').data, [])

    def test_document_management_requires_staff(self):
        self.client.force_login(self.student)
        for url in ('/admin/manage-docs/', '/admin/upload-pdf/', '/admin/manage-uploads/'):
            self.assertEqual(self.client.get(url).status_code, 302)

    def test_analytics_and_print_check_ownership(self):
        rating = self.result()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get('/admin/analytics/', {'pilot_id': self.pilot.pk}).status_code, 404)
        self.assertEqual(self.client.get(f'/print-rating-unsafe/{rating.pk}/').status_code, 404)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(f'/print-rating-unsafe/{rating.pk}/').status_code, 200)

    def test_token_cannot_bypass_result_access_and_is_single_use(self):
        from django.utils import timezone
        from datetime import timedelta
        token = PrintToken.objects.create(rating_session=self.result(), expires_at=timezone.now()+timedelta(hours=1))
        url = reverse('pilot_training:print_rating_token', args=[token.token])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        token.refresh_from_db()
        self.assertFalse(token.used)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_valid_complete_result_is_published_once(self):
        data = self.payload()
        response = self.submit(data)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(RatingExercise.objects.count(), 2)
        self.assertEqual(RatingExercise.objects.get(assignment=self.assignment).pro_remarks, 'Remark')
        self.training.refresh_from_db()
        self.assertEqual(self.training.status, 'completed')
        self.assertEqual(self.submit(data).status_code, 400)
        self.assertEqual(RatingSession.objects.count(), 1)
        self.assertEqual(len(self.api(self.student).get('/api/rating-sessions/by-pilot/', {'pilot_id': self.pilot.pk}).data), 1)

    def test_other_student_and_other_instructor_cannot_submit(self):
        self.assertEqual(self.api(self.student).post('/api/rating-sessions/', self.payload(), format='json').status_code, 403)
        teacher = User.objects.create_user('unassigned-instructor')
        Instructor.objects.create(user=teacher, name='Other instructor', license='I2')
        self.assertEqual(self.api(teacher).post('/api/rating-sessions/', self.payload(), format='json').status_code, 404)
        self.assert_no_result()

    def test_wrong_pilot_is_rejected(self):
        self.assertEqual(self.submit(self.payload(pilot_id=self.other_pilot.pk)).status_code, 404)
        self.assert_no_result()

    def test_invalid_and_incomplete_exercises_never_write_partial_results(self):
        cases = [[], [{'assignment_id': self.assignment.pk, 'score': 4}],
                 [{'assignment_id': self.assignment.pk, 'score': 4}, {'assignment_id': 999999, 'score': 4}],
                 [{'assignment_id': self.assignment.pk, 'score': 4}, {'assignment_id': self.foreign.pk, 'score': 4}],
                 [{'assignment_id': self.assignment.pk, 'score': 4}, {'assignment_id': self.assignment.pk, 'score': 5}]]
        for exercises in cases:
            with self.subTest(exercises=exercises):
                self.assertEqual(self.submit(self.payload(exercises=exercises)).status_code, 400)
                self.assert_no_result()

    def test_score_ranges_validated(self):
        for field, value in [('score', 99), ('score', 1), ('pro_score', 99), ('com_score', -1)]:
            data = self.payload()
            data['exercises'][1][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(self.submit(data).status_code, 400)
                self.assert_no_result()

    def test_database_failure_rolls_back_entire_submission(self):
        original = RatingExercise.objects.create
        calls = 0
        def fail_second(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('Synthetic storage failure')
            return original(**kwargs)
        with patch.object(RatingExercise.objects, 'create', side_effect=fail_second):
            with self.assertRaises(RuntimeError):
                self.submit(self.payload())
        self.assert_no_result()

    def test_nullable_competencies_do_not_crash_average(self):
        self.assertEqual(RatingExercise(pro_score=None, com_score=4).overall_score(), 4)

    def test_inactive_token_is_rejected_for_legacy_partial(self):
        from rest_framework.authtoken.models import Token
        token = Token.objects.create(user=self.teacher)
        self.teacher.is_active = False
        self.teacher.save(update_fields=['is_active'])
        self.assertEqual(self.client.get('/pilot-partial/', HTTP_AUTHORIZATION=f'Token {token.key}').status_code, 401)


    def test_analytics_encodes_remarks_without_changing_stored_text(self):
        import json
        text = '</script><img src=x onerror=alert(1)>'
        RatingExercise.objects.create(rating_session=self.result(), assignment=self.assignment,
            score=4, pro_score=3, pro_remarks=text)
        self.client.force_login(self.student)
        response = self.client.get('/admin/analytics/', {'pilot_id': self.pilot.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(text, response.content.decode())
        remarks = json.loads(response.context['competency_remarks_json'])
        self.assertNotIn('<', remarks['PRO'][0]['remark'])
        self.assertIn('&lt;', remarks['PRO'][0]['remark'])
        self.assertEqual(RatingExercise.objects.get().pro_remarks, text)

    def test_instructor_reads_previous_instructors_results_for_assigned_pilot(self):
        other_teacher = User.objects.create_user('another-teacher')
        other_instructor = Instructor.objects.create(user=other_teacher, name='Other teacher', license='I3')
        RatingSession.objects.create(pilot=self.pilot, session=self.future, instructor=other_instructor,
                                    general_notes='Other instructor notes')
        self.result()
        response = self.api(self.teacher).get('/api/rating-sessions/by-pilot/', {'pilot_id': self.pilot.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 2)
        self.assertEqual({r['general_notes'] for r in response.data}, {'Private', 'Other instructor notes'})

    def test_scoped_exercise_reference_reads(self):
        hidden_exercise = Exercise.objects.create(name='Unassigned', exercise_type='TEST')
        AssignmentExercise.objects.create(session=self.hidden, exercise=hidden_exercise)
        client = self.api(self.student)
        self.assertEqual(client.get(f'/api/exercises/{self.exercise.pk}/').status_code, 200)
        self.assertEqual(client.get(f'/api/exercises/{hidden_exercise.pk}/').status_code, 404)

    def test_session_lookup_works_for_own_future_training_only(self):
        self.client.force_login(self.student)
        response = self.client.get('/api/sessions-for-pilot/', {'pilot_id': self.pilot.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 2)
        self.assertEqual(self.client.get('/api/sessions-for-pilot/', {'pilot_id': self.other_pilot.pk}).status_code, 404)


class CrewSessionTests(TestCase):
    setUpTestData = classmethod(AccessAndSubmissionTests.setUpTestData.__func__)
    api = AccessAndSubmissionTests.api
    payload = AccessAndSubmissionTests.payload
    submit = AccessAndSubmissionTests.submit
    result = AccessAndSubmissionTests.result
    def setUp(self):
        self.partner_training = TrainingSession.objects.create(
            session=self.template, pilot=self.other_pilot, instructor=self.instructor)

    def pair(self, ids=None, user=None):
        return self.api(user or self.teacher).post('/api/crew-sessions/',
            {'training_ids': ids or [self.training.pk, self.partner_training.pk]}, format='json')

    def test_pair_keeps_individual_records_and_existing_results(self):
        result = self.result()
        old_ids = list(TrainingSession.objects.order_by('id').values_list('id', flat=True))
        response = self.pair()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(old_ids, list(TrainingSession.objects.order_by('id').values_list('id', flat=True)))
        result.refresh_from_db()
        self.assertEqual(result.general_notes, 'Private')
        self.assertEqual(result.training_session_id, self.training.pk)
        self.training.refresh_from_db(); self.partner_training.refresh_from_db()
        self.assertEqual(self.training.crew_session_id, self.partner_training.crew_session_id)
        self.assertEqual(self.training.crew_session_id, response.data['crew_id'])

    def test_pair_requires_two_distinct_pilots_with_same_template_and_instructor(self):
        cases = [[self.training.pk], [self.training.pk, self.training.pk],
                 [self.training.pk, TrainingSession.objects.get(session=self.future).pk]]
        for ids in cases:
            with self.subTest(ids=ids):
                self.assertEqual(self.pair(ids).status_code, 400)
        self.assertIsNone(TrainingSession.objects.get(pk=self.training.pk).crew_session_id)

    def test_pair_rejects_other_instructors_records(self):
        user = User.objects.create_user('crew-other-instructor')
        other = Instructor.objects.create(user=user, name='Other', license='CREW-OTHER')
        self.partner_training.instructor = other
        self.partner_training.save()
        self.assertEqual(self.pair().status_code, 404)
        self.assertIsNone(TrainingSession.objects.get(pk=self.training.pk).crew_session_id)

    def test_duplicate_pair_does_not_create_another_group(self):
        from .models import CrewSession
        self.assertEqual(self.pair().status_code, 201)
        self.assertEqual(self.pair().status_code, 400)
        self.assertEqual(CrewSession.objects.count(), 1)

    def test_list_shows_two_tabs_to_assigned_instructor_only(self):
        self.pair()
        response = self.api(self.teacher).get('/api/crew-sessions/')
        crew = next(row for row in response.data['sessions'] if row['crew_id'])
        self.assertEqual(len(crew['participants']), 2)
        self.assertEqual({row['pilot']['id'] for row in crew['participants']}, {self.pilot.pk, self.other_pilot.pk})
        self.assertEqual(self.api(self.student).get('/api/crew-sessions/').status_code, 403)
        self.assertEqual(self.pair(user=self.student).status_code, 403)

    def test_publishing_one_pilot_does_not_complete_the_other(self):
        self.pair()
        first = self.submit(self.payload())
        self.assertEqual(first.status_code, 201, first.data)
        self.partner_training.refresh_from_db()
        self.assertEqual(self.partner_training.status, 'planned')
        self.assertFalse(RatingSession.objects.filter(pilot=self.other_pilot).exists())
        second = self.submit(self.payload(pilot_id=self.other_pilot.pk, session_id=self.partner_training.pk))
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(RatingSession.objects.count(), 2)
        own = self.api(self.student).get('/api/rating-sessions/by-pilot/', {'pilot_id': self.pilot.pk})
        self.assertEqual(len(own.data), 1)
        self.assertEqual(self.api(self.student).get('/api/rating-sessions/by-pilot/', {'pilot_id': self.other_pilot.pk}).status_code, 404)

    def test_cancelled_record_cannot_be_paired(self):
        self.partner_training.status = 'cancelled'
        self.partner_training.save()
        self.assertEqual(self.pair().status_code, 400)

    def test_instructor_sees_separate_published_snapshots(self):
        self.pair()
        self.assertEqual(self.submit(self.payload(general_notes='First pilot only')).status_code, 201)
        self.assertEqual(self.submit(self.payload(pilot_id=self.other_pilot.pk,
            session_id=self.partner_training.pk, general_notes='Second pilot only')).status_code, 201)
        data = self.api(self.teacher).get('/api/crew-sessions/').data
        crew = next(row for row in data['sessions'] if row['crew_id'])
        self.assertEqual({row['result']['general_notes'] for row in crew['participants']},
                         {'First pilot only', 'Second pilot only'})


    def test_group_member_cannot_silently_change_pilot_or_template(self):
        from django.core.exceptions import ValidationError
        self.pair()
        self.training.refresh_from_db()
        self.training.pilot = self.other_pilot
        with self.assertRaises(ValidationError):
            self.training.clean()
        self.training.pilot = self.pilot
        self.training.session = self.future
        with self.assertRaises(ValidationError):
            self.training.clean()


class PortalReadTests(TestCase):
    setUpTestData = classmethod(AccessAndSubmissionTests.setUpTestData.__func__)
    api = AccessAndSubmissionTests.api
    result = AccessAndSubmissionTests.result

    def test_identity_supports_instructor_and_student(self):
        response = self.api(self.teacher).get('/api/auth/me/')
        self.assertEqual(response.data['roles'], ['instructor'])
        self.assertEqual(response.data['instructor_id'], self.instructor.pk)
        response = self.api(self.student).get('/api/auth/me/')
        self.assertEqual(response.data['roles'], ['student'])
        self.assertEqual(response.data['pilot_id'], self.pilot.pk)

    def test_personal_calendar_never_expands_for_superuser(self):
        manager = User.objects.create_superuser('calendar-admin', password='synthetic')
        self.assertEqual(self.api(manager).get('/api/my-training-sessions/').data, [])
        self.assertEqual(len(self.api(self.teacher).get('/api/my-training-sessions/').data), 2)
        self.assertEqual(len(self.api(self.student).get('/api/my-training-sessions/').data), 2)
        self.assertEqual(self.api(self.other).get('/api/my-training-sessions/').data, [])

    def test_future_assignment_detail_has_no_published_result(self):
        response = self.api(self.student).get(f'/api/training-sessions/{self.training.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['exercises']), 2)
        self.assertIsNone(response.data['result'])
        self.assertEqual(self.api(self.other).get(f'/api/training-sessions/{self.training.pk}/').status_code, 404)

    def test_previous_instructor_notes_are_visible_only_for_assigned_pilots(self):
        previous_user = User.objects.create_user('previous-teacher')
        previous = Instructor.objects.create(user=previous_user, name='Previous instructor', license='HISTORY')
        result = RatingSession.objects.create(pilot=self.pilot, session=self.template, instructor=previous,
            general_notes='Check prior difficulty')
        RatingExercise.objects.create(rating_session=result, assignment=self.assignment, score=3,
            pro_score=2, pro_remarks='Repeat the checklist')
        response = self.api(self.teacher).get('/api/results/', {'pilot_id': self.pilot.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]['instructor']['name'], 'Previous instructor')
        self.assertEqual(response.data[0]['exercises'][0]['pro_remarks'], 'Repeat the checklist')
        self.assertEqual(self.api(self.other).get('/api/results/', {'pilot_id': self.pilot.pk}).status_code, 404)
        self.assertEqual(self.api(self.other).get('/api/results/').data, [])
        self.assertEqual(self.api(self.teacher).patch('/api/results/', {}).status_code, 405)

    def test_result_print_api_checks_access_with_token(self):
        rating=self.result()
        response=self.api(self.student).get(f'/api/results/{rating.pk}/print/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
        self.assertEqual(self.api(self.other).get(f'/api/results/{rating.pk}/print/').status_code, 404)

    def test_print_grant_opens_html_without_authorization_header(self):
        from rest_framework.authtoken.models import Token
        rating = self.result()
        client = APIClient()
        token, _ = Token.objects.get_or_create(user=self.student)
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        response = client.post(f'/api/results/{rating.pk}/print-access/')
        self.assertEqual(response.status_code, 200)
        cookie = response.cookies['result_print']
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['path'], f'/api/results/{rating.pk}/print/')
        client.credentials()
        printed = client.get(response.data['url'])
        self.assertEqual(printed.status_code, 200)
        self.assertIn('text/html', printed['Content-Type'])
        self.assertEqual(printed['Cache-Control'], 'no-store')
        self.assertIn(client.get('/api/results/').status_code, (401, 403))
        self.student.is_active = False
        self.student.save(update_fields=['is_active'])
        self.assertEqual(client.get(response.data['url']).status_code, 401)

    def test_print_grants_require_ownership_and_reject_tampering_or_expiry(self):
        from django.core import signing
        rating = self.result()
        path = f'/api/results/{rating.pk}/print/'
        access_path = f'/api/results/{rating.pk}/print-access/'
        self.assertEqual(self.api(self.other).post(access_path).status_code, 404)
        client = APIClient()
        self.assertIn(client.post(access_path).status_code, (401, 403))
        client.cookies['result_print'] = 'invalid'
        self.assertEqual(client.get(path).status_code, 401)
        client.cookies['result_print'] = signing.dumps({'user': self.student.pk, 'rating': rating.pk + 1}, salt='result-print')
        self.assertEqual(client.get(path).status_code, 401)
        with patch('django.core.signing.time.time', return_value=1):
            client.cookies['result_print'] = signing.dumps({'user': self.student.pk, 'rating': rating.pk}, salt='result-print')
        self.assertEqual(client.get(path).status_code, 401)

    def test_portal_endpoints_require_login(self):
        for path in ['/api/auth/me/', '/api/my-training-sessions/', '/api/results/',
                     f'/api/training-sessions/{self.training.pk}/']:
            with self.subTest(path=path):
                self.assertIn(self.client.get(path).status_code, (401, 403))


    def test_password_change_revokes_print_grant(self):
        rating = self.result()
        client = self.api(self.student)
        grant = client.post(f'/api/results/{rating.pk}/print-access/')
        self.assertEqual(grant.status_code, 200)
        client.force_authenticate(user=None)
        self.student.set_password('Synthetic-replacement-password-42')
        self.student.save(update_fields=['password'])
        self.assertEqual(client.get(grant.data['url']).status_code, 401)


class ResultVersionTests(TestCase):
    setUpTestData = classmethod(AccessAndSubmissionTests.setUpTestData.__func__)
    api = AccessAndSubmissionTests.api
    payload = AccessAndSubmissionTests.payload
    submit = AccessAndSubmissionTests.submit

    def setUp(self):
        from .result_versions import publish_initial
        self.rating = RatingSession.objects.create(pilot=self.pilot,session=self.template,
            instructor=self.instructor,training_session=self.training,general_notes='Original notes')
        for assignment in [self.assignment,self.second]:
            RatingExercise.objects.create(rating_session=self.rating,assignment=assignment,score=4,completed=True,pro_score=3)
        self.revision = publish_initial(self.rating,self.teacher)
        self.manager = User.objects.create_superuser('responsible',password='synthetic')

    def ack_payload(self, revision=None):
        import uuid
        rev=revision or self.revision
        return {'revision_id':rev.pk,'content_hash':rev.content_hash,'event_id':str(uuid.uuid4())}

    def correction(self, revision=None):
        rev=revision or self.revision
        return {'revision_id':rev.pk,'content_hash':rev.content_hash,'reason':'Corrected after instructor review',
            'general_notes':'Corrected notes','exercises':[
                {'assignment_id':self.assignment.pk,'score':3,'pro_remarks':'Updated remark'},
                {'assignment_id':self.second.pk,'score':5}]}

    def test_only_own_student_can_acknowledge(self):
        url=f'/api/results/{self.rating.pk}/acknowledge/'
        self.assertEqual(self.api(self.teacher).post(url,self.ack_payload(),format='json').status_code,403)
        self.assertEqual(self.api(self.other).post(url,self.ack_payload(),format='json').status_code,404)
        response=self.api(self.student).post(url,self.ack_payload(),format='json')
        self.assertEqual(response.status_code,200,response.data)
        self.assertEqual(response.data['acknowledgement']['name'],self.pilot.name)
        self.assertFalse(response.data['can_acknowledge'])

    def test_acknowledgement_retry_is_idempotent(self):
        from .models import ResultAcknowledgement
        payload=self.ack_payload();url=f'/api/results/{self.rating.pk}/acknowledge/'
        first=self.api(self.student).post(url,payload,format='json')
        second=self.api(self.student).post(url,payload,format='json')
        self.assertEqual(second.status_code,200)
        self.assertEqual(first.data['acknowledgement'],second.data['acknowledgement'])
        self.assertEqual(ResultAcknowledgement.objects.count(),1)

    def test_wrong_hash_is_not_acknowledged(self):
        payload=self.ack_payload();payload['content_hash']='0'*64
        response=self.api(self.student).post(f'/api/results/{self.rating.pk}/acknowledge/',payload,format='json')
        self.assertEqual(response.status_code,409)

    def test_only_responsible_can_create_correction(self):
        url=f'/api/results/{self.rating.pk}/revisions/'
        self.assertEqual(self.api(self.teacher).post(url,self.correction(),format='json').status_code,403)
        self.assertEqual(self.api(self.student).post(url,self.correction(),format='json').status_code,403)
        response=self.api(self.manager).post(url,self.correction(),format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.data['version'],2)
        self.assertEqual(self.rating.revisions.count(),2)
        self.revision.refresh_from_db()
        self.assertEqual(self.revision.snapshot['general_notes'],'Original notes')
        self.rating.refresh_from_db()
        self.assertEqual(self.rating.general_notes,'Corrected notes')

    def test_correction_preserves_old_ack_and_requires_new_one(self):
        from .models import ResultAcknowledgement
        ack=self.ack_payload();url=f'/api/results/{self.rating.pk}/acknowledge/'
        self.api(self.student).post(url,ack,format='json')
        correction=self.api(self.manager).post(f'/api/results/{self.rating.pk}/revisions/',self.correction(),format='json')
        self.assertIsNone(correction.data['acknowledgement'])
        current=self.rating.revisions.first()
        old_payload=self.ack_payload(self.revision)
        self.assertEqual(self.api(self.student).post(url,old_payload,format='json').status_code,409)
        response=self.api(self.student).post(url,self.ack_payload(current),format='json')
        self.assertEqual(response.status_code,200)
        self.assertEqual(ResultAcknowledgement.objects.count(),2)
        replay=self.api(self.student).post(url,ack,format='json')
        self.assertEqual(replay.status_code,200)
        self.assertFalse(replay.data['is_current'])

    def test_stale_correction_and_missing_reason_are_rejected(self):
        url=f'/api/results/{self.rating.pk}/revisions/'
        missing=self.correction();missing['reason']='  '
        self.assertEqual(self.api(self.manager).post(url,missing,format='json').status_code,400)
        self.assertEqual(self.api(self.manager).post(url,self.correction(),format='json').status_code,201)
        self.assertEqual(self.api(self.manager).post(url,self.correction(),format='json').status_code,409)
        self.assertEqual(self.rating.revisions.count(),2)

    def test_invalid_correction_is_atomic(self):
        data=self.correction();data['exercises'][1]['score']=99
        self.assertEqual(self.api(self.manager).post(f'/api/results/{self.rating.pk}/revisions/',data,format='json').status_code,400)
        self.assertEqual(self.rating.revisions.count(),1)
        self.rating.refresh_from_db();self.assertEqual(self.rating.general_notes,'Original notes')

    def test_published_models_and_history_cannot_be_silently_edited(self):
        from django.core.exceptions import ValidationError
        from .models import ResultRevision
        self.rating.general_notes='Silent change'
        with self.assertRaises(ValidationError):self.rating.save()
        item=self.rating.ratingexercise_set.first();item.score=2
        with self.assertRaises(ValidationError):item.save()
        with self.assertRaises(ValidationError):item.delete()
        self.revision.reason='Silent edit'
        with self.assertRaises(ValidationError):self.revision.save()
        with self.assertRaises(ValidationError):ResultRevision.objects.filter(pk=self.revision.pk).update(reason='Changed')
        with self.assertRaises(ValidationError):self.revision.delete()

    def test_old_version_print_uses_snapshot_after_correction_and_renaming(self):
        self.api(self.manager).post(f'/api/results/{self.rating.pk}/revisions/',self.correction(),format='json')
        Exercise.objects.filter(pk=self.exercise.pk).update(name='Renamed exercise')
        response=self.api(self.student).get(f'/api/results/{self.rating.pk}/print/',{'revision':self.revision.pk})
        self.assertEqual(response.status_code,200)
        html=response.content.decode()
        self.assertIn('Original notes',html);self.assertNotIn('Corrected notes',html)
        self.assertIn('Exercise',html);self.assertNotIn('Renamed exercise',html)
        current=self.api(self.student).get(f'/api/results/{self.rating.pk}/print/')
        self.assertIn('Corrected notes',current.content.decode())

    def test_version_history_is_scoped_and_immutable(self):
        url=f'/api/results/{self.rating.pk}/revisions/'
        response=self.api(self.student).get(url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data[0]['version'],1)
        self.assertFalse(response.data[0]['can_revise'])
        self.assertEqual(self.api(self.other).get(url).status_code,404)

    def test_legacy_results_backfill_without_automatic_acknowledgement(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        from .models import ResultAcknowledgement
        legacy=RatingSession.objects.create(pilot=self.other_pilot,session=self.template,instructor=self.instructor,general_notes='Historic notes')
        RatingExercise.objects.create(rating_session=legacy,assignment=self.assignment,score=3)
        migration=importlib.import_module('pilot_training.migrations.0007_snapshot_existing_results')
        migration.snapshot_existing(apps,SimpleNamespace(connection=connection))
        self.assertEqual(legacy.revisions.count(),1)
        self.assertEqual(legacy.revisions.first().snapshot['general_notes'],'Historic notes')
        self.assertEqual(ResultAcknowledgement.objects.count(),0)
