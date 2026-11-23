import io
from unittest.mock import patch
from django.test import SimpleTestCase, override_settings
from .atcd_client import fetch_schedule, ATCDError, NoRedirect


@override_settings(ATCD_BASE_URL='https://nordstar.atcdocs.ru', ATCD_EXPORT_KEY='synthetic-key-over-thirty-two-characters')
class ATCDClientTests(SimpleTestCase):
    def test_credential_only_goes_to_fixed_server_and_redirects_are_disabled(self):
        with patch('pilot_training.atcd_client.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'{"schema":1,"source":"nordstar-atcd","rows":[]}')
            self.assertEqual(fetch_schedule('2026-11-20','2026-11-21'),[])
            self.assertIsInstance(opener.call_args.args[0],NoRedirect)
            req=opener.return_value.open.call_args.args[0]
            self.assertTrue(req.full_url.startswith('https://nordstar.atcdocs.ru/api/integrations/'))
            self.assertEqual(req.get_header('X-sim-integration-key'),'synthetic-key-over-thirty-two-characters')

    def test_untrusted_host_and_duplicate_ids_are_rejected(self):
        with override_settings(ATCD_BASE_URL='https://attacker.example'),patch('pilot_training.atcd_client.build_opener') as opener:
            with self.assertRaises(ATCDError): fetch_schedule('2026-11-20','2026-11-21')
            opener.assert_not_called()
        with patch('pilot_training.atcd_client.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.return_value=io.BytesIO(b'{"schema":1,"source":"nordstar-atcd","rows":[{"id":1},{"id":1}]}')
            with self.assertRaises(ATCDError): fetch_schedule('2026-11-20','2026-11-21')

    def test_local_http_only_in_debug_and_failed_response_does_not_expose_key(self):
        with override_settings(DEBUG=False,ATCD_BASE_URL='http://127.0.0.1:8000'):
            with self.assertRaises(ATCDError): fetch_schedule('2026-11-20','2026-11-21')
        with patch('pilot_training.atcd_client.build_opener',side_effect=ValueError('synthetic-key-over-thirty-two-characters')):
            with self.assertRaises(ATCDError) as error: fetch_schedule('2026-11-20','2026-11-21')
            self.assertNotIn('synthetic-key',str(error.exception))
