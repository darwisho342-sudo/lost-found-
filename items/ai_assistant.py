import os
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from .moderation import ContentModerationService
from .models import (
    AIAssistantSettings,
    AICapability,
    AICapabilityAuditLog,
    AICapabilitySetting,
    AdminCapabilityOverride,
    Conversation,
    ItemReport,
)
from .services import MatchingService


CAPABILITY_DEFINITIONS = (
    ("report_summarization", "Report summarization", "Summarize selected reports without private contact information.", "low"),
    ("conversation_summarization", "Conversation summarization", "Summarize an authorized conversation with private details redacted.", "high"),
    ("data_extraction", "Data extraction", "Suggest structured item details without modifying a report.", "medium"),
    ("content_generation", "Content generation", "Draft administrator notices, descriptions, and replies for review.", "medium"),
    ("user_support_hints", "User-support hints", "Explain workflows and suggest safe support steps.", "low"),
    ("risk_violation_checks", "Risk and violation checks", "Run deterministic moderation checks and recommend human review.", "high"),
    ("matching_insights", "Matching insights", "Explain the existing deterministic report match score.", "medium"),
    ("analytics_insights", "Analytics insights", "Summarize aggregated report activity and resolution trends.", "low"),
)


class AIProviderConfigurationService:
    """Future providers obtain secrets from the environment, never database fields."""

    @staticmethod
    def api_key(provider_name):
        safe_name = "".join(character if character.isalnum() else "_" for character in provider_name)
        return os.environ.get(f"FINDMATCH_AI_{safe_name.upper()}_API_KEY", "")


@dataclass(frozen=True)
class AssistantResult:
    title: str
    content: str
    disclaimer: str = "This is an advisory result. Review it before taking any action."


class AICapabilityService:
    @staticmethod
    def client_ip(request):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        return forwarded or request.META.get("REMOTE_ADDR") or None

    @classmethod
    def audit(cls, *, user, event_type, description, capability=None, old_value="", new_value="", scope="request", request=None):
        return AICapabilityAuditLog.objects.create(
            acting_administrator=user,
            capability=capability,
            event_type=event_type,
            old_value=str(old_value)[:255],
            new_value=str(new_value)[:255],
            scope=scope[:40],
            safe_description=description[:255],
            ip_address=cls.client_ip(request) if request else None,
        )

    @staticmethod
    def can_manage_global_settings(user):
        return user.is_authenticated and user.is_staff and (
            user.is_superuser or user.has_perm("items.manage_ai_assistant")
        )

    @classmethod
    def is_enabled(cls, user, capability_code, context=None):
        if not user.is_authenticated or not user.is_staff:
            return False
        assistant_settings = AIAssistantSettings.get_solo()
        if not assistant_settings.is_enabled:
            return False
        capability = AICapability.objects.filter(
            code=capability_code, is_available=True
        ).first()
        if capability is None:
            return False
        global_setting = AICapabilitySetting.objects.filter(capability=capability).first()
        if global_setting is None or not global_setting.is_enabled:
            return False
        override = AdminCapabilityOverride.objects.filter(
            administrator=user, capability=capability
        ).first()
        if override and override.setting == AdminCapabilityOverride.OverrideSetting.DISABLED:
            return False
        if context and isinstance(context, Conversation) and not context.can_view(user):
            return False
        return True

    @classmethod
    def enabled_capabilities(cls, user):
        return [
            capability
            for capability in AICapability.objects.filter(is_available=True)
            if cls.is_enabled(user, capability.code)
        ]

    @classmethod
    def update_override(cls, *, user, capability, setting, request=None):
        if not user.is_staff:
            raise PermissionDenied
        if setting == AdminCapabilityOverride.OverrideSetting.ENABLED:
            global_setting = AICapabilitySetting.objects.filter(capability=capability).first()
            if not global_setting or not global_setting.is_enabled:
                raise ValidationError("A personal override cannot enable a globally disabled capability.")
        override, _ = AdminCapabilityOverride.objects.get_or_create(
            administrator=user, capability=capability
        )
        old_value = override.setting
        override.setting = setting
        override.full_clean()
        override.save(update_fields=["setting"])
        cls.audit(
            user=user,
            capability=capability,
            event_type=AICapabilityAuditLog.EventType.OVERRIDE_CHANGED,
            old_value=old_value,
            new_value=setting,
            scope="personal",
            description="An administrator changed a personal AI capability override.",
            request=request,
        )
        return override


class AIAssistantService:
    @classmethod
    def execute(cls, *, user, capability_code, input_text="", reports=(), conversation=None, request=None):
        capability = AICapability.objects.filter(code=capability_code).first()
        if not AICapabilityService.is_enabled(user, capability_code, context=conversation):
            AICapabilityService.audit(
                user=user,
                capability=capability,
                event_type=AICapabilityAuditLog.EventType.REQUEST_BLOCKED,
                description="An AI Assistant request was blocked by configuration or permissions.",
                request=request,
            )
            raise PermissionDenied("This AI Assistant capability is not enabled for your account.")
        assistant_settings = AIAssistantSettings.get_solo()
        cleaned_input = ContentModerationService.redact_private_data(input_text)
        if len(cleaned_input) > assistant_settings.maximum_input_length:
            raise ValidationError(
                f"Input must be {assistant_settings.maximum_input_length} characters or fewer."
            )
        handlers = {
            "report_summarization": cls.report_summary,
            "conversation_summarization": cls.conversation_summary,
            "data_extraction": cls.data_extraction,
            "content_generation": cls.content_generation,
            "user_support_hints": cls.support_hints,
            "risk_violation_checks": cls.risk_check,
            "matching_insights": cls.matching_insights,
            "analytics_insights": cls.analytics_insights,
        }
        try:
            result = handlers[capability_code](
                user=user,
                input_text=cleaned_input,
                reports=list(reports),
                conversation=conversation,
            )
        except (KeyError, ValueError) as exc:
            AICapabilityService.audit(
                user=user,
                capability=capability,
                event_type=AICapabilityAuditLog.EventType.PROVIDER_FAILURE,
                description="The local assistant provider could not complete a request.",
                request=request,
            )
            raise ValidationError(str(exc)) from exc
        AICapabilityService.audit(
            user=user,
            capability=capability,
            event_type=AICapabilityAuditLog.EventType.REQUEST_EXECUTED,
            description="An administrator executed an advisory AI Assistant capability.",
            request=request,
        )
        return result

    @staticmethod
    def report_summary(*, reports, **kwargs):
        if not reports:
            raise ValueError("Select at least one report to summarize.")
        lines = []
        for report in reports[:20]:
            description = ContentModerationService.redact_private_data(report.description)
            lines.append(
                f"{report.title}: {report.get_report_type_display()}, {report.get_category_display()}, "
                f"{report.colour}, {report.get_campus_location_display()}, {report.item_date:%d %b %Y}, "
                f"status {report.get_status_display()}. Description: {description[:240]}"
            )
        return AssistantResult("Report summary", "\n\n".join(lines))

    @staticmethod
    def conversation_summary(*, conversation, user, **kwargs):
        if conversation is None:
            raise ValueError("Select an authorized conversation to summarize.")
        if not conversation.can_view(user):
            raise PermissionDenied
        messages = conversation.messages.filter(is_deleted=False).select_related("sender")[:100]
        safe_messages = [ContentModerationService.redact_private_data(message.body) for message in messages]
        questions = [message for message in safe_messages if "?" in message]
        content = (
            f"Conversation about {conversation.item_report.title}. Current status: "
            f"{conversation.get_status_display()}. {len(safe_messages)} visible message(s) reviewed."
        )
        if questions:
            content += "\n\nUnresolved questions mentioned: " + " | ".join(questions[-3:])[:600]
        else:
            content += "\n\nNo explicit unresolved question was detected. Human review is still required."
        return AssistantResult("Conversation summary", content)

    @staticmethod
    def data_extraction(*, input_text, **kwargs):
        if not input_text:
            raise ValueError("Enter an item description to analyze.")
        lowered = input_text.casefold()
        category = next((label for code, label in ItemReport.Category.choices if code in lowered or label.casefold() in lowered), "Other")
        location = next((label for code, label in ItemReport.CampusLocation.choices if code.replace("_", " ") in lowered or label.casefold() in lowered), "Other")
        colours = [colour for colour in ("black", "white", "blue", "red", "green", "brown", "silver", "gold", "grey", "purple") if colour in lowered]
        report_type = "Lost" if "lost" in lowered else "Found" if "found" in lowered else "Unclear"
        return AssistantResult(
            "Suggested structured details",
            f"Report type: {report_type}\nCategory: {category}\nColour: {', '.join(colours).title() or 'Unclear'}\nLocation: {location}\n\nNothing has been saved or changed.",
        )

    @staticmethod
    def content_generation(*, input_text, **kwargs):
        if not input_text:
            raise ValueError("Enter the facts the draft should cover.")
        return AssistantResult(
            "Draft for administrator review",
            "Hello,\n\nWe are reviewing your FindMatch case. "
            f"Based on the information available: {input_text[:900]}\n\n"
            "Please use the secure FindMatch workflow and do not share passwords, identity numbers, or private contact details.\n\nFindMatch Administration",
            "Draft only. It has not been sent or saved anywhere.",
        )

    @staticmethod
    def support_hints(*, input_text, **kwargs):
        return AssistantResult(
            "User-support hints",
            "1. Confirm which public report or private conversation the user means.\n"
            "2. Keep contact and ownership evidence inside the private conversation workflow.\n"
            "3. Explain that match scores are suggestions, not proof of ownership.\n"
            "4. Escalate disputed ownership, threats, or sensitive-data exposure for human review.\n"
            f"5. Case note considered: {input_text[:500] or 'No additional case note provided.'}",
        )

    @staticmethod
    def risk_check(*, input_text, reports, conversation, user, **kwargs):
        sources = [input_text]
        sources.extend(report.description for report in reports)
        if conversation:
            sources.extend(
                conversation.messages.filter(is_deleted=False)
                .values_list("body", flat=True)[:100]
            )
        if not any(sources):
            raise ValueError("Enter text or select content to check.")
        analysis = ContentModerationService.analyze("\n".join(sources))
        categories = "\n".join(f"- {category}" for category in analysis["categories"]) or "- None detected"
        return AssistantResult(
            "Risk and violation check",
            f"Detected categories:\n{categories}\n\nRecommended action: {analysis['recommended_action']}",
            "This check does not replace the normal moderation workflow or administrator judgment.",
        )

    @staticmethod
    def matching_insights(*, reports, **kwargs):
        if len(reports) != 2:
            raise ValueError("Select exactly two reports for matching insights.")
        match = MatchingService.compare(reports[0], reports[1])
        return AssistantResult(
            f"Matching insight: {match.total_score}/100",
            f"Category: {match.category_points}/25\nDescription: {match.description_points}/25\n"
            f"Colour: {match.colour_points}/20\nLocation: {match.location_points}/15\n"
            f"Date proximity: {match.date_points}/15",
            "A match score is only a suggestion and never proves ownership.",
        )

    @staticmethod
    def analytics_insights(**kwargs):
        reports = ItemReport.objects.filter(is_deleted=False)
        since = timezone.now() - timedelta(days=30)
        recent = reports.filter(created_at__gte=since)
        category = recent.values("category").annotate(total=Count("id")).order_by("-total").first()
        total = reports.count()
        resolved = reports.filter(status=ItemReport.Status.RESOLVED).count()
        rate = round((resolved / total) * 100) if total else 0
        popular = dict(ItemReport.Category.choices).get(category["category"], "No category") if category else "No category"
        return AssistantResult(
            "Aggregated platform insights",
            f"Total current reports: {total}\nReports created in the last 30 days: {recent.count()}\n"
            f"Resolved reports: {resolved} ({rate}%)\nMost common recent category: {popular}",
            "These statistics are aggregated and contain no private user information.",
        )
