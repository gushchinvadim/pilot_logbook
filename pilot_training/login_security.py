"""Shared, transaction-locked login limits for API and Django admin."""
from datetime import timedelta
from functools import wraps
import ipaddress
import math

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.http import HttpResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import Throttled
from rest_framework.throttling import BaseThrottle

from .models import LoginBudget


class LoginThrottled(Throttled):
    extra_detail_singular = 'Повторите попытку через {wait} сек.'
    extra_detail_plural = extra_detail_singular


def client_ip(request):
    remote = request.META.get('REMOTE_ADDR', '')
    # Nginx overwrites X-Forwarded-For; direct clients cannot select a forged address.
    if remote in ('127.0.0.1', '::1'):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '').strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    try:
        return str(ipaddress.ip_address(remote))
    except ValueError:
        return 'unknown'


def budget_key(scope, value):
    return salted_hmac('sim-login-budget', scope + ':' + value, algorithm='sha256').hexdigest()


def consume(scope, value, limit, seconds):
    key = budget_key(scope, value)
    now = timezone.now()
    with transaction.atomic():
        row, _ = LoginBudget.objects.select_for_update().get_or_create(
            key=key, defaults={'scope': scope, 'expires_at': now + timedelta(seconds=seconds)})
        if row.expires_at <= now:
            row.attempts = 0
            row.expires_at = now + timedelta(seconds=seconds)
        if row.attempts >= limit:
            raise LoginThrottled(wait=max(1, math.ceil((row.expires_at - now).total_seconds())),
                detail='Слишком много попыток входа. Повторите позже.')
        row.attempts += 1
        row.save(update_fields=['attempts', 'expires_at'])
        return row.key, row.expires_at


def reserve_login(request, username):
    # Count all requests per IP, including malformed payloads and valid logins.
    consume('ip', client_ip(request), getattr(settings, 'SIM_LOGIN_IP_LIMIT', 60), 60)
    if isinstance(username, str) and username.strip():
        return consume('account', username.strip().casefold(), getattr(settings, 'SIM_LOGIN_ACCOUNT_LIMIT', 10), 300)
    return None


def release_success(reservation):
    if reservation:
        key, expiry = reservation
        # Successful logins do not spend the account's failed-attempt allowance.
        # Match the window too: a late request must not decrement a newer window.
        LoginBudget.objects.filter(key=key, expires_at=expiry, attempts__gt=0).update(attempts=F('attempts') - 1)


class LoginThrottle(BaseThrottle):
    def allow_request(self, request, view):
        # Reserve the IP before parsing the body: invalid JSON must also be limited.
        consume('ip', client_ip(request), getattr(settings, 'SIM_LOGIN_IP_LIMIT', 60), 60)
        username = request.data.get('username') if isinstance(request.data, dict) else None
        request.login_reservation = None
        if isinstance(username, str) and username.strip():
            request.login_reservation = consume('account', username.strip().casefold(),
                getattr(settings, 'SIM_LOGIN_ACCOUNT_LIMIT', 10), 300)
        return True


def protect_admin_login(original_login):
    @wraps(original_login)
    def login(request, extra_context=None):
        reservation = None
        if request.method == 'POST':
            try:
                reservation = reserve_login(request, request.POST.get('username'))
            except Throttled as error:
                response = HttpResponse('Слишком много попыток входа. Пожалуйста, повторите позже.',
                    status=429, content_type='text/plain; charset=utf-8')
                response['Retry-After'] = str(error.wait)
                response['Cache-Control'] = 'no-store'
                return response
        response = original_login(request, extra_context=extra_context)
        if request.method == 'POST' and response.status_code in (302, 303) and request.user.is_authenticated:
            release_success(reservation)
        return response
    return login
