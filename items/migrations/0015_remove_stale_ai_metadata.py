from django.db import migrations


AI_MODEL_NAMES = (
    "aiassistantsettings",
    "aicapability",
    "aicapabilityauditlog",
    "aicapabilitysetting",
    "admincapabilityoverride",
)


def remove_stale_ai_metadata(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    content_types = ContentType.objects.filter(app_label="items", model__in=AI_MODEL_NAMES)
    Permission.objects.filter(content_type__in=content_types).delete()
    Permission.objects.filter(content_type__app_label="items", codename="manage_ai_assistant").delete()
    content_types.delete()


class Migration(migrations.Migration):
    dependencies = [("items", "0014_remove_admincapabilityoverride_unique_ai_capability_override_and_more")]
    operations = [migrations.RunPython(remove_stale_ai_metadata, migrations.RunPython.noop)]
