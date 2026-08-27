"""Verified-account and University/International scope authorization."""

from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.translation import gettext as _


class UniversityModePermissionDenied(PermissionDenied):
    """Permission error that lets the 403 page offer safe mode-recovery actions."""


class UniversityAccessService:
    """Keep University access decisions in one server-side service."""

    SESSION_SCOPE_KEY = "findmatch_scope"
    PENDING_SCOPE_KEY = "findmatch_pending_scope"

    @staticmethod
    def normalize_email(email):
        return (email or "").strip().casefold()

    @classmethod
    def email_domain(cls, email):
        value = cls.normalize_email(email)
        return value.rsplit("@", 1)[1] if value.count("@") == 1 else ""

    @classmethod
    def email_is_eligible(cls, email):
        return cls.email_domain(email) in set(settings.UNIVERSITY_EMAIL_DOMAINS)

    @staticmethod
    def profile_for(user):
        from .models import UserProfile

        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile

    @staticmethod
    def is_authorized_staff(user):
        """Django staff status remains the source of truth for University staff access."""
        return bool(user.is_authenticated and user.is_active and (user.is_staff or user.is_superuser))

    @classmethod
    def synchronize_eligibility(cls, user, profile=None):
        """Refresh cached profile eligibility from the configured exact domains."""
        if not user.is_authenticated:
            return profile
        profile = profile or cls.profile_for(user)
        eligible = bool(user.is_active and cls.email_is_eligible(user.email))
        changed = []
        if profile.university_eligible != eligible:
            profile.university_eligible = eligible
            changed.append("university_eligible")
        if eligible and profile.university_eligibility_lost_at is not None:
            profile.university_eligibility_lost_at = None
            changed.append("university_eligibility_lost_at")
        elif not eligible and profile.university_eligibility_lost_at is None:
            profile.university_eligibility_lost_at = timezone.now()
            changed.append("university_eligibility_lost_at")
        if (
            not eligible
            and not settings.OPEN_UNIVERSITY_ACCESS
            and not cls.is_authorized_staff(user)
            and profile.preferred_scope == "university"
        ):
            profile.preferred_scope = "international"
            changed.append("preferred_scope")
        if changed:
            changed.append("updated_at")
            profile.save(update_fields=changed)
        return profile

    @classmethod
    def is_verified(cls, user):
        if not user.is_authenticated or not user.is_active:
            return False
        if settings.OPEN_UNIVERSITY_ACCESS:
            cls.synchronize_eligibility(user)
            return True
        if cls.is_authorized_staff(user):
            cls.synchronize_eligibility(user)
            return True
        profile = cls.synchronize_eligibility(user)
        return bool(profile.email_verified_at and profile.university_eligible
                    and not profile.university_eligibility_lost_at
                    and cls.email_is_eligible(user.email))

    @classmethod
    def has_verified_email(cls, user):
        if not user.is_authenticated or not user.is_active:
            return False
        if user.is_staff:
            return True
        return bool(cls.synchronize_eligibility(user).email_verified_at)

    @classmethod
    def can_access_scope(cls, user, scope):
        from .models import ItemReport

        if (
            settings.OPEN_UNIVERSITY_ACCESS
            and user.is_authenticated
            and user.is_active
            and scope in ItemReport.Scope.values
        ):
            return True
        if scope == ItemReport.Scope.UNIVERSITY:
            return cls.is_verified(user)
        if scope == ItemReport.Scope.INTERNATIONAL:
            return cls.has_verified_email(user)
        return False

    @classmethod
    def accessible_scopes(cls, user):
        from .models import ItemReport

        if settings.OPEN_UNIVERSITY_ACCESS and user.is_authenticated and user.is_active:
            return tuple(ItemReport.Scope.values)
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
                raise UniversityModePermissionDenied(
                    _(
                        "University Mode is available only to verified Biruni University "
                        "students and authorized staff. You can continue using International Mode."
                    )
                )
            raise PermissionDenied(_("Verify your email address before using International Mode."))

    @classmethod
    def save_scope(cls, request, scope):
        """Validate and persist a selected scope for an authenticated account."""
        from .models import ItemReport

        if scope not in ItemReport.Scope.values:
            raise ValueError("Unsupported FindMatch scope")
        cls.synchronize_eligibility(request.user)
        cls.require_scope(request.user, scope)
        request.session[cls.SESSION_SCOPE_KEY] = scope
        request.session.pop(cls.PENDING_SCOPE_KEY, None)
        profile = cls.profile_for(request.user)
        if profile.preferred_scope != scope:
            profile.preferred_scope = scope
            profile.save(update_fields=("preferred_scope", "updated_at"))
        request.findmatch_scope = scope
        return scope

    @classmethod
    def active_scope(cls, request, *, allow_public=True):
        """Resolve and remember a safe UI scope without weakening action checks."""
        from .models import ItemReport

        allowed = set(ItemReport.Scope.values)
        requested = request.GET.get("scope") or request.POST.get("scope")
        session = getattr(request, "session", {})
        scope = requested or session.get(cls.SESSION_SCOPE_KEY)
        if not scope and request.user.is_authenticated:
            scope = cls.profile_for(request.user).preferred_scope
        if scope not in allowed:
            scope = ItemReport.Scope.UNIVERSITY
        if request.user.is_authenticated and cls.has_verified_email(request.user):
            if scope == ItemReport.Scope.UNIVERSITY and not cls.is_verified(request.user):
                if requested == ItemReport.Scope.UNIVERSITY:
                    raise UniversityModePermissionDenied(
                        _(
                            "University Mode is available only to verified Biruni University "
                            "students and authorized staff. You can continue using International Mode."
                        )
                    )
                scope = ItemReport.Scope.INTERNATIONAL
        elif not allow_public:
            cls.require_scope(request.user, scope)
        if requested in allowed:
            if hasattr(request, "session"):
                request.session[cls.SESSION_SCOPE_KEY] = scope
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
