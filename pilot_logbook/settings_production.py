"""Production settings for the same-origin React portal behind a local Nginx proxy."""
from .settings import *  # noqa: F403
from decouple import config
from django.core.exceptions import ImproperlyConfigured

DEBUG = False
SECRET_KEY = config('SECRET_KEY')
ALLOWED_HOSTS = [host.strip() for host in config('ALLOWED_HOSTS', default='survey-ebt.ru').split(',') if host.strip()]
if not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS:
    raise ImproperlyConfigured('Set explicit ALLOWED_HOSTS for production.')
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in config(
    'CSRF_TRUSTED_ORIGINS', default='https://survey-ebt.ru').split(',') if origin.strip()]
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.postgresql', 'NAME': config('DB_NAME'), 'USER': config('DB_USER'),
    'PASSWORD': config('DB_PASSWORD'), 'HOST': config('DB_HOST', default='127.0.0.1'),
    'PORT': config('DB_PORT', default='5432'), 'CONN_MAX_AGE': 60,
}}
STATIC_URL = '/static/'
STATIC_ROOT = config('STATIC_ROOT', default='/srv/sim-training/shared/staticfiles')
MEDIA_URL = '/media/'
MEDIA_ROOT = config('MEDIA_ROOT', default='/srv/sim-training/shared/media')
# Gunicorn listens only on loopback; Nginx overwrites this header, never trusting the client's copy.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = []
CORS_ALLOW_CREDENTIALS = False
# No preload/subdomain policy is imposed on other applications using the same domain family.
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=3600, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
