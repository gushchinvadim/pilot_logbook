from rest_framework.permissions import BasePermission, SAFE_METHODS
from .access import authenticated, can_manage


class IsInstructorUser(BasePermission):
    def has_permission(self, request, view):
        return authenticated(request.user) and hasattr(request.user, 'instructor')


class ScopedModelPermission(BasePermission):
    """Reads use the view's scope; writes require explicit model permission."""
    def has_permission(self, request, view):
        if not authenticated(request.user):
            return False
        if request.method in SAFE_METHODS:
            return True
        action = {"POST": "add", "PUT": "change", "PATCH": "change", "DELETE": "delete"}.get(request.method)
        return bool(action) and can_manage(request.user, view.queryset.model, action)
