"""Report lifecycle operations with privacy-safe notifications and audit records."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .communications import record_contact_event
from .models import ContactAuditLog, ItemReport, Notification
from .notification_service import NotificationService


class ReportLifecycleService:
    default_lifetime = timedelta(days=90)
    warning_window = timedelta(days=7)

    @classmethod
    def initialize_expiration(cls, report):
        if report.status == ItemReport.Status.ACTIVE and not report.expires_at:
            report.expires_at = timezone.now() + cls.default_lifetime
            report.save(update_fields=("expires_at", "updated_at"))

    @classmethod
    def renew(cls, *, report, user):
        if user.pk != report.owner_id and not user.is_staff:
            raise PermissionDenied
        if report.status not in (ItemReport.Status.ACTIVE, ItemReport.Status.EXPIRED, ItemReport.Status.CLOSED):
            raise ValidationError(_("This report cannot be renewed in its current state."))
        with transaction.atomic():
            report = ItemReport.objects.select_for_update().get(pk=report.pk)
            report.status = ItemReport.Status.ACTIVE
            report.renewed_at = timezone.now()
            report.expires_at = timezone.now() + cls.default_lifetime
            report.save(update_fields=("status", "renewed_at", "expires_at", "updated_at"))
            return report

    @classmethod
    def process_expiration(cls, now=None):
        now = now or timezone.now()
        warning_limit = now + cls.warning_window
        warning_reports = ItemReport.objects.filter(
            status=ItemReport.Status.ACTIVE, expires_at__gt=now, expires_at__lte=warning_limit,
        ).select_related("owner")
        for report in warning_reports:
            NotificationService.create(
                recipient=report.owner, notification_type=Notification.NotificationType.EXPIRATION_WARNING,
                title=_("Report expires soon"),
                safe_message=_("One of your active reports will expire soon. Open it to review or renew."),
                item_report=report, destination_url=reverse("item_detail", args=(report.pk,)),
                deduplication_key=f"expiration-warning:{report.pk}:{report.expires_at.date()}",
            )
        expired = ItemReport.objects.filter(status=ItemReport.Status.ACTIVE, expires_at__lte=now)
        count = expired.update(status=ItemReport.Status.EXPIRED, updated_at=now)
        return count
