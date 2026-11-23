"""Reference PDFs shared by authenticated portal users."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.http import FileResponse, Http404
from django.urls import reverse
from rest_framework.authentication import BaseAuthentication, SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

GRANT_AGE = 600
GRANT_SALT = 'reference-document'


def reference_file(filename):
    if not isinstance(filename, str) or not filename or '/' in filename or '\\' in filename or '\x00' in filename:
        raise Http404
    root = (Path(settings.MEDIA_ROOT) / 'docs').resolve()
    target = (root / filename).resolve()
    if not target.is_relative_to(root) or target.parent != root or target.suffix.lower() != '.pdf' or not target.is_file():
        raise Http404
    return target


def reference_filenames():
    root = Path(settings.MEDIA_ROOT) / 'docs'
    if not root.is_dir():
        return []
    result = []
    for entry in root.iterdir():
        try:
            reference_file(entry.name)
        except Http404:
            continue
        result.append(entry.name)
    return sorted(result, key=str.casefold)


class ReferenceCookieAuthentication(BaseAuthentication):
    """A short-lived browser grant for exactly one PDF; never valid for other APIs."""
    def authenticate(self, request):
        if request.method not in ('GET', 'HEAD'):
            return None
        try:
            grant = signing.loads(request.COOKIES.get('reference_pdf', ''), salt=GRANT_SALT, max_age=GRANT_AGE)
            if grant['filename'] != request.parser_context['kwargs']['filename']:
                return None
            user = get_user_model().objects.get(pk=grant['user'], is_active=True)
            if not user.get_session_auth_hash() == grant.get('auth'):
                return None
        except (signing.BadSignature, KeyError, TypeError, get_user_model().DoesNotExist):
            return None
        return user, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def prepare_reference(request):
    filename = request.data.get('filename')
    reference_file(filename)
    url = reverse('pilot_training:reference_pdf', kwargs={'filename': filename})
    response = Response({'url': url})
    response.set_cookie('reference_pdf', signing.dumps({'user': request.user.pk, 'filename': filename, 'auth': request.user.get_session_auth_hash()}, salt=GRANT_SALT),
        path=url, max_age=GRANT_AGE, secure=request.is_secure(), httponly=True, samesite='Strict')
    response['Cache-Control'] = 'no-store'
    return response


@api_view(['GET', 'HEAD'])
@authentication_classes([TokenAuthentication, SessionAuthentication, ReferenceCookieAuthentication])
@permission_classes([IsAuthenticated])
def reference_pdf(request, filename):
    target = reference_file(filename)
    response = FileResponse(target.open('rb'), content_type='application/pdf', as_attachment=False, filename=filename)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
