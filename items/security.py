"""Small deterministic security helpers; no external service is required."""

import hashlib
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import UserProfile


class RateLimitService:
    limits = {
        "report": (8, 3600),
        "claim": (10, 3600),
        "message": (30, 60),
        "login": (10, 900),
    }

    @classmethod
    def check(cls, request, action):
        maximum, window = cls.limits[action]
        identity = request.user.pk if request.user.is_authenticated else request.META.get("REMOTE_ADDR", "unknown")
        digest = hashlib.sha256(str(identity).encode()).hexdigest()[:24]
        key = f"findmatch-rate:{action}:{digest}"
        count = cache.get(key, 0)
        if count >= maximum:
            raise ValidationError(_("Too many attempts. Please wait before trying again."))
        if count:
            cache.incr(key)
        else:
            cache.set(key, 1, window)


class EmailVerificationService:
    salt = "findmatch-email-verification"
    max_age = int(timedelta(days=2).total_seconds())

    @classmethod
    def token(cls, user):
        return signing.dumps({"user_id": user.pk, "email": user.email}, salt=cls.salt, compress=True)

    @classmethod
    def verify(cls, token, user_model):
        payload = signing.loads(token, salt=cls.salt, max_age=cls.max_age)
        user = user_model.objects.get(pk=payload["user_id"], email__iexact=payload["email"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.email_verified_at = timezone.now()
        profile.save(update_fields=("email_verified_at", "updated_at"))
        return user

    @classmethod
    def send(cls, request, user):
        url = request.build_absolute_uri(reverse("verify_email", args=(cls.token(user),)))
        send_mail(
            _("Verify your FindMatch email"),
            _("Open this link to verify your email address: %(url)s") % {"url": url},
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=True,
        )
        return url
