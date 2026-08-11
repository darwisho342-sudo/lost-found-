from django.db import migrations


CAPABILITIES = (
    ("report_summarization", "Report summarization", "Summarize selected reports without private contact information.", "low", True),
    ("conversation_summarization", "Conversation summarization", "Summarize an authorized conversation with private details redacted.", "high", False),
    ("data_extraction", "Data extraction", "Suggest structured item details without modifying a report.", "medium", True),
    ("content_generation", "Content generation", "Draft administrator notices, descriptions, and replies for review.", "medium", True),
    ("user_support_hints", "User-support hints", "Explain workflows and suggest safe support steps.", "low", True),
    ("risk_violation_checks", "Risk and violation checks", "Run deterministic moderation checks and recommend human review.", "high", False),
    ("matching_insights", "Matching insights", "Explain the deterministic report match score.", "medium", True),
    ("analytics_insights", "Analytics insights", "Summarize aggregated report activity and resolution trends.", "low", True),
)


def seed_ai_configuration(apps, schema_editor):
    Capability = apps.get_model("items", "AICapability")
    CapabilitySetting = apps.get_model("items", "AICapabilitySetting")
    AssistantSettings = apps.get_model("items", "AIAssistantSettings")
    AssistantSettings.objects.get_or_create(
        pk=1,
        defaults={
            "is_enabled": False,
            "provider_name": "Local deterministic provider",
            "model_name": "findmatch-local-v1",
            "request_timeout_seconds": 15,
            "maximum_input_length": 5000,
        },
    )
    for display_order, (code, name, description, risk_level, enabled_by_default) in enumerate(CAPABILITIES, 1):
        capability, _ = Capability.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "risk_level": risk_level,
                "enabled_by_default": enabled_by_default,
                "is_available": True,
                "display_order": display_order,
            },
        )
        CapabilitySetting.objects.get_or_create(
            capability=capability,
            defaults={"is_enabled": enabled_by_default},
        )


class Migration(migrations.Migration):
    dependencies = [("items", "0005_aicapability_aiassistantsettings_and_more")]

    operations = [migrations.RunPython(seed_ai_configuration, migrations.RunPython.noop)]
