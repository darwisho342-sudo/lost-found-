from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from .models import ItemReport
from .university import UniversityAccessService


def notification_center(request):
    context = {
        "university_name": settings.UNIVERSITY_NAME,
        "university_security_office": settings.UNIVERSITY_SECURITY_OFFICE,
        "international_mode_enabled": settings.INTERNATIONAL_MODE_ENABLED,
        "open_university_access": settings.OPEN_UNIVERSITY_ACCESS,
        "session_cookie_age": settings.SESSION_COOKIE_AGE,
    }
    try:
        context["active_scope"] = UniversityAccessService.active_scope(request)
    except PermissionDenied:
        context["active_scope"] = ItemReport.Scope.INTERNATIONAL
    context["scope_choices"] = ItemReport.Scope.choices
    context["has_university_access"] = UniversityAccessService.is_verified(request.user)
    context["has_verified_email"] = UniversityAccessService.has_verified_email(request.user)
    if not request.user.is_authenticated:
        return context
    notifications = request.user.notifications.filter(
        Q(item_report__isnull=True)
        | Q(item_report__scope__in=UniversityAccessService.accessible_scopes(request.user))
    )
    context.update({
        "notification_preview": notifications[:6],
        "notification_unread_count": notifications.filter(is_read=False).count(),
    })
    return context
