from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import time

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Pilot, Instructor


class ReferenceDocumentTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'docs').mkdir()
        (self.root / 'uploads').mkdir()
        self.filename = 'РЛЭ Boeing 737 #1 100%.PDF'
        (self.root / 'docs' / self.filename).write_bytes(b'%PDF-synthetic-reference')
        (self.root / 'docs' / 'QRH.pdf').write_bytes(b'%PDF-other')
        (self.root / 'docs' / 'private.xlsx').write_bytes(b'private')
        private = self.root / 'uploads' / 'students.pdf'
        private.write_bytes(b'private-students')
        (self.root / 'docs' / 'escape.pdf').symlink_to(private)
        self.override = override_settings(MEDIA_ROOT=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        User = get_user_model()
        self.student = User.objects.create_user('reference-student')
        self.instructor = User.objects.create_user('reference-instructor')
        Pilot.objects.create(user=self.student, name='Synthetic Student', license='REFERENCE-P1')
        Instructor.objects.create(user=self.instructor, name='Synthetic Instructor', license='REFERENCE-I1')
        self.client = APIClient()
        self.open_url = reverse('pilot_training:prepare_reference')
        self.pdf_url = reverse('pilot_training:reference_pdf', kwargs={'filename': self.filename})

    def grant(self, user=None):
        self.client.force_authenticate(user or self.student)
        response = self.client.post(self.open_url, {'filename': self.filename}, format='json', secure=True)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['url'], self.pdf_url)
        browser = APIClient()
        browser.cookies.update(response.cookies)
        return response, browser

    def test_both_roles_can_list_pdfs_but_private_and_escaped_files_are_hidden(self):
        for user in (self.student, self.instructor):
            self.client.force_authenticate(user)
            response = self.client.get('/api/docs/')
            self.assertEqual(response.status_code, 200)
            self.assertCountEqual(response.json()['files'], [self.filename, 'QRH.pdf'])

    def test_anonymous_cannot_list_prepare_or_open(self):
        self.assertEqual(self.client.get('/api/docs/').status_code, 401)
        self.assertEqual(self.client.post(self.open_url, {'filename': self.filename}, format='json').status_code, 401)
        self.assertEqual(self.client.get(self.pdf_url).status_code, 401)

    def test_native_pdf_viewer_can_open_unicode_filename_without_authorization_header(self):
        grant, browser = self.grant()
        cookie = grant.cookies['reference_pdf']
        self.assertTrue(cookie['httponly'])
        self.assertTrue(cookie['secure'])
        self.assertEqual(cookie['samesite'], 'Strict')
        self.assertEqual(cookie['path'], self.pdf_url)
        response = browser.get(grant.data['url'], secure=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-synthetic-reference')

    def test_grant_cannot_open_other_document_or_authenticate_other_apis(self):
        _, browser = self.grant()
        other = reverse('pilot_training:reference_pdf', kwargs={'filename': 'QRH.pdf'})
        self.assertEqual(browser.get(other).status_code, 401)
        self.assertEqual(browser.get('/api/auth/me/').status_code, 401)

    def test_expired_or_tampered_grant_and_inactive_account_are_rejected(self):
        _, browser = self.grant()
        now = time.time()
        with patch('django.core.signing.time.time', return_value=now + 601):
            self.assertEqual(browser.get(self.pdf_url).status_code, 401)
        browser.cookies['reference_pdf'] = 'tampered'
        self.assertEqual(browser.get(self.pdf_url).status_code, 401)
        _, browser = self.grant()
        self.student.is_active = False
        self.student.save(update_fields=['is_active'])
        self.assertEqual(browser.get(self.pdf_url).status_code, 401)

    def test_only_reference_pdfs_can_be_opened(self):
        self.client.force_authenticate(self.instructor)
        for filename in ('../uploads/students.pdf', 'escape.pdf', 'private.xlsx', 'missing.pdf', '', None):
            response = self.client.post(self.open_url, {'filename': filename}, format='json')
            self.assertEqual(response.status_code, 404, filename)

    def test_empty_library_is_valid(self):
        with TemporaryDirectory() as empty, override_settings(MEDIA_ROOT=empty):
            self.client.force_authenticate(self.student)
            self.assertEqual(self.client.get('/api/docs/').json(), {'files': []})


    def test_password_change_revokes_browser_pdf_grant(self):
        _, browser = self.grant()
        self.student.set_password('Synthetic-replacement-password-42')
        self.student.save(update_fields=['password'])
        self.assertEqual(browser.get(self.pdf_url).status_code, 401)
