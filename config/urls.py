"""Project-level URL configuration for FindMatch."""

from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from items import views

localized_urlpatterns = [
    path("", views.home, name="home"),
    path("items/", include("items.urls")),
    path("my-reports/", views.my_reports, name="my_reports"),
    path("my-dashboard/", views.user_dashboard, name="user_dashboard"),
    path("my-matches/", views.my_possible_matches, name="my_possible_matches"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", views.RoleAwareLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/profile/", views.profile_detail, name="profile"),
    path("accounts/profile/edit/", views.profile_edit, name="profile_edit"),
    path("accounts/verify-email/<str:token>/", views.verify_email, name="verify_email"),
    path("accounts/resend-verification/", views.resend_verification, name="resend_verification"),
    path("accounts/password-reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("accounts/password-reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("accounts/reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("accounts/privacy/", views.privacy_centre, name="privacy_centre"),
    path("accounts/data-export/", views.account_data_export, name="account_data_export"),
    path("accounts/request-deactivation/", views.request_account_deactivation, name="request_account_deactivation"),
    path("privacy/", views.privacy_policy, name="privacy_policy"),
    path("terms/", views.terms, name="terms"),
    path("contact-requests/sent/", views.contact_requests_sent, name="contact_requests_sent"),
    path(
        "contact-requests/received/",
        views.contact_requests_received,
        name="contact_requests_received",
    ),
    path(
        "contact-requests/<int:pk>/",
        views.contact_request_detail,
        name="contact_request_detail",
    ),
    path(
        "contact-requests/<int:pk>/cancel/",
        views.contact_request_cancel,
        name="contact_request_cancel",
    ),
    path(
        "contact-requests/<int:pk>/start/",
        views.contact_request_start,
        name="contact_request_start",
    ),
    path("claims/<int:pk>/clarification/", views.claim_clarification_answer, name="claim_clarification_answer"),
    path("claims/<int:pk>/report-suspicious/", views.claim_report_suspicious, name="claim_report_suspicious"),
    path("claims/<int:pk>/confirm-handover/", views.claim_handover_confirm, name="claim_handover_confirm"),
    path("claims/<int:pk>/return/", views.return_arrangement, name="return_arrangement"),
    path("claims/<int:pk>/return/confirm/<str:role>/", views.return_confirmation, name="return_confirmation"),
    path("claim-evidence/<int:pk>/download/", views.claim_evidence_download, name="claim_evidence_download"),
    path("claims/<int:pk>/<str:action>/", views.claim_action, name="claim_action"),
    path("conversations/", views.conversation_list, name="conversation_list"),
    path("conversations/<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("conversations/<int:pk>/complete/", views.conversation_complete, name="conversation_complete"),
    path("messages/<int:pk>/delete/", views.message_delete, name="message_delete"),
    path("messages/<int:pk>/attachment/", views.message_attachment_download, name="message_attachment_download"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/unread-count/", views.notification_unread_count, name="notification_unread_count"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
    path("notifications/read-all/", views.notification_mark_all_read, name="notification_mark_all_read"),
    path("saved-searches/", views.saved_search_list, name="saved_search_list"),
    path("saved-searches/create/", views.saved_search_create, name="saved_search_create"),
    path("saved-searches/<int:pk>/<str:action>/", views.saved_search_action, name="saved_search_action"),
    path("management/", views.dashboard_home, name="management_dashboard"),
    path("management/", views.dashboard_home, name="dashboard_home"),
    path("management/reports/", views.dashboard_reports, name="management_reports"),
    path("management/reports/", views.dashboard_reports, name="dashboard_reports"),
    path(
        "management/reports/bulk-action/",
        views.dashboard_report_bulk_action,
        name="management_report_bulk_action",
    ),
    path(
        "management/reports/bulk-confirm/",
        views.dashboard_report_bulk_confirm,
        name="management_report_bulk_confirm",
    ),
    path(
        "management/reports/<int:pk>/visibility/",
        views.dashboard_report_visibility,
        name="management_report_visibility",
    ),
    path(
        "management/reports/<int:pk>/visibility/",
        views.dashboard_report_visibility,
        name="dashboard_report_visibility",
    ),
    path("management/users/", views.dashboard_users, name="management_users"),
    path(
        "management/conversations/",
        views.management_conversations,
        name="management_conversations",
    ),
    path(
        "management/conversations/<int:pk>/deactivate/",
        views.management_conversation_deactivate,
        name="management_conversation_deactivate",
    ),
    path(
        "management/conversations/<int:pk>/complete/",
        views.management_conversation_complete,
        name="management_conversation_complete",
    ),
    path(
        "management/conversations/<int:pk>/reopen/",
        views.management_conversation_reopen,
        name="management_conversation_reopen",
    ),
    path("management/audit/", views.management_audit_log, name="management_audit_log"),
    path("management/users/", views.dashboard_users, name="dashboard_users"),
    path(
        "management/users/<int:pk>/",
        views.dashboard_user_detail,
        name="management_user_detail",
    ),
    path(
        "management/users/<int:pk>/",
        views.dashboard_user_detail,
        name="dashboard_user_detail",
    ),
    path(
        "management/users/<int:pk>/toggle-active/",
        views.dashboard_user_toggle_active,
        name="management_user_toggle_active",
    ),
    path(
        "management/users/<int:pk>/toggle-active/",
        views.dashboard_user_toggle_active,
        name="dashboard_user_toggle_active",
    ),
    path("403/", views.permission_denied, name="permission_denied_page"),
    path("404/", views.page_not_found, name="page_not_found_page"),
    # Compatibility redirects for links from earlier FindMatch versions.
    path("register/", RedirectView.as_view(pattern_name="register", permanent=False)),
    path("login/", RedirectView.as_view(pattern_name="login", permanent=False, query_string=True)),
    path("logout/", auth_views.LogoutView.as_view()),
    path("reports/", RedirectView.as_view(pattern_name="item_list", permanent=False, query_string=True)),
    path("reports/mine/", RedirectView.as_view(pattern_name="my_reports", permanent=False, query_string=True)),
    path("matches/", RedirectView.as_view(pattern_name="my_possible_matches", permanent=False)),
    path("dashboard/", RedirectView.as_view(pattern_name="management_dashboard", permanent=False)),
    path("dashboard/reports/", RedirectView.as_view(pattern_name="management_reports", permanent=False, query_string=True)),
    path("dashboard/users/", RedirectView.as_view(pattern_name="management_users", permanent=False, query_string=True)),
    path("reports/create/<str:report_type>/", views.report_create),
    path("reports/<int:pk>/", views.report_detail),
    path("reports/<int:pk>/edit/", views.report_edit),
    path("reports/<int:pk>/delete/", views.report_delete),
    path("reports/<int:pk>/matches/", views.possible_matches),
    path("reports/<int:pk>/status/<str:new_status>/", views.change_status),
    path("reports/<int:pk>/renew/", views.report_renew, name="report_renew"),
]

urlpatterns = [
    path("health/", views.health_check, name="health_check"),
    path("", RedirectView.as_view(pattern_name="home", permanent=False)),
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
]

urlpatterns += i18n_patterns(
    *localized_urlpatterns,
    prefix_default_language=True,
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "items.views.permission_denied"
handler404 = "items.views.page_not_found"
