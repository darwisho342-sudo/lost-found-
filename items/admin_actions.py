from dataclasses import dataclass, field
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .communications import record_contact_event
from .models import ContactAuditLog, ItemReport, Notification
from .notification_service import NotificationService


@dataclass
class BulkActionResult:
    success_count: int = 0
    skipped_count: int = 0
    skipped_reasons: list[str] = field(default_factory=list)


class AdminReportActionService:
    ACTION_LABELS = {
        "mark_reviewed": "Mark as Reviewed",
        "mark_active": "Mark as Active",
        "mark_resolved": "Mark as Resolved",
        "close": "Close Selected",
        "hide": "Hide Selected",
        "delete": "Delete Selected",
    }
    CONFIRMATION_ACTIONS = {"mark_resolved", "close", "hide", "delete"}

    @classmethod
    def apply(cls, *, administrator, reports, action):
        if not administrator.is_staff:
            raise PermissionDenied
        if action not in cls.ACTION_LABELS:
            raise ValueError("Choose an action before continuing.")
        reports = list(reports)
        result = BulkActionResult()
        operation_key = uuid4().hex
        with transaction.atomic():
            locked_reports = list(
                ItemReport.objects.select_for_update().filter(pk__in=[report.pk for report in reports])
            )
            for report in locked_reports:
                skip_reason = cls._apply_one(report, action, administrator)
                if skip_reason:
                    result.skipped_count += 1
                    if skip_reason not in result.skipped_reasons:
                        result.skipped_reasons.append(skip_reason)
                    continue
                result.success_count += 1
                NotificationService.create(
                    recipient=report.owner,
                    notification_type=Notification.NotificationType.REPORT_STATUS_CHANGED,
                    title="Report updated",
                    safe_message=f"An administrator updated your report ‘{report.title}’.",
                    item_report=report,
                    destination_url=report.get_absolute_url(),
                    deduplication_key=f"bulk:{operation_key}:{report.pk}",
                )
            if reports:
                record_contact_event(
                    actor=administrator,
                    event_type=ContactAuditLog.EventType.BULK_REPORT_ACTION,
                    item_report=reports[0],
                    description="An administrator applied a bulk report action.",
                )
        missing_count = len(reports) - len(locked_reports)
        if missing_count:
            result.skipped_count += missing_count
            result.skipped_reasons.append("Some selected reports were not found.")
        return result

    @staticmethod
    def _apply_one(report, action, administrator):
        now = timezone.now()
        if report.is_deleted:
            return "Already deleted reports were skipped."
        if action == "mark_reviewed":
            if report.is_reviewed:
                return "Already reviewed reports were skipped."
            report.is_reviewed = True
            report.reviewed_at = now
            report.reviewed_by = administrator
            report.save(update_fields=["is_reviewed", "reviewed_at", "reviewed_by", "updated_at"])
        elif action == "mark_active":
            if report.status == ItemReport.Status.ACTIVE:
                return "Already active reports were skipped."
            report.status = ItemReport.Status.ACTIVE
            report.save(update_fields=["status", "updated_at"])
        elif action == "mark_resolved":
            if report.status == ItemReport.Status.RESOLVED:
                return "Already resolved reports were skipped."
            report.status = ItemReport.Status.RESOLVED
            report.save(update_fields=["status", "updated_at"])
        elif action == "close":
            if report.status == ItemReport.Status.CLOSED:
                return "Already closed reports were skipped."
            report.status = ItemReport.Status.CLOSED
            report.save(update_fields=["status", "updated_at"])
        elif action == "hide":
            if report.is_hidden:
                return "Already hidden reports were skipped."
            report.is_hidden = True
            report.save(update_fields=["is_hidden", "updated_at"])
        elif action == "delete":
            report.is_deleted = True
            report.is_hidden = True
            report.deleted_at = now
            report.deleted_by = administrator
            report.save(
                update_fields=["is_deleted", "is_hidden", "deleted_at", "deleted_by", "updated_at"]
            )
        return None
