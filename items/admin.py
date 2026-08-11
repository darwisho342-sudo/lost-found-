from django.contrib import admin

from .models import (
    AIAssistantSettings,
    AICapability,
    AICapabilityAuditLog,
    AICapabilitySetting,
    AdminCapabilityOverride,
    ContactAuditLog,
    ContactRequest,
    Conversation,
    ItemReport,
    Message,
    Notification,
    UserBlock,
    UserProfile,
)


@admin.register(ItemReport)
class ItemReportAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "report_type",
        "category",
        "campus_location",
        "status",
        "owner",
        "item_date",
        "is_reviewed",
        "is_deleted",
    )
    list_filter = ("report_type", "category", "campus_location", "status", "is_reviewed", "is_deleted")
    search_fields = ("title", "description", "colour", "owner__username")
    list_select_related = ("owner",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "consent_to_share_phone",
        "mask_phone_number",
        "updated_at",
    )
    search_fields = ("user__username", "user__email")
    exclude = ("phone_number",)


@admin.register(ContactRequest)
class ContactRequestAdmin(admin.ModelAdmin):
    list_display = ("item_report", "request_type", "requesting_user", "receiving_user", "status", "requested_at")
    list_filter = ("request_type", "status")
    search_fields = ("item_report__title", "requesting_user__username", "receiving_user__username")
    readonly_fields = ("requested_at", "reviewed_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("item_report", "first_participant", "second_participant", "status", "is_active", "last_message_at")
    list_filter = ("status", "is_active")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "sent_at", "read_at", "is_deleted")
    list_filter = ("is_deleted",)
    exclude = ("body",)


@admin.register(UserBlock)
class UserBlockAdmin(admin.ModelAdmin):
    list_display = ("blocker", "blocked_user", "created_at")
    search_fields = ("blocker__username", "blocked_user__username")
    readonly_fields = ("created_at",)


@admin.register(ContactAuditLog)
class ContactAuditLogAdmin(admin.ModelAdmin):
    list_display = ("event_type", "acting_user", "item_report", "timestamp")
    list_filter = ("event_type",)
    readonly_fields = ("acting_user", "event_type", "item_report", "contact_request", "conversation", "timestamp", "description")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "notification_type", "is_read", "created_at")
    list_filter = ("notification_type", "is_read")
    search_fields = ("title", "safe_message", "recipient__username")
    readonly_fields = ("created_at", "read_at", "deduplication_key")


@admin.register(AICapability)
class AICapabilityAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "risk_level", "is_available", "display_order")
    list_filter = ("risk_level", "is_available")
    search_fields = ("name", "code", "description")
    readonly_fields = ("code", "created_at", "updated_at")


@admin.register(AIAssistantSettings)
class AIAssistantSettingsAdmin(admin.ModelAdmin):
    list_display = ("is_enabled", "provider_name", "model_name", "updated_by", "updated_at")

    def has_add_permission(self, request):
        return not AIAssistantSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AICapabilitySetting)
class AICapabilitySettingAdmin(admin.ModelAdmin):
    list_display = ("capability", "is_enabled", "updated_by", "updated_at")
    list_filter = ("is_enabled",)


@admin.register(AdminCapabilityOverride)
class AdminCapabilityOverrideAdmin(admin.ModelAdmin):
    list_display = ("administrator", "capability", "setting")
    list_filter = ("setting", "capability")


@admin.register(AICapabilityAuditLog)
class AICapabilityAuditLogAdmin(admin.ModelAdmin):
    list_display = ("event_type", "acting_administrator", "capability", "scope", "created_at")
    list_filter = ("event_type", "scope")
    readonly_fields = (
        "acting_administrator", "capability", "event_type", "old_value", "new_value",
        "scope", "safe_description", "ip_address", "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

# Register your models here.
