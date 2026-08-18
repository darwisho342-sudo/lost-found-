"""Verified-account and University/International scope authorization."""

from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.utils.translation import gettext as _


class UniversityAccessService:
    """Keep University access decisions in one server-side service."""

    @staticmethod
    def email_domain(email):
        value = (email or "").strip().casefold()
        return value.rsplit("@", 1)[1] if value.count("@") == 1 else ""

    @classmethod
    def email_is_eligible(cls, email):
        return cls.email_domain(email) in set(settings.UNIVERSITY_EMAIL_DOMAINS)

    @staticmethod
    def profile_for(user):
        from .models import UserProfile

        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile

    @classmethod
    def is_verified(cls, user):
        if not user.is_authenticated or not user.is_active:
            return False
        if user.is_staff:
            return True
        profile = cls.profile_for(user)
        return bool(profile.email_verified_at and profile.university_eligible
                    and not profile.university_eligibility_lost_at
                    and cls.email_is_eligible(user.email))

    @classmethod
    def has_verified_email(cls, user):
        if not user.is_authenticated or not user.is_active:
            return False
        if user.is_staff:
            return True
        return bool(cls.profile_for(user).email_verified_at)

    @classmethod
    def can_access_scope(cls, user, scope):
        from .models import ItemReport

        if scope == ItemReport.Scope.UNIVERSITY:
            return cls.is_verified(user)
        if scope == ItemReport.Scope.INTERNATIONAL:
            return cls.has_verified_email(user)
        return False

    @classmethod
    def accessible_scopes(cls, user):
        from .models import ItemReport

        if cls.is_verified(user):
            return tuple(ItemReport.Scope.values)
        if cls.has_verified_email(user):
            return (ItemReport.Scope.INTERNATIONAL,)
        return ()

    @classmethod
    def require_scope(cls, user, scope):
        from .models import ItemReport

        if not cls.can_access_scope(user, scope):
            if scope == ItemReport.Scope.UNIVERSITY:
                raise PermissionDenied(_("A verified University account is required for University Mode."))
            raise PermissionDenied(_("Verify your email address before using International Mode."))

    @classmethod
    def active_scope(cls, request, *, allow_public=True):
        """Resolve and remember a safe UI scope without weakening action checks."""
        from .models import ItemReport

        allowed = set(ItemReport.Scope.values)
        requested = request.GET.get("scope") or request.POST.get("scope")
        session = getattr(request, "session", {})
        scope = requested or session.get("findmatch_scope")
        if not scope and request.user.is_authenticated:
            scope = cls.profile_for(request.user).preferred_scope
        if scope not in allowed:
            scope = ItemReport.Scope.UNIVERSITY
        if request.user.is_authenticated and cls.has_verified_email(request.user):
            if scope == ItemReport.Scope.UNIVERSITY and not cls.is_verified(request.user):
                if requested == ItemReport.Scope.UNIVERSITY:
                    raise PermissionDenied(_("Your verified account has International access only."))
                scope = ItemReport.Scope.INTERNATIONAL
        elif not allow_public:
            cls.require_scope(request.user, scope)
        if requested in allowed:
            if hasattr(request, "session"):
                request.session["findmatch_scope"] = scope
            if request.user.is_authenticated:
                profile = cls.profile_for(request.user)
                if profile.preferred_scope != scope:
                    profile.preferred_scope = scope
                    profile.save(update_fields=("preferred_scope", "updated_at"))
        return scope

    @classmethod
    def require_verified(cls, user):
        if not cls.is_verified(user):
            raise PermissionDenied(
                _("Verify an approved University email address before using this feature.")
            )


def verified_university_required(view):
    """Require login plus verified University status without template-only checks."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        UniversityAccessService.require_verified(request.user)
        return view(request, *args, **kwargs)

    return wrapped


def verified_scope_required(view):
    """Require a verified account permitted to use the selected session scope."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login

            return redirect_to_login(request.get_full_path())
        scope = UniversityAccessService.active_scope(request, allow_public=False)
        UniversityAccessService.require_scope(request.user, scope)
        request.findmatch_scope = scope
        return view(request, *args, **kwargs)

    return wrapped
