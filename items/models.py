from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


MAX_IMAGE_SIZE = 5 * 1024 * 1024


def normalize_phone_number(value):
    value = (value or "").strip()
    if not value:
        return ""
    has_country_code = value.startswith("+")
    digits = "".join(character for character in value if character.isdigit())
    return f"+{digits}" if has_country_code else digits


def validate_phone_number(value):
    raw_value = (value or "").strip()
    allowed_punctuation = set("+()- .")
    if any(not character.isdigit() and character not in allowed_punctuation for character in raw_value):
        raise ValidationError("Enter a valid phone number containing 7 to 15 digits.")
    if "+" in raw_value and (not raw_value.startswith("+") or raw_value.count("+") > 1):
        raise ValidationError("Enter a valid phone number containing 7 to 15 digits.")
    normalized = normalize_phone_number(value)
    digits = normalized.removeprefix("+")
    if normalized and (not digits.isdigit() or not 7 <= len(digits) <= 15):
        raise ValidationError("Enter a valid phone number containing 7 to 15 digits.")


def validate_image_size(image):
    if image.size > MAX_IMAGE_SIZE:
        raise ValidationError("The image must be 5 MB or smaller.")


def report_image_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    return f"reports/user_{instance.owner_id}/{instance.report_type}_{instance.pk or 'new'}{suffix}"


class ItemReport(models.Model):
    class ReportType(models.TextChoices):
        LOST = "lost", "Lost"
        FOUND = "found", "Found"

    class Category(models.TextChoices):
        ELECTRONICS = "electronics", "Electronics"
        BAGS = "bags", "Bags"
        CLOTHING = "clothing", "Clothing"
        DOCUMENTS = "documents", "Documents"
        KEYS = "keys", "Keys"
        WALLETS = "wallets", "Wallets"
        JEWELLERY = "jewellery", "Jewellery"
        BOOKS = "books", "Books"
        OTHER = "other", "Other"

    class CampusLocation(models.TextChoices):
        MAIN_ENTRANCE = "main_entrance", "Main Entrance"
        LIBRARY = "library", "Library"
        CAFETERIA = "cafeteria", "Cafeteria"
        CLASSROOM = "classroom", "Classroom"
        LABORATORY = "laboratory", "Laboratory"
        STUDENT_AFFAIRS = "student_affairs", "Student Affairs"
        SPORTS_AREA = "sports_area", "Sports Area"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        POSSIBLE_MATCH = "possible_match", "Possible Match"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="item_reports"
    )
    report_type = models.CharField(max_length=5, choices=ReportType.choices, db_index=True)
    title = models.CharField(max_length=120)
    description = models.TextField(max_length=1500)
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    colour = models.CharField(max_length=50, db_index=True)
    campus_location = models.CharField(
        max_length=30, choices=CampusLocation.choices, db_index=True
    )
    item_date = models.DateField("date lost or found", db_index=True)
    image = models.ImageField(
        upload_to=report_image_path, validators=[validate_image_size]
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    is_hidden = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Hidden reports are visible only to their owner and staff members.",
    )
    is_reviewed = models.BooleanField(default=False, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_item_reports",
    )
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_item_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["report_type", "status", "-created_at"])]

    def __str__(self):
        return f"{self.get_report_type_display()}: {self.title}"

    def get_absolute_url(self):
        return reverse("item_detail", kwargs={"pk": self.pk})


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    phone_number = models.CharField(
        max_length=16, blank=True, validators=[validate_phone_number]
    )
    consent_to_share_phone = models.BooleanField(
        default=False,
        help_text=(
            "When enabled, your phone number is shown only after staff approve a contact "
            "request. You can revoke consent at any time."
        ),
    )
    mask_phone_number = models.BooleanField(
        default=True,
        help_text="Show active conversation contacts only the final four digits of your phone number.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        permissions = (
            ("view_unmasked_phone_numbers", "Can view unmasked shared phone numbers"),
        )

    def clean(self):
        super().clean()
        validate_phone_number(self.phone_number)
        self.phone_number = normalize_phone_number(self.phone_number)

    def save(self, *args, **kwargs):
        self.phone_number = normalize_phone_number(self.phone_number)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profile for {self.user.username}"


class UserBlock(models.Model):
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_user_relationships",
    )
    blocked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_by_relationships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("blocker", "blocked_user"), name="unique_user_block"
            ),
            models.CheckConstraint(
                condition=~Q(blocker=models.F("blocked_user")),
                name="user_cannot_block_self",
            ),
        ]

    def __str__(self):
        return f"{self.blocker} blocked {self.blocked_user}"


class ContactRequest(models.Model):
    class RequestType(models.TextChoices):
        OWNERSHIP_CLAIM = "ownership_claim", "Ownership Claim"
        FOUND_ITEM = "found_item", "Found Item"

    class Status(models.TextChoices):
        INITIATED = "initiated", "Conversation Started"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"
        CANCELLED = "cancelled", "Cancelled"
        REVOKED = "revoked", "Revoked"

    item_report = models.ForeignKey(
        ItemReport, on_delete=models.CASCADE, related_name="contact_requests"
    )
    requesting_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_contact_requests",
    )
    receiving_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_contact_requests",
    )
    request_type = models.CharField(max_length=24, choices=RequestType.choices)
    initial_message = models.TextField(validators=[MaxLengthValidator(2000)])
    private_details = models.TextField(validators=[MaxLengthValidator(2000)])
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_contact_requests",
    )
    admin_note = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(requesting_user=models.F("receiving_user")),
                name="contact_request_different_users",
            ),
            models.UniqueConstraint(
                fields=("item_report", "requesting_user", "receiving_user"),
                condition=Q(status="pending"),
                name="unique_pending_contact_request",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.requesting_user_id is not None
            and self.requesting_user_id == self.receiving_user_id
        ):
            raise ValidationError("You cannot send a contact request to yourself.")
        if (
            self.item_report_id
            and self.receiving_user_id is not None
            and self.receiving_user_id != self.item_report.owner_id
        ):
            raise ValidationError("The request recipient must own the item report.")
        if self.item_report_id:
            expected_type = (
                self.RequestType.OWNERSHIP_CLAIM
                if self.item_report.report_type == ItemReport.ReportType.FOUND
                else self.RequestType.FOUND_ITEM
            )
            if self.request_type and self.request_type != expected_type:
                raise ValidationError("The request type does not match this report.")

    def can_view(self, user):
        return user.is_authenticated and (
            user.is_staff or user.pk in (self.requesting_user_id, self.receiving_user_id)
        )

    def __str__(self):
        return f"{self.get_request_type_display()} for {self.item_report.title}"


class Conversation(models.Model):
    class DealStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        DEACTIVATED = "deactivated", "Deactivated"
        COMPLETED = "completed", "Completed"
        CLOSED = "closed", "Closed"

    item_report = models.ForeignKey(
        ItemReport, on_delete=models.CASCADE, related_name="conversations"
    )
    approved_contact_request = models.OneToOneField(
        ContactRequest, on_delete=models.CASCADE, related_name="conversation"
    )
    first_participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_first",
    )
    second_participant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations_as_second",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(
        max_length=12, choices=DealStatus.choices, default=DealStatus.ACTIVE, db_index=True
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_conversations",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_conversations",
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reopened_conversations",
    )
    deactivated_at = models.DateTimeField(null=True, blank=True)
    deactivated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deactivated_conversations",
    )
    deactivation_reason = models.TextField(
        blank=True, validators=[MaxLengthValidator(1000)]
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-last_message_at"]
        constraints = [
            models.UniqueConstraint(
                fields=("item_report", "first_participant", "second_participant"),
                name="unique_report_participant_conversation",
            ),
        ]

    def can_view(self, user):
        return user.is_authenticated and (
            user.is_staff or user.pk in (self.first_participant_id, self.second_participant_id)
        )

    def other_participant(self, user):
        if user.pk == self.first_participant_id:
            return self.second_participant
        if user.pk == self.second_participant_id:
            return self.first_participant
        return None

    def __str__(self):
        return f"Conversation for {self.item_report.title}"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contact_messages"
    )
    body = models.TextField(validators=[MaxLengthValidator(2000)])
    sent_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["sent_at"]

    def clean(self):
        super().clean()
        if not self.body.strip():
            raise ValidationError({"body": "A message cannot be empty."})
        if self.conversation_id and self.sender_id not in (
            self.conversation.first_participant_id,
            self.conversation.second_participant_id,
        ):
            raise ValidationError("The sender must be a conversation participant.")

    def __str__(self):
        return f"Message {self.pk or 'new'} in conversation {self.conversation_id}"


class ContactAuditLog(models.Model):
    class EventType(models.TextChoices):
        REQUEST_CREATED = "request_created", "Contact request created"
        REQUEST_CANCELLED = "request_cancelled", "Contact request cancelled"
        REQUEST_APPROVED = "request_approved", "Request approved"
        REQUEST_DENIED = "request_denied", "Request denied"
        PERMISSION_REVOKED = "permission_revoked", "Permission revoked"
        CONVERSATION_OPENED = "conversation_opened", "Conversation opened"
        MESSAGE_SENT = "message_sent", "Message sent"
        MESSAGE_READ = "message_read", "Message read"
        PHONE_GRANTED = "phone_granted", "Phone-number access granted"
        PHONE_BLOCKED = "phone_blocked", "Phone-number access blocked"
        PHONE_MASKED = "phone_masked", "Masked phone number displayed"
        BULK_REPORT_ACTION = "bulk_report_action", "Bulk report action"
        DEAL_COMPLETED = "deal_completed", "Deal completed"
        CONVERSATION_REOPENED = "conversation_reopened", "Conversation reopened"
        CONVERSATION_DEACTIVATED = "conversation_deactivated", "Conversation deactivated"

    acting_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="contact_audit_events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices, db_index=True)
    item_report = models.ForeignKey(
        ItemReport, on_delete=models.SET_NULL, null=True, related_name="contact_audit_events"
    )
    contact_request = models.ForeignKey(
        ContactRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)
    description = models.CharField(max_length=255)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return self.get_event_type_display()


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        NEW_MESSAGE = "new_message", "New Message"
        DEAL_COMPLETED = "deal_completed", "Deal Completed"
        CONVERSATION_REOPENED = "conversation_reopened", "Conversation Reopened"
        CONVERSATION_DEACTIVATED = "conversation_deactivated", "Conversation Deactivated"
        CONTACT_APPROVED = "contact_approved", "Contact Request Approved"
        CONTACT_DENIED = "contact_denied", "Contact Request Denied"
        REPORT_STATUS_CHANGED = "report_status_changed", "Report Status Changed"
        ADMIN_NOTICE = "admin_notice", "Administrator Notice"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(
        max_length=28, choices=NotificationType.choices, db_index=True
    )
    title = models.CharField(max_length=100)
    safe_message = models.CharField(max_length=255)
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    item_report = models.ForeignKey(
        ItemReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    destination_url = models.CharField(max_length=255, blank=True)
    deduplication_key = models.CharField(max_length=160, unique=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_notification_type_display()} for {self.recipient.username}"


class AICapability(models.Model):
    class RiskLevel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    code = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255)
    risk_level = models.CharField(max_length=10, choices=RiskLevel.choices)
    enabled_by_default = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("display_order", "name")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        AICapabilitySetting.objects.get_or_create(
            capability=self, defaults={"is_enabled": self.enabled_by_default}
        )


class AIAssistantSettings(models.Model):
    is_enabled = models.BooleanField(default=False)
    provider_name = models.CharField(max_length=80, default="Local deterministic provider")
    model_name = models.CharField(max_length=80, default="findmatch-local-v1")
    request_timeout_seconds = models.PositiveSmallIntegerField(default=15)
    maximum_input_length = models.PositiveIntegerField(default=5000)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_ai_assistant_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "AI assistant settings"
        permissions = (("manage_ai_assistant", "Can manage global AI assistant settings"),)

    @classmethod
    def get_solo(cls):
        settings_record, _ = cls.objects.get_or_create(pk=1)
        return settings_record

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return None

    def __str__(self):
        return "Global AI Assistant settings"


class AICapabilitySetting(models.Model):
    capability = models.OneToOneField(
        AICapability, on_delete=models.CASCADE, related_name="global_setting"
    )
    is_enabled = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_ai_capability_settings",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.capability.name}: {'enabled' if self.is_enabled else 'disabled'}"


class AdminCapabilityOverride(models.Model):
    class OverrideSetting(models.TextChoices):
        INHERIT = "inherit", "Inherit Global Setting"
        ENABLED = "enabled", "Enabled"
        DISABLED = "disabled", "Disabled"

    administrator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_capability_overrides",
        limit_choices_to={"is_staff": True},
    )
    capability = models.ForeignKey(
        AICapability, on_delete=models.CASCADE, related_name="administrator_overrides"
    )
    setting = models.CharField(
        max_length=10, choices=OverrideSetting.choices, default=OverrideSetting.INHERIT
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("administrator", "capability"),
                name="unique_ai_capability_override",
            )
        ]

    def clean(self):
        super().clean()
        if self.administrator_id and not self.administrator.is_staff:
            raise ValidationError("AI capability overrides are available only to staff users.")
        if self.setting == self.OverrideSetting.ENABLED and self.capability_id:
            global_setting = getattr(self.capability, "global_setting", None)
            if global_setting is None or not global_setting.is_enabled:
                raise ValidationError("A personal override cannot enable a globally disabled capability.")

    def __str__(self):
        return f"{self.administrator}: {self.capability.code} ({self.setting})"


class AICapabilityAuditLog(models.Model):
    class EventType(models.TextChoices):
        ASSISTANT_ENABLED = "assistant_enabled", "Assistant Enabled"
        ASSISTANT_DISABLED = "assistant_disabled", "Assistant Disabled"
        CAPABILITY_ENABLED = "capability_enabled", "Capability Enabled"
        CAPABILITY_DISABLED = "capability_disabled", "Capability Disabled"
        OVERRIDE_CHANGED = "override_changed", "Override Changed"
        REQUEST_EXECUTED = "request_executed", "Request Executed"
        REQUEST_BLOCKED = "request_blocked", "Request Blocked"
        PROVIDER_FAILURE = "provider_failure", "Provider Failure"

    acting_administrator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="ai_capability_audit_events",
    )
    capability = models.ForeignKey(
        AICapability,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=24, choices=EventType.choices, db_index=True)
    old_value = models.CharField(max_length=255, blank=True)
    new_value = models.CharField(max_length=255, blank=True)
    scope = models.CharField(max_length=40, default="global")
    safe_description = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.get_event_type_display()

# Create your models here.
