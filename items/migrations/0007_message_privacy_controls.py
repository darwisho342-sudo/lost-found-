import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("items", "0006_seed_ai_capabilities"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="hide_approved_confirmed_messages",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Hide approved and confirmed messages from the normal conversation "
                    "view, except messages marked as important context."
                ),
            ),
        ),
        migrations.AddField(
            model_name="userprofile",
            name="mask_phone_number",
            field=models.BooleanField(
                default=True,
                help_text="Show approved contacts only the final four digits of your phone number.",
            ),
        ),
        migrations.AlterModelOptions(
            name="userprofile",
            options={
                "permissions": (
                    (
                        "view_unmasked_phone_numbers",
                        "Can view unmasked approved phone numbers",
                    ),
                ),
            },
        ),
        migrations.AddField(
            model_name="message",
            name="hidden_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="hidden_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="hidden_contact_messages",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="is_hidden",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AddField(
            model_name="message",
            name="is_important_context",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Keep this message visible when it explains an important deal-status change."
                ),
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="retention_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="message",
            name="review_status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("approved", "Approved"),
                    ("confirmed", "Confirmed"),
                    ("rejected", "Rejected"),
                    ("quarantined", "Quarantined"),
                ],
                db_index=True,
                default="pending",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="message",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("participants", "Participants"),
                    ("administrator_only", "Administrator Only"),
                    ("hidden", "Hidden"),
                ],
                db_index=True,
                default="participants",
                max_length=20,
            ),
        ),
        migrations.AlterModelOptions(
            name="message",
            options={
                "ordering": ["sent_at"],
                "permissions": (
                    (
                        "review_restricted_messages",
                        "Can review restricted conversation messages",
                    ),
                ),
            },
        ),
        migrations.AddIndex(
            model_name="message",
            index=models.Index(
                fields=["conversation", "visibility", "review_status"],
                name="items_messa_convers_f4b80c_idx",
            ),
        ),
        migrations.AlterField(
            model_name="contactauditlog",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("request_created", "Contact request created"),
                    ("request_cancelled", "Contact request cancelled"),
                    ("request_approved", "Request approved"),
                    ("request_denied", "Request denied"),
                    ("permission_revoked", "Permission revoked"),
                    ("conversation_opened", "Conversation opened"),
                    ("message_sent", "Message sent"),
                    ("message_read", "Message read"),
                    ("phone_granted", "Phone-number access granted"),
                    ("phone_blocked", "Phone-number access blocked"),
                    ("phone_masked", "Masked phone number displayed"),
                    ("restricted_messages_viewed", "Restricted messages reviewed"),
                    ("bulk_report_action", "Bulk report action"),
                    ("deal_completed", "Deal completed"),
                    ("conversation_reopened", "Conversation reopened"),
                ],
                db_index=True,
                max_length=32,
            ),
        ),
    ]
