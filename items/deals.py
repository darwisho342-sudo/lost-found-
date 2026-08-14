from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .communications import record_contact_event
from .models import ContactAuditLog, ContactRequest, Conversation, ItemReport, Notification
from .notification_service import NotificationService


class DealService:
    @staticmethod
    def receiving_participant(conversation):
        if conversation.item_report.report_type == ItemReport.ReportType.LOST:
            return conversation.item_report.owner
        return conversation.approved_contact_request.requesting_user

    @classmethod
    def complete(cls, *, conversation, acting_user, allow_staff=False):
        with transaction.atomic():
            conversation = Conversation.objects.select_for_update().select_related(
                "item_report", "approved_contact_request", "first_participant", "second_participant"
            ).get(pk=conversation.pk)
            receiver = cls.receiving_participant(conversation)
            authorized = acting_user == receiver or (allow_staff and acting_user.is_staff)
            if not authorized:
                raise PermissionDenied(_("Only the receiving participant can complete this deal."))
            if conversation.status == Conversation.DealStatus.COMPLETED:
                return conversation, False
            if not conversation.is_active or conversation.status not in (
                Conversation.DealStatus.ACTIVE,
            ):
                raise ValidationError(_("This conversation cannot be completed."))
            now = timezone.now()
            conversation.status = Conversation.DealStatus.COMPLETED
            conversation.completed_at = now
            conversation.completed_by = acting_user
            conversation.is_active = False
            conversation.save(
                update_fields=["status", "completed_at", "completed_by", "is_active"]
            )
            report = ItemReport.objects.select_for_update().get(pk=conversation.item_report_id)
            report.status = ItemReport.Status.RESOLVED
            report.save(update_fields=["status", "updated_at"])
            other_pending = ContactRequest.objects.filter(
                item_report=report, status=ContactRequest.Status.PENDING
            ).exclude(pk=conversation.approved_contact_request_id)
            pending_requesters = list(other_pending.values_list("requesting_user_id", "pk"))
            other_pending.update(status=ContactRequest.Status.CANCELLED, reviewed_at=now)
            Notification.objects.filter(conversation=conversation, is_read=False).update(
                is_read=True, read_at=now
            )
            destination = reverse("conversation_detail", args=[conversation.pk])
            for participant in (conversation.first_participant, conversation.second_participant):
                NotificationService.create(
                    recipient=participant,
                    notification_type=Notification.NotificationType.DEAL_COMPLETED,
                    title=_("Deal completed"),
                    safe_message=_("The item ‘%(title)s’ has been marked as returned.") % {"title": report.title},
                    conversation=conversation,
                    item_report=report,
                    destination_url=destination,
                    deduplication_key=f"deal-completed:{conversation.pk}:{participant.pk}",
                )
            for requester_id, request_id in pending_requesters:
                NotificationService.create(
                    recipient_id=requester_id,
                    notification_type=Notification.NotificationType.ADMIN_NOTICE,
                    title=_("Conversation initiation closed"),
                    safe_message=_("Another return was completed for ‘%(title)s’.") % {"title": report.title},
                    item_report=report,
                    destination_url=reverse("contact_request_detail", args=[request_id]),
                    deduplication_key=f"deal-pending-closed:{conversation.pk}:{request_id}",
                )
            record_contact_event(
                actor=acting_user,
                event_type=ContactAuditLog.EventType.DEAL_COMPLETED,
                item_report=report,
                contact_request=conversation.approved_contact_request,
                conversation=conversation,
                description=_("An item return was completed."),
            )
            return conversation, True

    @staticmethod
    def reopen(*, conversation, administrator, reason, change_report_status=False):
        if not administrator.is_staff:
            raise PermissionDenied
        if not reason.strip():
            raise ValidationError(_("Enter an administrator reason."))
        with transaction.atomic():
            conversation = Conversation.objects.select_for_update().select_related(
                "item_report", "approved_contact_request", "first_participant", "second_participant"
            ).get(pk=conversation.pk)
            if conversation.status not in (
                Conversation.DealStatus.COMPLETED,
                Conversation.DealStatus.DEACTIVATED,
            ):
                raise ValidationError(_("Only completed or deactivated conversations can be reactivated."))
            now = timezone.now()
            conversation.status = Conversation.DealStatus.ACTIVE
            conversation.is_active = True
            conversation.deactivated_at = None
            conversation.deactivated_by = None
            conversation.deactivation_reason = ""
            conversation.reopened_at = now
            conversation.reopened_by = administrator
            conversation.save(
                update_fields=[
                    "status", "is_active", "reopened_at", "reopened_by",
                    "deactivated_at", "deactivated_by", "deactivation_reason",
                ]
            )
            if change_report_status:
                report = conversation.item_report
                report.status = ItemReport.Status.ACTIVE
                report.save(update_fields=["status", "updated_at"])
            destination = reverse("conversation_detail", args=[conversation.pk])
            reopen_key = now.isoformat()
            for participant in (conversation.first_participant, conversation.second_participant):
                NotificationService.create(
                    recipient=participant,
                    notification_type=Notification.NotificationType.CONVERSATION_REOPENED,
                    title=_("Conversation reopened"),
                    safe_message=_("An administrator reopened the conversation about ‘%(title)s’.") % {"title": conversation.item_report.title},
                    conversation=conversation,
                    item_report=conversation.item_report,
                    destination_url=destination,
                    deduplication_key=f"conversation-reopened:{conversation.pk}:{participant.pk}:{reopen_key}",
                )
            record_contact_event(
                actor=administrator,
                event_type=ContactAuditLog.EventType.CONVERSATION_REOPENED,
                item_report=conversation.item_report,
                contact_request=conversation.approved_contact_request,
                conversation=conversation,
                description=_("An administrator reopened a conversation after recording a private reason."),
            )
            return conversation
