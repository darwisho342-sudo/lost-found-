from django.contrib import admin

from .models import (
    ContactAuditLog,
    ContactRequest,
    ClaimAnswer,
    ClaimAppeal,
    ClaimEvidence,
    Conversation,
    ItemReport,
    ReportImage,
    DismissedMatch,
    PrivateVerificationQuestion,
    HandoverConfirmation,
    SuspiciousClaimReport,
    Message,
    Notification,
    UserBlock,
    UserProfile,
    TrustedOrganization, OrganizationMembership, ReturnArrangement, CustodyEvent,
    SavedSearch, SavedSearchNotification, ContentReport,
    CustodyRecord, CustodyMovement, StorageIncident,
    UniversityLocation,
)


@admin.register(ItemReport)
class ItemReportAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "scope",
        "report_type",
        "category",
        "campus_location",
        "status",
        "owner",
        "item_date",
        "is_reviewed",
        "is_deleted",
    )
    list_filter = ("scope", "report_type", "category", "campus_location", "country", "status", "is_reviewed", "is_deleted")
    search_fields = ("title", "description", "colour", "owner__username")
    list_select_related = ("owner",)
    readonly_fields = ("created_at", "updated_at")
    exclude = ("private_sensitive_image",)


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


@admin.register(PrivateVerificationQuestion)
class PrivateVerificationQuestionAdmin(admin.ModelAdmin):
    list_display = ("item_report", "question_type", "position")
    exclude = ("expected_answer",)


@admin.register(ClaimAnswer)
class ClaimAnswerAdmin(admin.ModelAdmin):
    list_display = ("contact_request", "question")
    exclude = ("answer",)


@admin.register(ClaimEvidence)
class ClaimEvidenceAdmin(admin.ModelAdmin):
    list_display = ("contact_request", "uploaded_at")
    exclude = ("file",)


admin.site.register(HandoverConfirmation)
admin.site.register(SuspiciousClaimReport)
admin.site.register(ClaimAppeal)
admin.site.register(ReportImage)
admin.site.register(DismissedMatch)


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


@admin.register(TrustedOrganization)
class TrustedOrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "organization_type", "country", "city", "is_verified")
    list_filter = ("organization_type", "is_verified", "country")
    search_fields = ("name", "country", "city")


admin.site.register(OrganizationMembership)
admin.site.register(CustodyEvent)
admin.site.register(SavedSearch)
admin.site.register(SavedSearchNotification)
admin.site.register(ContentReport)


@admin.register(CustodyRecord)
class CustodyRecordAdmin(admin.ModelAdmin):
    list_display = ("reference", "found_report", "status", "intake_at", "retention_expires_at", "is_high_value")
    list_filter = ("status", "is_high_value", "is_locked_storage")
    search_fields = ("reference", "found_report__title")
    exclude = ("storage_reference", "notes")


@admin.register(CustodyMovement)
class CustodyMovementAdmin(admin.ModelAdmin):
    list_display = ("custody_record", "event_type", "recorded_by", "recorded_at")
    readonly_fields = ("custody_record", "event_type", "recorded_by", "recorded_at", "safe_note")

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(StorageIncident)


@admin.register(UniversityLocation)
class UniversityLocationAdmin(admin.ModelAdmin):
    list_display = ("campus", "building", "general_area", "location_type", "is_active")
    list_filter = ("campus", "location_type", "is_active")
    search_fields = ("campus", "building", "general_area")


@admin.register(ReturnArrangement)
class ReturnArrangementAdmin(admin.ModelAdmin):
    list_display = ("contact_request", "return_method", "status", "trusted_organization", "updated_at")
    list_filter = ("return_method", "status", "legal_or_safety_hold")
    exclude = ("delivery_address", "tracking_reference")
