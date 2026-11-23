from datetime import timedelta
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, override_settings
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from rest_framework.authtoken.models import Token, TokenProxy
from rest_framework.test import APIClient

from .login_security import budget_key, client_ip, consume
from .models import Instructor, LoginBudget


class AdminCredentialSecurityTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user('security-staff', is_staff=True)
        self.teacher = get_user_model().objects.create_user('security-instructor')
        self.instructor = Instructor.objects.create(user=self.teacher, name='Synthetic instructor', license='SECURITY')
        self.token = Token.objects.create(user=self.teacher)
        self.client.force_login(self.staff)

    def test_staff_cannot_rotate_credential_via_legacy_url(self):
        url = f'/admin/pilot_training/instructor/{self.instructor.pk}/generate-token/'
        with self.assertRaises(NoReverseMatch):
            reverse('admin:generate-token', args=[self.instructor.pk])
        # Django may redirect an unknown model URL to its generic change view.
        self.assertIn(self.client.get(url).status_code, (302, 403, 404))
        self.assertIn(self.client.post(url).status_code, (302, 403, 404))
        self.assertEqual(Token.objects.get(user=self.teacher).key, self.token.key)

    def test_view_only_admin_never_contains_token_or_token_action(self):
        self.staff.user_permissions.add(Permission.objects.get(codename='view_instructor'))
        response = self.client.get(reverse('admin:pilot_training_instructor_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.token.key.encode() in response.content)
        self.assertNotContains(response, 'generate-token')
        self.assertFalse(admin.site.is_registered(Token))
        self.assertFalse(admin.site.is_registered(TokenProxy))

    def test_password_change_revokes_existing_credential(self):
        self.teacher.set_password('Synthetic-new-password-42')
        self.teacher.save(update_fields=['password'])
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Token ' + self.token.key)
        self.assertEqual(client.get('/api/auth/me/').status_code, 401)
        self.assertFalse(Token.objects.filter(user=self.teacher).exists())

    def test_normal_profile_or_last_login_save_does_not_revoke_credential(self):
        self.teacher.first_name = 'Synthetic'
        self.teacher.save(update_fields=['first_name'])
        self.teacher.last_login = timezone.now()
        self.teacher.save(update_fields=['last_login'])
        self.assertTrue(Token.objects.filter(pk=self.token.pk).exists())

    def test_password_rollback_preserves_credential(self):
        try:
            with transaction.atomic():
                self.teacher.set_password('Synthetic-rolled-back-password-42')
                self.teacher.save(update_fields=['password'])
                raise ValueError('Synthetic rollback')
        except ValueError:
            pass
        self.assertTrue(Token.objects.filter(pk=self.token.pk).exists())


@override_settings(SIM_LOGIN_IP_LIMIT=50, SIM_LOGIN_ACCOUNT_LIMIT=3)
class LoginLimitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('limit-user', password='Synthetic-password-42', is_staff=True)
        self.client = APIClient()
        self.url = '/api/api-token-auth/'

    def login(self, username='limit-user', password='wrong', **kwargs):
        return self.client.post(self.url, {'username': username, 'password': password}, format='json', **kwargs)

    def test_repeated_failures_return_429_and_retry_after(self):
        for _ in range(3):
            self.assertEqual(self.login().status_code, 400)
        response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response['Retry-After']), 0)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertIn('Повторите попытку', str(response.data['detail']))
        self.assertLessEqual(int(response['Retry-After']), 300)
        self.assertFalse(Token.objects.filter(user=self.user).exists())

    def test_account_limit_is_shared_between_ips_and_normalized(self):
        for index in range(3):
            self.assertEqual(self.login(username=' LIMIT-USER ', REMOTE_ADDR=f'203.0.113.{index+1}').status_code, 400)
        self.assertEqual(self.login(REMOTE_ADDR='203.0.113.99').status_code, 429)
        self.assertEqual(LoginBudget.objects.filter(scope='account').count(), 1)

    @override_settings(SIM_LOGIN_IP_LIMIT=2)
    def test_ip_limit_also_covers_different_accounts(self):
        self.assertEqual(self.login(username='wrong-one').status_code, 400)
        self.assertEqual(self.login(username='wrong-two').status_code, 400)
        self.assertEqual(self.login(username='wrong-three').status_code, 429)
        self.assertEqual(self.login(username='wrong-three', REMOTE_ADDR='203.0.113.15').status_code, 400)

    def test_successful_login_keeps_api_contract_and_does_not_spend_account_failures(self):
        for _ in range(5):
            response = self.login(password='Synthetic-password-42')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertIn('token', response.data)
            self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(LoginBudget.objects.get(key=budget_key('account', 'limit-user')).attempts, 0)

    def test_expired_token_header_does_not_block_password_login(self):
        response = self.login(password='Synthetic-password-42', HTTP_AUTHORIZATION='Token expired')
        self.assertEqual(response.status_code, 200)

    def test_window_expiry_allows_login_again(self):
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            for _ in range(3): self.login()
            self.assertEqual(self.login().status_code, 429)
        with patch('django.utils.timezone.now', return_value=now + timedelta(seconds=301)):
            self.assertEqual(self.login(password='Synthetic-password-42').status_code, 200)

    def test_admin_login_uses_same_failed_attempt_budget(self):
        for _ in range(3):
            response = self.client.post('/admin/login/', {'username': 'limit-user', 'password': 'wrong'})
            self.assertEqual(response.status_code, 200)
        response = self.client.post('/admin/login/', {'username': 'limit-user', 'password': 'wrong'})
        self.assertEqual(response.status_code, 429)
        self.assertIn('Retry-After', response)
        self.assertEqual(self.login().status_code, 429)

    def test_valid_admin_login_releases_account_reservation(self):
        response = self.client.post('/admin/login/', {'username': 'limit-user', 'password': 'Synthetic-password-42'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(LoginBudget.objects.get(key=budget_key('account', 'limit-user')).attempts, 0)

    def test_budget_storage_contains_no_plaintext_ip_or_username(self):
        self.login(REMOTE_ADDR='203.0.113.17')
        for row in LoginBudget.objects.all():
            self.assertEqual(len(row.key), 64)
            self.assertNotIn('limit-user', row.key)
            self.assertNotIn('203.0.113.17', row.key)

    def test_cleanup_retains_active_and_recent_windows(self):
        now = timezone.now()
        LoginBudget.objects.create(key='a'*64, scope='ip', expires_at=now-timedelta(days=2))
        LoginBudget.objects.create(key='b'*64, scope='ip', expires_at=now-timedelta(hours=1))
        LoginBudget.objects.create(key='c'*64, scope='ip', expires_at=now+timedelta(minutes=1))
        call_command('purge_login_budgets', verbosity=0)
        self.assertCountEqual(LoginBudget.objects.values_list('key', flat=True), ['b'*64, 'c'*64])

    def test_untrusted_client_cannot_choose_forwarded_address(self):
        from django.test import RequestFactory
        factory = RequestFactory()
        direct = factory.post('/', REMOTE_ADDR='203.0.113.17', HTTP_X_FORWARDED_FOR='203.0.113.99')
        proxy = factory.post('/', REMOTE_ADDR='127.0.0.1', HTTP_X_FORWARDED_FOR='203.0.113.99')
        self.assertEqual(client_ip(direct), '203.0.113.17')
        self.assertEqual(client_ip(proxy), '203.0.113.99')


from concurrent.futures import ThreadPoolExecutor
from django.db import close_old_connections, connections
from django.test import TransactionTestCase, skipUnlessDBFeature


class ConcurrentLoginLimitTests(TransactionTestCase):
    @skipUnlessDBFeature('has_select_for_update')
    def test_parallel_requests_cannot_exceed_account_budget(self):
        from rest_framework.exceptions import Throttled
        key = budget_key('account', 'parallel-account')
        LoginBudget.objects.create(key=key, scope='account', expires_at=timezone.now()+timedelta(minutes=5))
        def attempt(_):
            close_old_connections()
            try:
                consume('account', 'parallel-account', 3, 300)
                return True
            except Throttled:
                return False
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(outcomes), 3)
        self.assertEqual(LoginBudget.objects.get(pk=key).attempts, 3)
