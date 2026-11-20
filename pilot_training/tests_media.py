from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from pilot_logbook.media_views import protected_media


class ProductionMediaTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'docs').mkdir()
        (self.root / 'uploads').mkdir()
        (self.root / 'docs' / 'lesson.pdf').write_bytes(b'%PDF-test')
        (self.root / 'uploads' / 'students.xlsx').write_bytes(b'private')
        self.settings_override = override_settings(MEDIA_ROOT=self.root)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.factory = APIRequestFactory()

    def response(self, path, staff=None):
        request = self.factory.get('/media/' + path)
        if staff is not None:
            force_authenticate(request, user=SimpleNamespace(is_authenticated=True, is_staff=staff))
        response = protected_media(request, path)
        self.addCleanup(response.close)
        return response

    def test_anonymous_cannot_read_documents(self):
        self.assertEqual(self.response('docs/lesson.pdf').status_code, 401)

    def test_authenticated_can_read_pdf_but_not_private_uploads(self):
        response = self.response('docs/lesson.pdf', staff=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-test')
        self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(self.response('uploads/students.xlsx', staff=False).status_code, 403)

    def test_staff_can_download_upload(self):
        self.assertEqual(self.response('uploads/students.xlsx', staff=True).status_code, 200)

    def test_symlink_cannot_escape_media_root(self):
        with TemporaryDirectory() as outside:
            secret = Path(outside) / 'secret.pdf'
            secret.write_bytes(b'outside')
            (self.root / 'docs' / 'escape.pdf').symlink_to(secret)
            self.assertEqual(self.response('docs/escape.pdf', staff=True).status_code, 404)

    def test_traversal_and_missing_files_are_rejected(self):
        self.assertEqual(self.response('../outside.pdf', staff=True).status_code, 404)
        self.assertEqual(self.response('missing.pdf', staff=True).status_code, 404)
