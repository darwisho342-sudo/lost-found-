import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class SensitiveContentModerationService:
    """Small local safety check; private text is never copied into public metadata."""

    @staticmethod
    def clean(value):
        value = (value or "").strip()
        if "\x00" in value:
            raise ValidationError("The text contains unsupported characters.")
        return value

    CARD_NUMBER = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
    SECURITY_CODE = re.compile(r"(?i)\b(?:cvv|cvc|security\s*code|pin|password|passcode|otp|authentication\s*code)\b\s*[:=#-]?\s*\S+")
    NATIONAL_ID = re.compile(r"(?i)\b(?:national\s*id|identity\s*number|kimlik\s*no|tc\s*no)\b\s*[:=#-]?\s*[A-Z0-9-]{5,}")
    PRIVATE_CONTACT = re.compile(
        r"(?ix)(?:\b[\w.+-]+@[\w.-]+\.[A-Z]{2,}\b|(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w))"
    )
    PRIVATE_OWNERSHIP_DETAIL = re.compile(
        r"(?i)\b(?:serial\s*(?:number|no\.?|#)|hidden\s+mark|exact\s+contents?|"
        r"contents?\s+(?:are|include|inside)|ownership\s+(?:proof|detail)|"
        r"full\s+(?:id|card|identity)\s*(?:number|no\.?|#))\b"
    )

    @classmethod
    def reject_public_sensitive_content(cls, value):
        text = cls.clean(value)
        if cls.CARD_NUMBER.search(text) or cls.SECURITY_CODE.search(text) or cls.NATIONAL_ID.search(text):
            raise ValidationError(_("Please remove private or sensitive information before submitting this report."))
        return text

    @classmethod
    def reject_forbidden_secret(cls, value):
        text = cls.clean(value)
        if cls.CARD_NUMBER.search(text) or cls.SECURITY_CODE.search(text) or cls.NATIONAL_ID.search(text):
            raise ValidationError(_("Do not include complete passwords, PINs, card numbers, security codes, or identification numbers."))
        return text

    @classmethod
    def reject_found_public_identifying_content(cls, value):
        """Keep ownership evidence and contact details out of public Found text."""
        text = cls.reject_public_sensitive_content(value)
        if cls.PRIVATE_CONTACT.search(text) or cls.PRIVATE_OWNERSHIP_DETAIL.search(text):
            raise ValidationError(_(
                "Move serial numbers, hidden marks, exact contents, ownership evidence, and contact details to the private verification fields."
            ))
        return text


class ContentModerationService:
    """Deterministic local review hints; it never changes or removes content."""

    EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
    PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
    SENSITIVE_EVIDENCE_PATTERN = re.compile(
        r"(?i)\b(?:password|pin(?:\s+code)?|student\s+id|serial\s+number)\b\s*[:#=-]?\s*\S+"
    )
    HARMFUL_TERMS = {"threat", "kill", "attack", "hate"}
    OWNERSHIP_TERMS = {"student id", "serial number", "pin code", "password"}

    @classmethod
    def analyze(cls, value):
        text = SensitiveContentModerationService.clean(value)
        lowered = text.casefold()
        categories = []
        if cls.EMAIL_PATTERN.search(text) or cls.PHONE_PATTERN.search(text):
            categories.append("Possible private contact information")
        if any(term in lowered for term in cls.HARMFUL_TERMS):
            categories.append("Potentially abusive or threatening language")
        if any(term in lowered for term in cls.OWNERSHIP_TERMS):
            categories.append("Potentially sensitive ownership evidence")
        return {
            "categories": categories,
            "recommended_action": (
                "Escalate to a human moderator before taking action."
                if categories
                else "No configured warning category was detected; routine human review still applies."
            ),
        }

    @classmethod
    def redact_private_data(cls, value):
        text = SensitiveContentModerationService.clean(value)
        text = cls.EMAIL_PATTERN.sub("[email removed]", text)
        text = cls.PHONE_PATTERN.sub("[phone removed]", text)
        return cls.SENSITIVE_EVIDENCE_PATTERN.sub("[sensitive detail removed]", text)
