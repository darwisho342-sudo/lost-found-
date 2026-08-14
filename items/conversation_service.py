from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext as _

from .communications import record_contact_event
from .models import (
    ContactAuditLog,
    ContactRequest,
    Conversation,
    ItemReport,
    Message,
    Notification,
    UserBlock,
)
from .notification_service import NotificationService


class ConversationInitiationService:
    @staticmethod
    def existing_conversation(*, item_report, first_user, second_user):
        return Conversation.objects.filter(item_report=item_report).filter(
            Q(first_participant=first_user, second_participant=second_user)
            | Q(first_participant=second_user, second_participant=first_user)
        ).first()

    @classmethod
    def start(
        cls,
        *,
        item_report,
        initiating_user,
        initial_message,
        actor=None,
        contact_request=None,
    ):
        actor = actor or initiating_user
        if not initiating_user.is_authenticated:
            raise PermissionDenied
        with transaction.atomic():
            report = ItemReport.objects.select_for_update().select_related("owner").get(
                pk=item_report.pk
            )
            if report.is_deleted or report.is_hidden or report.status == ItemReport.Status.CLOSED:
                raise ValidationError(_("This report is not available for a new conversation."))
            if initiating_user.pk == report.owner_id:
                raise PermissionDenied(_("You cannot start a conversation with yourself."))
            if UserBlock.objects.filter(
                blocker=report.owner, blocked_user=initiating_user
            ).exists():
                raise PermissionDenied(_("The report owner is not accepting messages from this account."))

            existing = cls.existing_conversation(
                item_report=report,
                first_user=initiating_user,
                second_user=report.owner,
            )
            if existing:
                return existing, False

            created_request = contact_request is None
            if created_request:
                request_type = (
                    ContactRequest.RequestType.OWNERSHIP_CLAIM
                    if report.report_type == ItemReport.ReportType.FOUND
                    else ContactRequest.RequestType.FOUND_ITEM
                )
                contact_request = ContactRequest.objects.create(
                    item_report=report,
                    requesting_user=initiating_user,
                    receiving_user=report.owner,
                    request_type=request_type,
                    initial_message=initial_message,
                    private_details="",
                    status=ContactRequest.Status.INITIATED,
                )
            else:
                contact_request.status = ContactRequest.Status.INITIATED
                contact_request.save(update_fields=["status"])

            try:
                with transaction.atomic():
                    conversation = Conversation.objects.create(
                        item_report=report,
                        approved_contact_request=contact_request,
                        first_participant=initiating_user,
                        second_participant=report.owner,
                        status=Conversation.DealStatus.ACTIVE,
                        is_active=True,
                    )
            except IntegrityError:
                existing = cls.existing_conversation(
                    item_report=report,
                    first_user=initiating_user,
                    second_user=report.owner,
                )
                if existing:
                    if created_request:
                        contact_request.delete()
                    return existing, False
                raise

            message = Message(
                conversation=conversation,
                sender=initiating_user,
                body=initial_message.strip(),
            )
            message.full_clean()
            message.save()
            conversation.last_message_at = message.sent_at
            conversation.save(update_fields=["last_message_at"])

            recipient = report.owner if actor.pk == initiating_user.pk else initiating_user
            NotificationService.create(
                recipient=recipient,
                notification_type=Notification.NotificationType.NEW_MESSAGE,
                title=_("New private conversation"),
                safe_message=_("A private conversation was started about ‘%(title)s’.") % {"title": report.title},
                conversation=conversation,
                item_report=report,
                destination_url=reverse("conversation_detail", args=[conversation.pk]),
                deduplication_key=f"conversation-started:{conversation.pk}:{recipient.pk}",
            )
            record_contact_event(
                actor=actor,
                event_type=ContactAuditLog.EventType.CONVERSATION_OPENED,
                item_report=report,
                contact_request=contact_request,
                conversation=conversation,
                description=_("A private conversation was started directly from an item report."),
            )
            return conversation, True
