from django.urls import path

from . import views

urlpatterns = [
    path("", views.report_list, name="item_list"),
    path("lost/", views.report_list, {"report_type": "lost"}, name="lost_item_list"),
    path("found/", views.report_list, {"report_type": "found"}, name="found_item_list"),
    path("create/lost/", views.report_create, {"report_type": "lost"}, name="item_create_lost"),
    path("create/found/", views.report_create, {"report_type": "found"}, name="item_create_found"),
    path("<int:pk>/", views.report_detail, name="item_detail"),
    path("<int:pk>/edit/", views.report_edit, name="item_edit"),
    path("<int:pk>/delete/", views.report_delete, name="item_delete"),
    path("<int:pk>/matches/", views.possible_matches, name="item_matches"),
    path("<int:pk>/contact/", views.contact_request_create, name="contact_request_create"),
    path("<int:pk>/resolve/", views.change_status, {"new_status": "resolved"}, name="item_resolve"),
    path("<int:pk>/close/", views.change_status, {"new_status": "closed"}, name="item_close"),
    # Name aliases keep existing integrations and tests working on canonical paths.
    path("", views.report_list, name="report_list"),
    path("create/<str:report_type>/", views.report_create, name="report_create"),
    path("<int:pk>/", views.report_detail, name="report_detail"),
    path("<int:pk>/edit/", views.report_edit, name="report_edit"),
    path("<int:pk>/delete/", views.report_delete, name="report_delete"),
    path("<int:pk>/matches/", views.possible_matches, name="possible_matches"),
    path("<int:pk>/status/<str:new_status>/", views.change_status, name="change_status"),
]
