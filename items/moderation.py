import re

from django.core.exceptions import ValidationError


class SensitiveContentModerationService:
    """Small local safety check; private text is never copied into public metadata."""

    @staticmethod
    def clean(value):
        value = (value or "").strip()
        if "\x00" in value:
            raise ValidationError("The text contains unsupported characters.")
        return value


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
