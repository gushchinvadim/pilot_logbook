"""Authenticated access to uploaded files when Django runs in production."""
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied


@api_view(['GET'])
@authentication_classes([TokenAuthentication, SessionAuthentication])
@permission_classes([IsAuthenticated])
def protected_media(request, file_path):
    root = Path(settings.MEDIA_ROOT).resolve()
    target = (root / file_path).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise Http404
    relative = target.relative_to(root)
    shared_document = relative.parts[0] == 'docs' and target.suffix.lower() == '.pdf'
    if not shared_document and not request.user.is_staff:
        raise PermissionDenied
    response = FileResponse(target.open('rb'), as_attachment=not shared_document, filename=target.name)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
