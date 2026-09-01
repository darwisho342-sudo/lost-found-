"""Transactional return and delivery workflow with private-data boundaries."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .communications import record_contact_event
from .models import ContactAuditLog, ContactRequest, ItemReport, Notification, ReturnArrangement
from .notification_service import NotificationService


class ReturnWorkflowService:
    participant_statuses = {
        "arranging", "ready_pickup", "sent", "handed_over", "awaiting_receipt",
        "received", "failed_delivery", "disputed",
    }

    @classmethod
    def validate_access(cls, *, claim, user):
        if user.pk not in (claim.requesting_user_id, claim.receiving_user_id) and not user.is_staff:
            raise PermissionDenied
        if claim.status not in (
            ContactRequest.Status.APPROVED,
            ContactRequest.Status.RETURN_IN_PROGRESS,
            ContactRequest.Status.COMPLETED,
        ):
            raise ValidationError(_("A return can be arranged only after a claim is approved."))

    @classmethod
    def get_or_create(cls, *, claim, user):
        cls.validate_access(claim=claim, user=user)
        if claim.status == ContactRequest.Status.COMPLETED:
            raise PermissionDenied(_("A completed return is read-only."))
        arrangement, _ = ReturnArrangement.objects.get_or_create(contact_request=claim)
        return arrangement

    @classmethod
    def update(cls, *, arrangement, user, form):
        with transaction.atomic():
            arrangement = ReturnArrangement.objects.select_for_update().select_related(
                "contact_request__item_report", "contact_request__requesting_user", "contact_request__receiving_user"
            ).get(pk=arrangement.pk)
            if not arrangement.can_view(user):
                raise PermissionDenied
            updated = form.save(commit=False)
            if form.cleaned_data.get("delivery_address") and form.cleaned_data.get("share_delivery_address"):
                updated.address_shared_by = user
                updated.address_consent_at = updated.address_consent_at or timezone.now()
                updated.address_consent_withdrawn_at = None
            elif arrangement.delivery_address and not form.cleaned_data.get("share_delivery_address"):
                updated.delivery_address = ""
                updated.address_consent_withdrawn_at = timezone.now()
                updated.tracking_reference = ""
            updated.delivery_details_retention_expires_at = timezone.now() + timedelta(days=90)
            updated.full_clean()
            updated.save()
            claim = updated.contact_request
            if claim.status == ContactRequest.Status.APPROVED:
                claim.status = ContactRequest.Status.RETURN_IN_PROGRESS
                claim.save(update_fields=("status",))
            report = claim.item_report
            if report.status in (ItemReport.Status.ACTIVE, ItemReport.Status.CLAIM_IN_PROGRESS):
                report.status = ItemReport.Status.RETURN_ARRANGED
                report.save(update_fields=("status", "updated_at"))
            cls._notify(updated, user)
            record_contact_event(
                actor=user, event_type=ContactAuditLog.EventType.RETURN_UPDATED,
                item_report=report, contact_request=claim,
                conversation=getattr(claim, "conversation", None),
                description=_("The return arrangement status was updated."),
            )
            return updated

    @classmethod
    def confirm(cls, *, arrangement, user, role):
        with transaction.atomic():
            arrangement = ReturnArrangement.objects.select_for_update().select_related(
                "contact_request__item_report", "contact_request__requesting_user", "contact_request__receiving_user",
                "contact_request__conversation",
            ).get(pk=arrangement.pk)
            claim = arrangement.contact_request
            if user.pk not in (claim.requesting_user_id, claim.receiving_user_id):
                raise PermissionDenied
            now = timezone.now()
            if role == "finder" and user.pk == claim.receiving_user_id:
                arrangement.finder_confirmed_at = arrangement.finder_confirmed_at or now
                arrangement.status = "handed_over"
            elif role == "owner" and user.pk == claim.requesting_user_id:
                arrangement.owner_confirmed_at = arrangement.owner_confirmed_at or now
                arrangement.status = "received"
            else:
                raise PermissionDenied
            arrangement.save(update_fields=("finder_confirmed_at", "owner_confirmed_at", "status", "updated_at"))
            if (arrangement.finder_confirmed_at and arrangement.owner_confirmed_at
                    and claim.item_report.scope == ItemReport.Scope.INTERNATIONAL):
                claim.status = ContactRequest.Status.COMPLETED
                claim.reviewed_at = now
                claim.save(update_fields=("status", "reviewed_at"))
                report = ItemReport.objects.select_for_update().get(pk=claim.item_report_id)
                report.status = ItemReport.Status.RESOLVED
                report.save(update_fields=("status", "updated_at"))
                ContactRequest.objects.filter(
                    item_report=report,
                    status__in=(ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION),
                ).exclude(pk=claim.pk).update(status=ContactRequest.Status.CANCELLED, reviewed_at=now)
                conversation = claim.conversation
                conversation.status = conversation.DealStatus.COMPLETED
                conversation.is_active = False
                conversation.completed_at = now
                conversation.completed_by = user
                conversation.save(update_fields=("status", "is_active", "completed_at", "completed_by"))
            cls._notify(arrangement, user)
            return arrangement

    @staticmethod
    def _notify(arrangement, actor):
        claim = arrangement.contact_request
        recipient = claim.receiving_user if actor.pk == claim.requesting_user_id else claim.requesting_user
        NotificationService.create(
            recipient=recipient, notification_type=Notification.NotificationType.RETURN_UPDATED,
            title=_("Return arrangement updated"),
            safe_message=_("The return status changed. Open the private return page for details."),
            item_report=claim.item_report,
            conversation=getattr(claim, "conversation", None),
            destination_url=reverse("return_arrangement", args=(claim.pk,)),
            deduplication_key=f"return:{arrangement.pk}:{arrangement.status}:{recipient.pk}",
        )

    @staticmethod
    def purge_expired_private_delivery_data(now=None):
        now = now or timezone.now()
        return ReturnArrangement.objects.filter(
            delivery_details_retention_expires_at__lt=now, legal_or_safety_hold=False,
        ).exclude(delivery_address="", tracking_reference="").update(
            delivery_address="", tracking_reference="", courier_name="", address_consent_withdrawn_at=now,
        )
