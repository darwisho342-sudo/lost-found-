"""Transactional ownership-claim workflow and permission boundary."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from .communications import record_contact_event
from .conversation_service import ConversationInitiationService
from .models import ContactAuditLog, ContactRequest, HandoverConfirmation, ItemReport, Notification
from .notification_service import NotificationService


class OwnershipVerificationService:
    maximum_attempts = 3
    attempt_window = timedelta(days=30)

    @classmethod
    def validate_new_claim(cls, *, report, claimant):
        if report.report_type != ItemReport.ReportType.FOUND:
            raise ValidationError(_("Ownership verification is available only for Found reports."))
        if claimant.pk == report.owner_id:
            raise PermissionDenied(_("You cannot claim your own report."))
        if not claimant.is_active:
            raise PermissionDenied(_("This account cannot submit claims."))
        profile = getattr(claimant, "profile", None)
        if not profile or not profile.email_verified_at:
            raise PermissionDenied(_("Verify your email address before submitting an ownership claim."))
        if report.is_hidden or report.is_deleted or report.status not in (ItemReport.Status.ACTIVE, ItemReport.Status.POSSIBLE_MATCH):
            raise ValidationError(_("This item is not available for claims."))
        if ContactRequest.objects.filter(item_report=report, requesting_user=claimant, status__in=(ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION, ContactRequest.Status.APPROVED)).exists():
            raise ValidationError(_("You already have an active claim for this item."))
        recent_attempts = ContactRequest.objects.filter(
            item_report=report, requesting_user=claimant,
            requested_at__gte=timezone.now() - cls.attempt_window,
        ).count()
        if recent_attempts >= cls.maximum_attempts:
            raise ValidationError(_("You have reached the claim-attempt limit for this item."))
        return recent_attempts + 1

    @classmethod
    def submit(cls, *, report, claimant, form):
        with transaction.atomic():
            report = ItemReport.objects.select_for_update().select_related("owner").get(pk=report.pk)
            attempt = cls.validate_new_claim(report=report, claimant=claimant)
            claim = form.save(commit=False)
            claim.item_report = report
            claim.requesting_user = claimant
            claim.receiving_user = report.owner
            claim.request_type = ContactRequest.RequestType.OWNERSHIP_CLAIM
            claim.status = ContactRequest.Status.PENDING
            claim.private_details = ""
            claim.attempt_number = attempt
            claim.full_clean()
            claim.save()
            for question in report.verification_questions.all():
                claim.answers.create(question=question, answer=form.cleaned_data[f"question_{question.pk}"])
            if form.cleaned_data.get("evidence"):
                claim.evidence_files.create(file=form.cleaned_data["evidence"])
            cls.audit(claim, claimant, ContactAuditLog.EventType.REQUEST_CREATED, _("An ownership claim was submitted."))
            cls.notify(claim, report.owner, _("New ownership claim"), _("A private ownership claim requires your review."), "claim-submitted")
            return claim

    @classmethod
    def change_status(cls, *, claim, actor, action, clarification=""):
        if action == "dispute":
            if actor.pk != claim.requesting_user_id and not actor.is_staff:
                raise PermissionDenied
        elif actor.pk != claim.receiving_user_id and not actor.is_staff:
            raise PermissionDenied
        transitions = {
            "request_more": ((ContactRequest.Status.PENDING,), ContactRequest.Status.MORE_INFORMATION, ContactAuditLog.EventType.REQUEST_MORE_INFORMATION),
            "approve": ((ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION), ContactRequest.Status.APPROVED, ContactAuditLog.EventType.REQUEST_APPROVED),
            "reject": ((ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION), ContactRequest.Status.REJECTED, ContactAuditLog.EventType.REQUEST_DENIED),
            "dispute": ((ContactRequest.Status.REJECTED,), ContactRequest.Status.DISPUTED, ContactAuditLog.EventType.CLAIM_DISPUTED),
        }
        if action not in transitions:
            raise ValidationError(_("Unsupported claim action."))
        allowed, new_status, event_type = transitions[action]
        with transaction.atomic():
            claim = ContactRequest.objects.select_for_update().select_related("item_report", "requesting_user", "receiving_user").get(pk=claim.pk)
            if claim.status not in allowed:
                raise ValidationError(_("This claim can no longer be changed using that action."))
            if action == "request_more":
                if not clarification.strip():
                    raise ValidationError(_("Enter one clarification request."))
                if claim.clarification_request:
                    raise ValidationError(_("Only one clarification request is allowed."))
                claim.clarification_request = clarification.strip()
            claim.status = new_status
            claim.reviewed_at = timezone.now()
            claim.reviewed_by = actor
            claim.save(update_fields=("status", "clarification_request", "reviewed_at", "reviewed_by"))
            conversation = None
            if action == "approve":
                conversation, created = ConversationInitiationService.start(
                    item_report=claim.item_report, initiating_user=claim.requesting_user,
                    initial_message=claim.initial_message, actor=actor, contact_request=claim,
                )
                # start() uses the legacy initiated state; ownership approval remains explicit.
                claim.status = ContactRequest.Status.APPROVED
                claim.save(update_fields=("status",))
                report = ItemReport.objects.select_for_update().get(pk=claim.item_report_id)
                report.status = ItemReport.Status.CLAIM_IN_PROGRESS
                report.save(update_fields=("status", "updated_at"))
            cls.audit(claim, actor, event_type, {
                "request_more": _("More ownership information was requested."),
                "approve": _("An ownership claim was approved."),
                "reject": _("An ownership claim was rejected."),
                "dispute": _("An ownership claim was disputed."),
            }[action])
            cls.notify(claim, claim.requesting_user, _("Ownership claim updated"), _("Your ownership claim status changed. Open FindMatch to review it."), f"claim-{action}")
            return claim, conversation

    @staticmethod
    def audit(claim, actor, event_type, description):
        record_contact_event(actor=actor, event_type=event_type, item_report=claim.item_report,
            contact_request=claim, description=description)

    @staticmethod
    def notify(claim, recipient, title, message, key):
        NotificationService.create(recipient=recipient, notification_type=Notification.NotificationType.ADMIN_NOTICE,
            title=title, safe_message=message, item_report=claim.item_report,
            destination_url=reverse("contact_request_detail", args=(claim.pk,)),
            deduplication_key=f"{key}:{claim.pk}:{recipient.pk}:{claim.status}")

    @classmethod
    def confirm_handover(cls, *, claim, user):
        if claim.status != ContactRequest.Status.APPROVED or user.pk not in (claim.requesting_user_id, claim.receiving_user_id):
            raise PermissionDenied
        with transaction.atomic():
            claim = ContactRequest.objects.select_for_update().select_related("item_report", "requesting_user", "receiving_user").get(pk=claim.pk)
            HandoverConfirmation.objects.get_or_create(contact_request=claim, user=user)
            if claim.handover_confirmations.count() < 2:
                return False
            claim.status = ContactRequest.Status.COMPLETED
            claim.reviewed_at = timezone.now()
            claim.save(update_fields=("status", "reviewed_at"))
            report = ItemReport.objects.select_for_update().get(pk=claim.item_report_id)
            report.status = ItemReport.Status.RESOLVED
            report.is_hidden = bool(report.require_official_handover)
            report.save(update_fields=("status", "is_hidden", "updated_at"))
            ContactRequest.objects.filter(item_report=report, status__in=(ContactRequest.Status.PENDING, ContactRequest.Status.MORE_INFORMATION)).exclude(pk=claim.pk).update(status=ContactRequest.Status.REJECTED, reviewed_at=timezone.now())
            if hasattr(claim, "conversation"):
                conversation = claim.conversation
                conversation.status = conversation.DealStatus.COMPLETED
                conversation.is_active = False
                conversation.completed_at = timezone.now()
                conversation.completed_by = user
                conversation.save(update_fields=("status", "is_active", "completed_at", "completed_by"))
            cls.audit(claim, user, ContactAuditLog.EventType.DEAL_COMPLETED, _("Both participants confirmed the item handover."))
            return True
