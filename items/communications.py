from dataclasses import dataclass

from .models import ContactAuditLog, ContactRequest, UserProfile


@dataclass(frozen=True)
class PhoneNumberAccess:
    display_number: str
    dial_number: str | None
    is_masked: bool


def mask_phone_number(phone_number):
    digits = "".join(character for character in phone_number if character.isdigit())
    if not digits:
        return ""
    visible_digits = digits[-4:]
    return f"••••••{visible_digits}"


def record_contact_event(
    *, actor, event_type, item_report, contact_request=None, conversation=None, description
):
    """Write an audit event using only fixed, non-sensitive descriptive text."""
    return ContactAuditLog.objects.create(
        acting_user=actor if getattr(actor, "is_authenticated", False) else None,
        event_type=event_type,
        item_report=item_report,
        contact_request=contact_request,
        conversation=conversation,
        description=description,
    )


def phone_number_access(*, phone_owner, viewer, contact_request, conversation):
    profile, _ = UserProfile.objects.get_or_create(user=phone_owner)
    permitted_viewer = viewer.is_staff or viewer.pk in (
        conversation.first_participant_id,
        conversation.second_participant_id,
    )
    if (
        conversation.is_active
        and conversation.status == conversation.DealStatus.ACTIVE
        and permitted_viewer
        and profile.consent_to_share_phone
        and profile.phone_number
    ):
        may_view_unmasked = (
            viewer.pk == phone_owner.pk
            or viewer.has_perm("items.view_unmasked_phone_numbers")
            or not profile.mask_phone_number
        )
        if may_view_unmasked:
            return PhoneNumberAccess(
                display_number=profile.phone_number,
                dial_number=profile.phone_number,
                is_masked=False,
            )
        return PhoneNumberAccess(
            display_number=mask_phone_number(profile.phone_number),
            dial_number=None,
            is_masked=True,
        )
    return None


def visible_phone_number(*, phone_owner, viewer, contact_request, conversation):
    """Compatibility wrapper returning only the safe display value."""
    access = phone_number_access(
        phone_owner=phone_owner,
        viewer=viewer,
        contact_request=contact_request,
        conversation=conversation,
    )
    return access.display_number if access else None
