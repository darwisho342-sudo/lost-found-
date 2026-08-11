from datetime import date, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import ItemReportForm, UserProfileForm
from .models import (
    AIAssistantSettings,
    AICapability,
    AICapabilityAuditLog,
    AICapabilitySetting,
    AdminCapabilityOverride,
    MAX_IMAGE_SIZE,
    ContactAuditLog,
    ContactRequest,
    Conversation,
    ItemReport,
    Message,
    Notification,
    UserBlock,
    UserProfile,
    validate_image_size,
)
from .services import MatchingService
from .ai_assistant import AIAssistantService, AICapabilityService


def test_image(name="item.jpg", colour="blue"):
    buffer = BytesIO()
    Image.new("RGB", (40, 40), colour).save(buffer, format="JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class MediaTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_directory = TemporaryDirectory()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media_directory.name)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        cls.media_directory.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.owner = User.objects.create_user(
            username="student", email="student@example.invalid", password="StrongPass123!"
        )

    def create_report(self, **overrides):
        data = {
            "owner": self.owner,
            "report_type": ItemReport.ReportType.LOST,
            "title": "Black headphones",
            "description": "Black wireless headphones in a hard case",
            "category": ItemReport.Category.ELECTRONICS,
            "colour": "Black",
            "campus_location": ItemReport.CampusLocation.LIBRARY,
            "item_date": date.today(),
            "image": test_image(),
        }
        data.update(overrides)
        return ItemReport.objects.create(**data)


class HomepageAndAuthenticationTests(MediaTestCase):
    def test_homepage_is_public(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lost something? Let us help you find it.")

    def test_registration_logs_user_in(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "new_student",
                "email": "new@example.invalid",
                "password1": "A-Strong-Passphrase-135!",
                "password2": "A-Strong-Passphrase-135!",
            },
        )
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), User.objects.get(username="new_student").pk)

    def test_duplicate_email_has_clear_error(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "another",
                "email": self.owner.email.upper(),
                "password1": "A-Strong-Passphrase-135!",
                "password2": "A-Strong-Passphrase-135!",
            },
        )
        self.assertContains(response, "already uses this email", status_code=200)

    def test_login_and_protected_page(self):
        response = self.client.get(reverse("my_reports"))
        self.assertRedirects(response, f'{reverse("login")}?next={reverse("my_reports")}')
        self.assertTrue(self.client.login(username="student", password="StrongPass123!"))
        self.assertEqual(self.client.get(reverse("my_reports")).status_code, 200)


class ReportTests(MediaTestCase):
    def valid_form_data(self):
        return {
            "title": "Blue backpack",
            "description": "Blue canvas backpack with two pockets",
            "category": ItemReport.Category.BAGS,
            "colour": " Blue  Navy ",
            "campus_location": ItemReport.CampusLocation.CAFETERIA,
            "item_date": date.today().isoformat(),
            "image": test_image("backpack.jpg"),
        }

    def test_authenticated_user_can_create_report(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("report_create", args=["lost"]), self.valid_form_data())
        report = ItemReport.objects.get(title="Blue backpack")
        self.assertRedirects(response, reverse("possible_matches", args=[report.pk]))
        self.assertEqual(report.owner, self.owner)
        self.assertEqual(report.colour, "Blue Navy")

    def test_invalid_image_is_rejected(self):
        data = self.valid_form_data()
        data["image"] = SimpleUploadedFile("notes.txt", b"not an image", content_type="text/plain")
        form = ItemReportForm(data=data, files={"image": data["image"]})
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_oversized_image_validator(self):
        upload = SimpleUploadedFile("large.jpg", b"x" * (MAX_IMAGE_SIZE + 1))
        with self.assertRaises(ValidationError):
            validate_image_size(upload)

    def test_future_date_is_rejected(self):
        data = self.valid_form_data()
        data["item_date"] = (date.today() + timedelta(days=1)).isoformat()
        form = ItemReportForm(data=data, files={"image": data["image"]})
        self.assertFalse(form.is_valid())
        self.assertIn("future", form.errors["item_date"][0])

    def test_owner_can_edit_report(self):
        report = self.create_report()
        self.client.force_login(self.owner)
        data = self.valid_form_data()
        data["title"] = "Updated title"
        data.pop("image")
        response = self.client.post(reverse("report_edit", args=[report.pk]), data)
        self.assertRedirects(response, report.get_absolute_url())
        report.refresh_from_db()
        self.assertEqual(report.title, "Updated title")

    def test_other_user_cannot_edit_report(self):
        report = self.create_report()
        stranger = User.objects.create_user("stranger", password="StrongPass123!")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("report_edit", args=[report.pk])).status_code, 403)

    def test_staff_can_edit_report(self):
        report = self.create_report()
        staff = User.objects.create_user("staff", password="StrongPass123!", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("report_edit", args=[report.pk])).status_code, 200)

    def test_owner_can_resolve_and_close_reports(self):
        self.client.force_login(self.owner)
        for status in ("resolved", "closed"):
            report = self.create_report(title=f"Report {status}", image=test_image(f"{status}.jpg"))
            response = self.client.post(reverse("change_status", args=[report.pk, status]))
            self.assertRedirects(response, report.get_absolute_url())
            report.refresh_from_db()
            self.assertEqual(report.status, status)

    def test_final_status_requires_post(self):
        report = self.create_report()
        self.client.force_login(self.owner)
        response = self.client.get(reverse("change_status", args=[report.pk, "closed"]))
        self.assertContains(response, "Confirmation")
        report.refresh_from_db()
        self.assertEqual(report.status, ItemReport.Status.ACTIVE)


class SearchAndFilterTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.create_report(title="Blue backpack", category="bags", colour="Blue")
        self.create_report(
            title="Silver keys",
            description="Three keys",
            category="keys",
            colour="Silver",
            report_type="found",
            campus_location="cafeteria",
            image=test_image("keys.jpg"),
        )

    def test_keyword_searches_title_and_description(self):
        response = self.client.get(reverse("report_list"), {"query": "keys"})
        self.assertContains(response, "Silver keys")
        self.assertNotContains(response, "Blue backpack")

    def test_filters_work_together(self):
        response = self.client.get(
            reverse("report_list"),
            {"report_type": "found", "category": "keys", "campus_location": "cafeteria"},
        )
        self.assertContains(response, "Silver keys")
        self.assertNotContains(response, "Blue backpack")

    def test_empty_results_message(self):
        response = self.client.get(reverse("report_list"), {"query": "telescope"})
        self.assertContains(response, "No reports matched")


class MatchingServiceTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.lost = self.create_report(item_date=date(2026, 8, 1))

    def found_report(self, **overrides):
        data = {
            "owner": self.owner,
            "report_type": "found",
            "title": "Headphones found",
            "item_date": date(2026, 8, 2),
            "image": test_image("found.jpg"),
        }
        data.update(overrides)
        return self.create_report(**data)

    def test_identical_details_score_correctly(self):
        found = self.found_report()
        result = MatchingService.compare(self.lost, found)
        self.assertEqual(result.category_points, 25)
        self.assertEqual(result.description_points, 25)
        self.assertEqual(result.colour_points, 20)
        self.assertEqual(result.location_points, 15)
        self.assertEqual(result.date_points, 13)
        self.assertEqual(result.total_score, 98)

    def test_same_report_types_are_rejected(self):
        another_lost = self.create_report(title="Other", image=test_image("other.jpg"))
        with self.assertRaises(ValueError):
            MatchingService.compare(self.lost, another_lost)

    def test_date_point_boundaries(self):
        base = date(2026, 8, 1)
        expected = {0: 15, 1: 13, 3: 10, 7: 7, 14: 3, 15: 0}
        for days, points in expected.items():
            self.assertEqual(MatchingService.date_points(base, base + timedelta(days=days)), points)

    def test_results_are_ordered_limited_and_thresholded(self):
        close = self.found_report(title="Close match")
        self.found_report(
            title="Weak match",
            category="wallets",
            colour="Brown",
            campus_location="cafeteria",
            description="Unrelated wallet",
            item_date=date(2025, 1, 1),
            image=test_image("weak.jpg"),
        )
        results = MatchingService.find_matches(self.lost)
        self.assertEqual(results[0].found_item, close)
        self.assertTrue(all(result.total_score >= 50 for result in results))
        self.assertLessEqual(len(results), 5)

    def test_possible_matches_page_requires_owner(self):
        self.client.force_login(User.objects.create_user("other", password="StrongPass123!"))
        self.assertEqual(self.client.get(reverse("possible_matches", args=[self.lost.pk])).status_code, 403)


class AdministratorDashboardTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(
            "dashboard_staff",
            email="staff@example.invalid",
            password="StrongPass123!",
            is_staff=True,
        )
        self.report = self.create_report()

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("dashboard_home"))
        self.assertRedirects(
            response, f'{reverse("login")}?next={reverse("dashboard_home")}'
        )

    def test_staff_login_redirects_to_custom_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.staff.username, "password": "StrongPass123!"},
        )
        self.assertRedirects(response, reverse("dashboard_home"))

    def test_regular_login_redirects_to_homepage(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.owner.username, "password": "StrongPass123!"},
        )
        self.assertRedirects(response, reverse("home"))

    def test_regular_user_receives_custom_permission_denied_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dashboard_home"))
        self.assertContains(response, "Permission denied", status_code=403)

    def test_staff_dashboard_shows_required_totals(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard_home"))
        self.assertContains(response, "Administrator dashboard")
        self.assertEqual(response.context["total_users"], 2)
        self.assertEqual(response.context["total_lost"], 1)
        self.assertEqual(response.context["total_found"], 0)
        self.assertEqual(response.context["total_resolved"], 0)

    def test_staff_can_search_and_filter_reports(self):
        self.create_report(
            title="Found silver keys",
            report_type="found",
            category="keys",
            image=test_image("found-keys.jpg"),
        )
        self.client.force_login(self.staff)
        response = self.client.get(
            reverse("dashboard_reports"), {"query": "silver", "report_type": "found"}
        )
        self.assertContains(response, "Found silver keys")
        self.assertNotContains(response, "Black headphones")

    def test_staff_can_hide_and_show_report(self):
        self.client.force_login(self.staff)
        visibility_url = reverse("dashboard_report_visibility", args=[self.report.pk])
        self.assertEqual(self.client.get(visibility_url).status_code, 405)
        self.client.post(visibility_url)
        self.report.refresh_from_db()
        self.assertTrue(self.report.is_hidden)
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("report_list")), self.report.title)
        self.assertEqual(self.client.get(self.report.get_absolute_url()).status_code, 404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(self.report.get_absolute_url()).status_code, 200)

    def test_delete_uses_confirmation_and_enforces_ownership(self):
        stranger = User.objects.create_user("delete_stranger", password="StrongPass123!")
        self.client.force_login(stranger)
        delete_url = reverse("report_delete", args=[self.report.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(delete_url), "Yes, remove report")
        self.assertTrue(ItemReport.objects.filter(pk=self.report.pk).exists())
        self.client.post(delete_url)
        self.report.refresh_from_db()
        self.assertTrue(self.report.is_deleted)
        self.assertTrue(self.report.is_hidden)

    def test_staff_can_delete_any_report(self):
        self.client.force_login(self.staff)
        response = self.client.post(reverse("report_delete", args=[self.report.pk]))
        self.assertRedirects(response, reverse("dashboard_reports"))
        self.report.refresh_from_db()
        self.assertTrue(self.report.is_deleted)
        self.assertEqual(self.report.deleted_by, self.staff)

    def test_bulk_report_actions_require_staff_and_confirmation(self):
        action_url = reverse("management_report_bulk_action")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(action_url, {"action": "mark_reviewed", "report_ids[]": self.report.pk}).status_code, 403)
        self.client.force_login(self.staff)
        response = self.client.post(action_url, {"action": "mark_resolved", "report_ids[]": self.report.pk})
        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ItemReport.Status.ACTIVE)
        self.client.post(reverse("management_report_bulk_confirm"), {"action": "mark_resolved", "report_ids[]": self.report.pk})
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ItemReport.Status.RESOLVED)
        self.assertTrue(Notification.objects.filter(recipient=self.owner).exists())

    def test_bulk_review_is_idempotent_and_soft_delete_is_private(self):
        self.client.force_login(self.staff)
        payload = {"action": "mark_reviewed", "report_ids[]": [self.report.pk, 999999]}
        self.client.post(reverse("management_report_bulk_action"), payload)
        self.client.post(reverse("management_report_bulk_action"), payload)
        self.report.refresh_from_db()
        self.assertTrue(self.report.is_reviewed)
        self.client.post(reverse("management_report_bulk_confirm"), {"action": "delete", "report_ids[]": self.report.pk})
        self.client.logout()
        self.assertNotContains(self.client.get(reverse("item_list")), self.report.title)
        self.assertEqual(self.client.get(self.report.get_absolute_url()).status_code, 404)

    def test_staff_can_manage_regular_user_status(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("dashboard_users"), {"query": self.owner.username})
        self.assertContains(response, self.owner.email)
        toggle_url = reverse("dashboard_user_toggle_active", args=[self.owner.pk])
        self.assertEqual(self.client.get(toggle_url).status_code, 405)
        self.client.post(toggle_url)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)

    @override_settings(DEBUG=False)
    def test_custom_not_found_page(self):
        response = self.client.get("/this-page-does-not-exist/")
        self.assertContains(response, "Page not found", status_code=404)


class CanonicalSitemapTests(MediaTestCase):
    def test_public_canonical_routes(self):
        expected_paths = {
            "home": "/",
            "item_list": "/items/",
            "lost_item_list": "/items/lost/",
            "found_item_list": "/items/found/",
            "register": "/accounts/register/",
            "login": "/accounts/login/",
        }
        for url_name, expected_path in expected_paths.items():
            with self.subTest(url_name=url_name):
                self.assertEqual(reverse(url_name), expected_path)
                self.assertEqual(self.client.get(expected_path).status_code, 200)

    def test_item_routes_use_integer_id(self):
        report = self.create_report()
        self.assertEqual(reverse("item_detail", args=[report.pk]), f"/items/{report.pk}/")
        self.assertEqual(
            reverse("item_matches", args=[report.pk]), f"/items/{report.pk}/matches/"
        )
        self.assertEqual(self.client.get("/items/999999/").status_code, 404)

    def test_dedicated_type_lists_only_show_the_requested_type(self):
        lost = self.create_report(title="Lost calculator")
        found = self.create_report(
            report_type=ItemReport.ReportType.FOUND,
            title="Found water bottle",
            image=test_image("found.jpg", "green"),
        )
        lost_response = self.client.get(reverse("lost_item_list"))
        self.assertContains(lost_response, lost.title)
        self.assertNotContains(lost_response, found.title)
        found_response = self.client.get(reverse("found_item_list"))
        self.assertContains(found_response, found.title)
        self.assertNotContains(found_response, lost.title)

    def test_protected_canonical_routes_redirect_to_canonical_login(self):
        protected_urls = [
            reverse("my_reports"),
            reverse("item_create_lost"),
            reverse("management_dashboard"),
        ]
        for protected_url in protected_urls:
            with self.subTest(url=protected_url):
                response = self.client.get(protected_url)
                self.assertRedirects(
                    response,
                    f'{reverse("login")}?next={protected_url}',
                    fetch_redirect_response=False,
                )

    def test_explicit_error_routes_use_custom_templates(self):
        self.assertEqual(self.client.get(reverse("permission_denied_page")).status_code, 403)
        self.assertEqual(self.client.get(reverse("page_not_found_page")).status_code, 404)


class SecureContactTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.requester = User.objects.create_user("requester", password="StrongPass123!")
        self.staff = User.objects.create_user(
            "contact_admin", password="StrongPass123!", is_staff=True
        )
        self.stranger = User.objects.create_user("contact_stranger", password="StrongPass123!")
        self.found_report = self.create_report(
            report_type=ItemReport.ReportType.FOUND,
            title="Found blue headphones",
            image=test_image("contact-found.jpg", "blue"),
        )
        self.lost_report = self.create_report(
            report_type=ItemReport.ReportType.LOST,
            title="Lost library keys",
            image=test_image("contact-lost.jpg", "black"),
        )

    def request_data(self):
        return {
            "initial_message": "I can explain where the item was seen.",
            "private_details": "A private identifying detail for staff review.",
        }

    def create_contact_request(self, item_report=None, status=ContactRequest.Status.PENDING):
        item_report = item_report or self.found_report
        request_type = (
            ContactRequest.RequestType.OWNERSHIP_CLAIM
            if item_report.report_type == ItemReport.ReportType.FOUND
            else ContactRequest.RequestType.FOUND_ITEM
        )
        return ContactRequest.objects.create(
            item_report=item_report,
            requesting_user=self.requester,
            receiving_user=self.owner,
            request_type=request_type,
            status=status,
            **self.request_data(),
        )

    def approve(self, contact_request):
        """Start an old pending initiation through its participant migration path."""
        self.client.force_login(self.requester)
        response = self.client.post(
            reverse("contact_request_start", args=[contact_request.pk]),
        )
        contact_request.refresh_from_db()
        return response, contact_request.conversation

    def test_phone_validation_and_normalization(self):
        profile = UserProfile(user=self.requester, phone_number="not-a-number")
        with self.assertRaises(ValidationError):
            profile.full_clean()
        form = UserProfileForm(
            {"phone_number": "+90 (555) 123-45-67", "consent_to_share_phone": True},
            instance=UserProfile(user=self.requester),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().phone_number, "+905551234567")

    def test_registration_creates_profile_with_consent(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "profile_student",
                "email": "profile@example.invalid",
                "phone_number": "+90 555 111 22 33",
                "consent_to_share_phone": True,
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertRedirects(response, reverse("home"))
        profile = User.objects.get(username="profile_student").profile
        self.assertEqual(profile.phone_number, "+905551112233")
        self.assertTrue(profile.consent_to_share_phone)

    def test_both_request_types_and_audit_events_are_created(self):
        self.client.force_login(self.requester)
        for report, expected_type in (
            (self.found_report, ContactRequest.RequestType.OWNERSHIP_CLAIM),
            (self.lost_report, ContactRequest.RequestType.FOUND_ITEM),
        ):
            response = self.client.post(
                reverse("contact_request_create", args=[report.pk]), self.request_data()
            )
            created = ContactRequest.objects.get(item_report=report)
            self.assertRedirects(
                response,
                reverse("conversation_detail", args=[created.conversation.pk]),
                fetch_redirect_response=False,
            )
            self.assertEqual(created.request_type, expected_type)
            self.assertEqual(created.status, ContactRequest.Status.INITIATED)
        self.assertEqual(
            ContactAuditLog.objects.filter(
                event_type=ContactAuditLog.EventType.CONVERSATION_OPENED
            ).count(),
            2,
        )

    def test_self_contact_is_blocked_and_duplicate_opens_existing_conversation(self):
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("contact_request_create", args=[self.found_report.pk])).status_code,
            403,
        )
        self.client.force_login(self.requester)
        create_url = reverse("contact_request_create", args=[self.found_report.pk])
        self.client.post(create_url, self.request_data())
        response = self.client.post(create_url, self.request_data())
        conversation = Conversation.objects.get(item_report=self.found_report)
        self.assertRedirects(response, reverse("conversation_detail", args=[conversation.pk]))
        self.assertEqual(ContactRequest.objects.count(), 1)

    def test_requester_can_cancel_only_pending_request(self):
        contact_request = self.create_contact_request()
        self.client.force_login(self.requester)
        response = self.client.post(reverse("contact_request_cancel", args=[contact_request.pk]))
        contact_request.refresh_from_db()
        self.assertEqual(contact_request.status, ContactRequest.Status.CANCELLED)
        self.assertRedirects(response, reverse("contact_requests_sent"))
        self.assertTrue(
            ContactAuditLog.objects.filter(
                event_type=ContactAuditLog.EventType.REQUEST_CANCELLED
            ).exists()
        )

    def test_message_thread_read_state_and_soft_delete(self):
        contact_request = self.create_contact_request()
        _, conversation = self.approve(contact_request)
        self.client.force_login(self.requester)
        self.client.post(reverse("conversation_detail", args=[conversation.pk]), {"body": "First"})
        self.client.post(reverse("conversation_detail", args=[conversation.pk]), {"body": "Second"})
        self.assertEqual(
            list(conversation.messages.values_list("body", flat=True)),
            [self.request_data()["initial_message"], "First", "Second"],
        )
        first_message = conversation.messages.filter(body="First").get()
        self.client.force_login(self.owner)
        self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        first_message.refresh_from_db()
        self.assertIsNotNone(first_message.read_at)
        self.client.force_login(self.requester)
        self.client.post(reverse("message_delete", args=[first_message.pk]))
        first_message.refresh_from_db()
        self.assertTrue(first_message.is_deleted)
        self.assertEqual(first_message.body, "")

    def test_conversation_membership_and_old_pending_explicit_start(self):
        pending_request = self.create_contact_request()
        self.assertFalse(Conversation.objects.filter(approved_contact_request=pending_request).exists())
        _, conversation = self.approve(pending_request)
        self.client.force_login(self.stranger)
        self.assertEqual(
            self.client.get(reverse("conversation_detail", args=[conversation.pk])).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("contact_request_detail", args=[pending_request.pk])).status_code,
            403,
        )

    def test_report_owner_can_start_an_old_pending_initiation(self):
        pending_request = self.create_contact_request()
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("contact_request_start", args=[pending_request.pk])
        )
        pending_request.refresh_from_db()
        conversation = pending_request.conversation
        self.assertRedirects(
            response,
            reverse("conversation_detail", args=[conversation.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(pending_request.status, ContactRequest.Status.INITIATED)
        self.assertEqual(conversation.messages.get().sender, self.requester)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.requester,
                notification_type=Notification.NotificationType.NEW_MESSAGE,
            ).exists()
        )

    def test_phone_visibility_and_consent_revocation(self):
        UserProfile.objects.update_or_create(
            user=self.owner,
            defaults={
                "phone_number": "+905551112233",
                "consent_to_share_phone": True,
                "mask_phone_number": True,
            },
        )
        contact_request = self.create_contact_request()
        _, conversation = self.approve(contact_request)
        self.client.force_login(self.requester)
        response = self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertContains(response, "••••••2233")
        self.assertNotContains(response, "+905551112233")
        profile = self.owner.profile
        profile.mask_phone_number = False
        profile.save(update_fields=["mask_phone_number"])
        response = self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertContains(response, "+905551112233")
        profile.consent_to_share_phone = False
        profile.save(update_fields=["consent_to_share_phone"])
        response = self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertNotContains(response, "+905551112233")
        self.assertContains(response, "chosen not to share their phone number")

    def test_all_messages_appear_immediately_in_chronological_order(self):
        contact_request = self.create_contact_request()
        _, conversation = self.approve(contact_request)
        first = Message.objects.create(
            conversation=conversation,
            sender=self.requester,
            body="First visible message",
        )
        second = Message.objects.create(
            conversation=conversation,
            sender=self.owner,
            body="Second visible message",
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertContains(response, first.body)
        self.assertContains(response, second.body)
        self.assertLess(response.content.index(first.body.encode()), response.content.index(second.body.encode()))
        self.assertNotContains(response, "Apply filter")

    def test_url_guessing_cannot_delete_unrelated_messages(self):
        contact_request = self.create_contact_request()
        _, conversation = self.approve(contact_request)
        message = Message.objects.create(
            conversation=conversation, sender=self.requester, body="Participant message"
        )
        self.client.force_login(self.stranger)
        self.assertEqual(
            self.client.post(reverse("message_delete", args=[message.pk])).status_code,
            404,
        )

    def test_report_owner_block_prevents_new_conversation(self):
        UserBlock.objects.create(blocker=self.owner, blocked_user=self.requester)
        self.client.force_login(self.requester)
        response = self.client.post(
            reverse("contact_request_create", args=[self.found_report.pk]),
            self.request_data(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Conversation.objects.exists())

    def test_admin_deactivation_requires_reason_and_blocks_messages_and_phone_access(self):
        UserProfile.objects.update_or_create(
            user=self.owner,
            defaults={"phone_number": "+905551112233", "consent_to_share_phone": True},
        )
        contact_request = self.create_contact_request()
        _, conversation = self.approve(contact_request)
        self.client.force_login(self.staff)
        deactivate_url = reverse("management_conversation_deactivate", args=[conversation.pk])
        response = self.client.post(deactivate_url, {"reason": ""})
        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.DealStatus.ACTIVE)
        self.client.post(
            deactivate_url,
            {"reason": "Participants requested an administrative pause."},
        )
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.DealStatus.DEACTIVATED)
        self.assertFalse(conversation.is_active)
        self.assertEqual(conversation.deactivated_by, self.staff)
        self.assertIsNotNone(conversation.deactivated_at)
        self.assertEqual(
            Notification.objects.filter(
                notification_type=Notification.NotificationType.CONVERSATION_DEACTIVATED
            ).count(),
            2,
        )
        self.client.force_login(self.requester)
        view_response = self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        self.assertContains(view_response, "Conversation deactivated")
        self.assertNotContains(view_response, "+905551112233")
        response = self.client.post(
            reverse("conversation_detail", args=[conversation.pk]), {"body": "Blocked"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Message.objects.filter(body="Blocked").exists())

    def test_audit_descriptions_exclude_private_values(self):
        contact_request = self.create_contact_request()
        self.approve(contact_request)
        descriptions = " ".join(ContactAuditLog.objects.values_list("description", flat=True))
        self.assertNotIn(contact_request.initial_message, descriptions)
        self.assertNotIn(contact_request.private_details, descriptions)

    def test_normal_users_cannot_access_contact_management(self):
        self.client.force_login(self.requester)
        for url_name in (
            "management_conversations",
            "management_audit_log",
        ):
            with self.subTest(url_name=url_name):
                self.assertEqual(self.client.get(reverse(url_name)).status_code, 403)

    def test_message_notification_is_private_and_marked_read_on_open(self):
        contact_request = self.create_contact_request()
        _, conversation = self.approve(contact_request)
        self.client.force_login(self.requester)
        self.client.post(reverse("conversation_detail", args=[conversation.pk]), {"body": "Hello"})
        notification = Notification.objects.filter(
            recipient=self.owner, notification_type="new_message"
        ).latest("created_at")
        self.assertFalse(notification.is_read)
        self.assertFalse(Notification.objects.filter(recipient=self.requester, notification_type="new_message").exists())
        self.client.force_login(self.owner)
        self.client.get(reverse("conversation_detail", args=[conversation.pk]))
        notification.refresh_from_db()
        self.assertTrue(notification.is_read)

    def test_only_receiver_completes_deal_and_duplicate_post_is_idempotent(self):
        contact_request = self.create_contact_request()
        _, conversation = self.approve(contact_request)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse("conversation_complete", args=[conversation.pk])).status_code, 403)
        self.client.force_login(self.requester)
        complete_url = reverse("conversation_complete", args=[conversation.pk])
        self.client.post(complete_url)
        conversation.refresh_from_db()
        self.found_report.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.DealStatus.COMPLETED)
        self.assertFalse(conversation.is_active)
        self.assertEqual(self.found_report.status, ItemReport.Status.RESOLVED)
        count = Notification.objects.filter(notification_type="deal_completed").count()
        self.client.post(complete_url)
        self.assertEqual(Notification.objects.filter(notification_type="deal_completed").count(), count)
        self.assertEqual(self.client.post(reverse("conversation_detail", args=[conversation.pk]), {"body": "Blocked"}).status_code, 403)

    def test_staff_reopen_requires_reason_and_can_reactivate_report(self):
        contact_request = self.create_contact_request()
        _, conversation = self.approve(contact_request)
        self.client.force_login(self.requester)
        self.client.post(reverse("conversation_complete", args=[conversation.pk]))
        self.client.force_login(self.staff)
        reopen_url = reverse("management_conversation_reopen", args=[conversation.pk])
        self.assertEqual(self.client.post(reopen_url, {"reason": "", "change_report_status": "on"}).status_code, 200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.DealStatus.COMPLETED)
        self.client.post(reopen_url, {"reason": "The participants reported a mistake.", "change_report_status": "on"})
        conversation.refresh_from_db()
        self.found_report.refresh_from_db()
        self.assertEqual(conversation.status, Conversation.DealStatus.ACTIVE)
        self.assertTrue(conversation.is_active)
        self.assertEqual(self.found_report.status, ItemReport.Status.ACTIVE)

    def test_notification_endpoints_are_owner_scoped(self):
        own = Notification.objects.create(recipient=self.requester, notification_type="admin_notice", title="Private update", safe_message="Safe account update.", deduplication_key="owner-test")
        foreign = Notification.objects.create(recipient=self.owner, notification_type="admin_notice", title="Other update", safe_message="Not for requester.", deduplication_key="foreign-test")
        self.client.force_login(self.requester)
        payload = self.client.get(reverse("notification_unread_count")).json()
        self.assertEqual(payload["unread_count"], 1)
        self.assertEqual(payload["notifications"][0]["id"], own.pk)
        self.assertEqual(self.client.post(reverse("notification_mark_read", args=[foreign.pk])).status_code, 404)


class AIAssistantTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(
            "assistant_staff", password="StrongPass123!", is_staff=True
        )
        self.superuser = User.objects.create_superuser(
            "assistant_superuser", "root@example.invalid", "StrongPass123!"
        )
        self.report = self.create_report(
            description="Black headphones. Contact me at student@example.com or +90 555 123 45 67."
        )

    def enable_capability(self, code):
        settings_record = AIAssistantSettings.get_solo()
        settings_record.is_enabled = True
        settings_record.save(update_fields=["is_enabled", "updated_at"])
        capability = AICapability.objects.get(code=code)
        capability.is_available = True
        capability.save(update_fields=["is_available", "updated_at"])
        setting = AICapabilitySetting.objects.get(capability=capability)
        setting.is_enabled = True
        setting.save(update_fields=["is_enabled", "updated_at"])
        return capability

    def test_seeded_configuration_has_stable_capabilities_and_one_setting_each(self):
        self.assertEqual(AICapability.objects.count(), 8)
        self.assertEqual(AICapabilitySetting.objects.count(), 8)
        self.assertEqual(AICapability.objects.values("code").distinct().count(), 8)
        self.assertFalse(AIAssistantSettings.get_solo().is_enabled)

    def test_only_staff_can_access_and_disabled_master_rejects_execution(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("management_ai_assistant")).status_code, 403)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("management_ai_assistant"))
        self.assertContains(response, "The AI Assistant is currently disabled.")
        response = self.client.post(
            reverse("management_ai_assistant"),
            {"form_action": "execute", "capability": "analytics_insights"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            AICapabilityAuditLog.objects.filter(event_type="request_blocked").exists()
        )

    def test_global_settings_require_permission_and_enabled_master_requires_capability(self):
        self.client.force_login(self.staff)
        self.assertEqual(
            self.client.get(reverse("management_ai_assistant_settings")).status_code, 403
        )
        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("management_ai_assistant_settings"),
            {
                "is_enabled": "on",
                "provider_name": "Local deterministic provider",
                "model_name": "findmatch-local-v1",
                "request_timeout_seconds": 15,
                "maximum_input_length": 5000,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Enable at least one capability")
        self.assertFalse(AIAssistantSettings.get_solo().is_enabled)
        capability = AICapability.objects.get(code="analytics_insights")
        response = self.client.post(
            reverse("management_ai_assistant_settings"),
            {
                "is_enabled": "on",
                "provider_name": "Local deterministic provider",
                "model_name": "findmatch-local-v1",
                "request_timeout_seconds": 15,
                "maximum_input_length": 5000,
                "enabled_capabilities": [capability.pk],
            },
        )
        self.assertRedirects(response, reverse("management_ai_assistant_settings"))
        self.assertTrue(AIAssistantSettings.get_solo().is_enabled)

    def test_personal_override_can_disable_but_not_enable_globally_disabled(self):
        enabled = self.enable_capability("report_summarization")
        self.assertTrue(AICapabilityService.is_enabled(self.staff, enabled.code))
        AICapabilityService.update_override(
            user=self.staff,
            capability=enabled,
            setting=AdminCapabilityOverride.OverrideSetting.DISABLED,
        )
        self.assertFalse(AICapabilityService.is_enabled(self.staff, enabled.code))
        disabled = AICapability.objects.get(code="conversation_summarization")
        AICapabilitySetting.objects.filter(capability=disabled).update(is_enabled=False)
        with self.assertRaises(ValidationError):
            AICapabilityService.update_override(
                user=self.staff,
                capability=disabled,
                setting=AdminCapabilityOverride.OverrideSetting.ENABLED,
            )

    def test_report_summary_redacts_contact_data_and_never_mutates_report(self):
        self.enable_capability("report_summarization")
        original_status = self.report.status
        result = AIAssistantService.execute(
            user=self.staff,
            capability_code="report_summarization",
            reports=[self.report],
        )
        self.assertNotIn("student@example.com", result.content)
        self.assertNotIn("+90 555 123 45 67", result.content)
        self.assertIn("[email removed]", result.content)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, original_status)
        audit_text = " ".join(
            AICapabilityAuditLog.objects.values_list("safe_description", flat=True)
        )
        self.assertNotIn("student@example.com", audit_text)

    def test_matching_insight_uses_deterministic_service_and_disclaims_ownership(self):
        self.enable_capability("matching_insights")
        found = self.create_report(
            report_type=ItemReport.ReportType.FOUND,
            title="Found black headphones",
            image=test_image("assistant-found.jpg"),
        )
        result = AIAssistantService.execute(
            user=self.staff,
            capability_code="matching_insights",
            reports=[self.report, found],
        )
        expected = MatchingService.compare(self.report, found)
        self.assertIn(f"{expected.total_score}/100", result.title)
        self.assertIn("never proves ownership", result.disclaimer)

    def test_conversation_summary_uses_all_non_deleted_messages(self):
        self.enable_capability("conversation_summarization")
        participant = User.objects.create_user(
            "assistant_participant", password="StrongPass123!"
        )
        contact_request = ContactRequest.objects.create(
            item_report=self.report,
            requesting_user=participant,
            receiving_user=self.owner,
            request_type=ContactRequest.RequestType.OWNERSHIP_CLAIM,
            initial_message="Private request",
            private_details="Private evidence",
            status=ContactRequest.Status.APPROVED,
        )
        conversation = Conversation.objects.create(
            item_report=self.report,
            approved_contact_request=contact_request,
            first_participant=participant,
            second_participant=self.owner,
        )
        Message.objects.create(
            conversation=conversation,
            sender=participant,
            body="Where should we meet?",
        )
        Message.objects.create(
            conversation=conversation,
            sender=participant,
            body="Second immediate question?",
        )

        result = AIAssistantService.execute(
            user=self.staff,
            capability_code="conversation_summarization",
            conversation=conversation,
        )
        self.assertIn("Where should we meet?", result.content)
        self.assertIn("Second immediate question", result.content)

    def test_settings_model_contains_no_api_key_field(self):
        field_names = {field.name for field in AIAssistantSettings._meta.fields}
        self.assertNotIn("api_key", field_names)
        self.assertNotIn("secret", field_names)


class NotificationBellTemplateTests(MediaTestCase):
    def test_zero_and_unread_badge_states_preserve_dropdown_button(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        zero_state = render_to_string(
            "includes/notification_center.html",
            {"notification_unread_count": 0, "notification_preview": []},
            request=request,
        )
        unread_state = render_to_string(
            "includes/notification_center.html",
            {"notification_unread_count": 7, "notification_preview": []},
            request=request,
        )
        self.assertIn("notification-count d-none", zero_state)
        self.assertNotIn("notification-count d-none", unread_state)
        self.assertIn(">7</span>", unread_state)
        self.assertIn('data-bs-toggle="dropdown"', zero_state)
        self.assertIn('data-bs-toggle="dropdown"', unread_state)
        self.assertIn("notification-bell-button", zero_state)


class SeedDataTests(MediaTestCase):
    def test_command_is_repeatable(self):
        call_command("seed_data", verbosity=0)
        first_counts = (User.objects.count(), ItemReport.objects.count())
        call_command("seed_data", verbosity=0)
        self.assertEqual((User.objects.count(), ItemReport.objects.count()), first_counts)
        self.assertGreaterEqual(ItemReport.objects.filter(report_type="lost").count(), 1)
        self.assertGreaterEqual(ItemReport.objects.filter(report_type="found").count(), 1)

# Create your tests here.
