"""Project-level URL configuration for FindMatch."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

from items import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home, name="home"),
    path("items/", include("items.urls")),
    path("my-reports/", views.my_reports, name="my_reports"),
    path("my-matches/", views.my_possible_matches, name="my_possible_matches"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", views.RoleAwareLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/profile/", views.profile_detail, name="profile"),
    path("accounts/profile/edit/", views.profile_edit, name="profile_edit"),
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
    path("conversations/", views.conversation_list, name="conversation_list"),
    path("conversations/<int:pk>/", views.conversation_detail, name="conversation_detail"),
    path("conversations/<int:pk>/complete/", views.conversation_complete, name="conversation_complete"),
    path("messages/<int:pk>/delete/", views.message_delete, name="message_delete"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/unread-count/", views.notification_unread_count, name="notification_unread_count"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
    path("notifications/read-all/", views.notification_mark_all_read, name="notification_mark_all_read"),
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
        "management/ai-assistant/",
        views.management_ai_assistant,
        name="management_ai_assistant",
    ),
    path(
        "management/ai-assistant/settings/",
        views.management_ai_assistant_settings,
        name="management_ai_assistant_settings",
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
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "items.views.permission_denied"
handler404 = "items.views.page_not_found"
