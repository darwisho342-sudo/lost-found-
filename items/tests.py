from datetime import date, timedelta
from io import BytesIO
import importlib.util
from tempfile import TemporaryDirectory

from django.contrib.auth.models import AnonymousUser, Permission, User
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext, ngettext
from PIL import Image

from .forms import ItemReportForm, UserProfileForm
from .choices import ITEM_TYPE_CHOICES, brand_choices_for
from .models import (
    MAX_IMAGE_SIZE,
    ContactAuditLog,
    ContactRequest,
    ClaimAnswer,
    HandoverConfirmation,
    Conversation,
    ItemReport,
    Message,
    Notification,
    PrivateVerificationQuestion,
    UserBlock,
    UserProfile,
    UniversityLocation,
    validate_image_size,
)
from .services import MatchingService


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
            username="student", email="student@st.biruni.edu.tr", password="StrongPass123!"
        )
        UserProfile.objects.create(
            user=self.owner, email_verified_at=timezone.now(),
            university_eligible=True, preferred_scope=ItemReport.Scope.UNIVERSITY,
        )
        self.university_location = UniversityLocation.objects.create(
            campus="Main Campus",
            building="Library",
            general_area="Library",
            location_type=ItemReport.CampusLocation.LIBRARY,
        )

    def force_login_recently(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["findmatch_recent_auth"] = int(timezone.now().timestamp())
        session.save()

    def create_report(self, **overrides):
        requested_campus_location = overrides.get(
            "campus_location", ItemReport.CampusLocation.LIBRARY
        )
        university_location = overrides.pop("university_location", None)
        if university_location is None:
            default_location = getattr(self, "university_location", None)
            if (
                default_location is not None
                and default_location.location_type == requested_campus_location
            ):
                university_location = default_location
            else:
                location_label = ItemReport.CampusLocation(requested_campus_location).label
                university_location, _ = UniversityLocation.objects.get_or_create(
                    campus="Main Campus",
                    location_type=requested_campus_location,
                    defaults={"general_area": location_label},
                )
        data = {
            "owner": self.owner,
            "report_type": ItemReport.ReportType.LOST,
            "title": "Black headphones",
            "description": "Black wireless headphones in a hard case",
            "category": ItemReport.Category.ELECTRONICS,
            "colour": "Black",
            "campus_location": ItemReport.CampusLocation.LIBRARY,
            "university_location": university_location,
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
                "email": "new@st.biruni.edu.tr",
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
            "university_location": str(self.university_location.pk),
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
        staff = User.objects.create_user(
            "staff", email="staff@st.biruni.edu.tr", password="StrongPass123!", is_staff=True
        )
        UserProfile.objects.create(
            user=staff, email_verified_at=timezone.now(), university_eligible=True
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("report_edit", args=[report.pk])).status_code, 200)

    def test_university_owner_can_close_but_not_resolve_reports(self):
        self.client.force_login(self.owner)
        university_report = self.create_report(title="Report resolved", image=test_image("resolved.jpg"))
        self.assertEqual(
            self.client.post(reverse("change_status", args=[university_report.pk, "resolved"])).status_code,
            403,
        )
        report = self.create_report(title="Report closed", image=test_image("closed.jpg"))
        response = self.client.post(reverse("change_status", args=[report.pk, "closed"]))
        self.assertRedirects(response, report.get_absolute_url())
        report.refresh_from_db()
        self.assertEqual(report.status, ItemReport.Status.CLOSED)

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
        self.lost = self.create_report(
            item_date=date(2026, 8, 1), item_type="headphones", primary_colour="black",
            material="plastic", approximate_size="medium", brand="sony", model="WH1000",
            country="Türkiye", region="Marmara", city="Istanbul", district="Fatih",
            place_type="university_school", place_name="Central Library",
            latitude=41.008, longitude=28.978,
        )

    def found_report(self, **overrides):
        data = {
            "owner": self.owner,
            "report_type": "found",
            "title": "Headphones found",
            "item_date": date(2026, 8, 2),
            "image": test_image("found.jpg"),
            "item_type": "headphones", "primary_colour": "black",
            "material": "plastic", "approximate_size": "medium", "brand": "sony", "model": "WH1000",
            "country": "Türkiye", "region": "Marmara", "city": "Istanbul", "district": "Fatih",
            "place_type": "university_school", "place_name": "Central Library",
            "latitude": 41.008, "longitude": 28.978,
        }
        data.update(overrides)
        return self.create_report(**data)

    def test_identical_details_score_correctly(self):
        found = self.found_report()
        result = MatchingService.compare(self.lost, found)
        self.assertEqual(result.category_points, 15)
        self.assertGreater(result.title_points, 0)
        self.assertEqual(result.description_points, 15)
        self.assertEqual(result.primary_colour_points, 10)
        self.assertEqual(result.location_points, 10)
        self.assertEqual(result.date_points, 8)

    def test_same_report_types_are_rejected(self):
        another_lost = self.create_report(title="Other", image=test_image("other.jpg"))
        with self.assertRaises(ValueError):
            MatchingService.compare(self.lost, another_lost)

    def test_date_point_boundaries(self):
        base = date(2026, 8, 1)
        expected = {0: 10, 1: 8, 3: 5, 7: 5, 14: 2, 15: 0}
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
        self.assertTrue(all(result.total_score >= 70 for result in results))
        self.assertLessEqual(len(results), 5)

    def test_possible_matches_page_requires_owner(self):
        self.client.force_login(User.objects.create_user("other", password="StrongPass123!"))
        self.assertEqual(self.client.get(reverse("possible_matches", args=[self.lost.pk])).status_code, 403)


class StructuredReportAndOwnershipTests(MediaTestCase):
    def structured_data(self, **overrides):
        data = {
            "title": "Lost Black Mobile Phone", "category": "electronics",
            "item_type": "mobile_phone", "primary_colour": "black",
            "secondary_colour": "", "material": "", "approximate_size": "",
            "pattern": "", "item_condition": "", "brand": "samsung",
            "custom_brand": "", "model": "Galaxy S",
            "university_location": str(self.university_location.pk),
            "item_date": date.today().isoformat(),
            "country": "Türkiye", "region": "Marmara", "city": "Istanbul",
            "district": "Fatih", "place_type": "university_school", "place_name": "Central Library",
            "public_location": "Central district", "public_location_precision_km": "5",
            "additional_details": "Black case", "require_official_handover": "",
        }
        data.update(overrides)
        return data

    def found_report(self):
        report = self.create_report(
            report_type="found", title="Found phone", item_type="mobile_phone",
            primary_colour="black", brand="samsung", model="Galaxy S",
        )
        question = PrivateVerificationQuestion.objects.create(
            item_report=report, question_type="hidden_mark",
            question_text="Describe the hidden mark", expected_answer="Tiny star under case",
        )
        return report, question

    def test_every_category_item_type_pair_is_valid(self):
        for category, choices in ITEM_TYPE_CHOICES.items():
            for item_type, label in choices:
                relevant_brands = [
                    value for value, choice_label in brand_choices_for(category, item_type)
                    if value not in {"other", "not_sure", "no_visible_brand"}
                ]
                form = ItemReportForm(
                    data=self.structured_data(
                        category=category, item_type=item_type,
                        custom_item_type="Custom item" if item_type == "other" else "",
                        brand=relevant_brands[0] if relevant_brands else "",
                    ), files={"image": test_image(f"{category}-{item_type}.jpg")}, report_type="lost",
                )
                self.assertTrue(form.is_valid(), (category, item_type, form.errors))

    def test_invalid_category_item_type_is_rejected(self):
        form = ItemReportForm(data=self.structured_data(category="bags", item_type="mobile_phone"), files={"image": test_image()}, report_type="lost")
        self.assertFalse(form.is_valid())
        self.assertIn("item_type", form.errors)

    def test_other_requires_custom_value_and_optional_fields_stay_optional(self):
        invalid = ItemReportForm(data=self.structured_data(item_type="other", custom_item_type=""), files={"image": test_image()}, report_type="lost")
        self.assertIn("custom_item_type", invalid.errors)
        valid = ItemReportForm(data=self.structured_data(item_type="other", custom_item_type="Music player", brand="", model="", additional_details=""), files={"image": test_image()}, report_type="lost")
        self.assertTrue(valid.is_valid(), valid.errors)

    def test_sensitive_public_content_is_blocked(self):
        form = ItemReportForm(data=self.structured_data(additional_details="password: secret123"), files={"image": test_image()}, report_type="lost")
        self.assertFalse(form.is_valid())
        self.assertIn("sensitive", str(form.errors["additional_details"]).lower())

    def test_automatic_title_is_generated_when_blank(self):
        form = ItemReportForm(data=self.structured_data(title=""), files={"image": test_image()}, report_type="lost")
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIn("Samsung", form.save(commit=False).title)

    def test_private_question_never_appears_publicly(self):
        report, question = self.found_report()
        response = self.client.get(report.get_absolute_url())
        self.assertNotContains(response, question.question_text)
        self.assertNotContains(response, question.expected_answer)

    def test_claim_requires_login_and_prevents_self_claim(self):
        report, question = self.found_report()
        url = reverse("contact_request_create", args=(report.pk,))
        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(url).status_code, 403)

    def submit_claim(self, report, question, claimant):
        self.client.force_login(claimant)
        return self.client.post(reverse("contact_request_create", args=(report.pk,)), {
            "initial_message": "I believe this is mine", "loss_location": "Library second floor",
            "loss_timeframe": "Yesterday afternoon", "truthful_confirmation": "on",
            f"question_{question.pk}": "A star under the case",
        })

    def test_claim_answers_are_private_and_finder_can_approve(self):
        report, question = self.found_report()
        claimant = User.objects.create_user("claimant", email="claimant@st.biruni.edu.tr", password="StrongPass123!")
        UserProfile.objects.create(user=claimant, email_verified_at=timezone.now(), university_eligible=True)
        response = self.submit_claim(report, question, claimant)
        claim = ContactRequest.objects.get(requesting_user=claimant)
        self.assertRedirects(response, reverse("contact_request_detail", args=(claim.pk,)))
        self.assertEqual(ClaimAnswer.objects.get(contact_request=claim).answer, "A star under the case")
        stranger = User.objects.create_user("stranger_claim", password="StrongPass123!")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(reverse("contact_request_detail", args=(claim.pk,))).status_code, 403)
        self.client.force_login(claimant)
        self.assertNotContains(self.client.get(reverse("contact_request_detail", args=(claim.pk,))), question.expected_answer)
        self.force_login_recently(self.owner)
        self.client.post(reverse("claim_action", args=(claim.pk, "approve")))
        claim.refresh_from_db()
        self.assertEqual(claim.status, ContactRequest.Status.APPROVED)
        self.assertTrue(hasattr(claim, "conversation"))

    def test_duplicate_claim_and_resolved_report_are_rejected(self):
        report, question = self.found_report()
        claimant = User.objects.create_user("duplicate_claimant", email="duplicate@st.biruni.edu.tr", password="StrongPass123!")
        UserProfile.objects.create(user=claimant, email_verified_at=timezone.now(), university_eligible=True)
        self.submit_claim(report, question, claimant)
        second = self.submit_claim(report, question, claimant)
        self.assertEqual(ContactRequest.objects.filter(requesting_user=claimant).count(), 1)
        report.status = ItemReport.Status.RESOLVED
        report.save()
        other = User.objects.create_user("late_claimant", email="late@st.biruni.edu.tr", password="StrongPass123!")
        UserProfile.objects.create(user=other, email_verified_at=timezone.now(), university_eligible=True)
        response = self.submit_claim(report, question, other)
        self.assertEqual(ContactRequest.objects.filter(requesting_user=other).count(), 0)

    def test_two_party_handover_resolves_report(self):
        report, question = self.found_report()
        claimant = User.objects.create_user("handover_claimant", email="handover@st.biruni.edu.tr", password="StrongPass123!")
        UserProfile.objects.create(user=claimant, email_verified_at=timezone.now(), university_eligible=True)
        self.submit_claim(report, question, claimant)
        claim = ContactRequest.objects.get(requesting_user=claimant)
        self.force_login_recently(self.owner)
        self.client.post(reverse("claim_action", args=(claim.pk, "approve")))
        self.client.force_login(claimant)
        self.client.post(reverse("claim_handover_confirm", args=(claim.pk,)))
        claim.refresh_from_db(); report.refresh_from_db()
        self.assertEqual(claim.status, ContactRequest.Status.APPROVED)
        self.assertEqual(report.status, ItemReport.Status.CLAIM_IN_PROGRESS)
        self.client.force_login(self.owner)
        self.client.post(reverse("claim_handover_confirm", args=(claim.pk,)))
        claim.refresh_from_db(); report.refresh_from_db()
        self.assertEqual(claim.status, ContactRequest.Status.APPROVED)
        self.assertEqual(report.status, ItemReport.Status.CLAIM_IN_PROGRESS)
        self.assertEqual(HandoverConfirmation.objects.filter(contact_request=claim).count(), 2)

    def test_matching_ignores_private_answers_and_wrong_direction_dates(self):
        lost = self.create_report(item_type="mobile_phone", primary_colour="black", report_type="lost", item_date=date.today())
        found, question = self.found_report()
        found.item_date = date.today() - timedelta(days=5); found.save()
        baseline = MatchingService.compare(lost, found).total_score
        question.expected_answer = "black headphones library samsung secret"; question.save()
        self.assertEqual(MatchingService.compare(lost, found).total_score, baseline)
        self.assertEqual(MatchingService.compare(lost, found).date_points, 0)


class AdministratorDashboardTests(MediaTestCase):
    def setUp(self):
        super().setUp()
        self.staff = User.objects.create_user(
            "dashboard_staff",
            email="dashboard.staff@st.biruni.edu.tr",
            password="StrongPass123!",
            is_staff=True,
        )
        UserProfile.objects.create(
            user=self.staff, email_verified_at=timezone.now(), university_eligible=True
        )
        self.staff.user_permissions.add(Permission.objects.get(codename="manage_custody"))
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

    def test_every_staff_page_uses_the_shared_independent_scroll_shell(self):
        self.client.force_login(self.staff)
        staff_pages = (
            "management_dashboard", "management_reports", "management_users",
            "management_claims", "management_moderation", "management_locations",
            "management_custody", "management_conversations", "management_audit_log",
        )
        for page_name in staff_pages:
            with self.subTest(page=page_name):
                response = self.client.get(reverse(page_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'class="admin-body sidebar-layout"')
                self.assertContains(response, 'class="admin-layout app-shell"')
                self.assertContains(response, 'class="admin-sidebar sidebar"')
                self.assertContains(response, 'class="admin-main main-section"')
                self.assertContains(response, 'class="admin-page main-content"')
                self.assertContains(response, 'data-admin-sidebar-open')
                self.assertContains(response, 'data-admin-sidebar-close')
                self.assertNotContains(response, 'id="mobileAdminMenu"')

    def test_shared_sidebar_assets_define_desktop_mobile_and_rtl_behaviour(self):
        css = (settings.BASE_DIR / "static/css/management/management-base.css").read_text(encoding="utf-8")
        javascript = (settings.BASE_DIR / "static/js/management-shell.js").read_text(encoding="utf-8")
        for rule in (
            "height: 100dvh", "overflow-y: auto", "overflow-x: hidden",
            "min-height: 0", "overscroll-behavior: contain", "scrollbar-gutter: stable",
            'html[dir="rtl"] .admin-sidebar', ".admin-body.admin-sidebar-open .admin-page",
        ):
            self.assertIn(rule, css)
        for behaviour in ("admin-sidebar-open", "Escape", "aria-expanded", "sidebar.inert"):
            self.assertIn(behaviour, javascript)
        self.client.force_login(self.staff)
        with translation.override("en"):
            arabic = self.client.get("/ar/management/")
            self.assertContains(arabic, '<html lang="ar" dir="rtl">')
            self.assertContains(arabic, 'id="adminSidebar"')

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
        self.force_login_recently(self.staff)
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
        self.force_login_recently(self.staff)
        response = self.client.post(reverse("report_delete", args=[self.report.pk]))
        self.assertRedirects(response, reverse("dashboard_reports"))
        self.report.refresh_from_db()
        self.assertTrue(self.report.is_deleted)
        self.assertEqual(self.report.deleted_by, self.staff)

    def test_bulk_report_actions_require_staff_and_confirmation(self):
        action_url = reverse("management_report_bulk_action")
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(action_url, {"action": "mark_reviewed", "report_ids[]": self.report.pk}).status_code, 403)
        self.force_login_recently(self.staff)
        response = self.client.post(action_url, {"action": "mark_resolved", "report_ids[]": self.report.pk})
        self.assertEqual(response.status_code, 200)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ItemReport.Status.ACTIVE)
        self.client.post(reverse("management_report_bulk_confirm"), {"action": "mark_resolved", "report_ids[]": self.report.pk})
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ItemReport.Status.RESOLVED)
        self.assertTrue(Notification.objects.filter(recipient=self.owner).exists())

    def test_bulk_review_is_idempotent_and_soft_delete_is_private(self):
        self.force_login_recently(self.staff)
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
        self.force_login_recently(self.staff)
        response = self.client.get(reverse("dashboard_users"), {"query": self.owner.username})
        self.assertContains(response, self.owner.email)
        toggle_url = reverse("dashboard_user_toggle_active", args=[self.owner.pk])
        self.assertEqual(self.client.get(toggle_url).status_code, 405)
        self.client.post(toggle_url, {"reason": "Repeated abuse confirmed by a human moderator."})
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_active)
        self.assertTrue(ContactAuditLog.objects.filter(event_type=ContactAuditLog.EventType.USER_SUSPENDED).exists())

    @override_settings(DEBUG=False)
    def test_custom_not_found_page(self):
        response = self.client.get("/this-page-does-not-exist/")
        self.assertContains(response, "Page not found", status_code=404)


class CanonicalSitemapTests(MediaTestCase):
    def test_public_canonical_routes(self):
        expected_paths = {
            "home": "/en/",
            "item_list": "/en/items/",
            "lost_item_list": "/en/items/lost/",
            "found_item_list": "/en/items/found/",
            "register": "/en/accounts/register/",
            "login": "/en/accounts/login/",
        }
        for url_name, expected_path in expected_paths.items():
            with self.subTest(url_name=url_name):
                self.assertEqual(reverse(url_name), expected_path)
                self.assertEqual(self.client.get(expected_path).status_code, 200)

    def test_item_routes_use_integer_id(self):
        report = self.create_report()
        self.assertEqual(reverse("item_detail", args=[report.pk]), f"/en/items/{report.pk}/")
        self.assertEqual(
            reverse("item_matches", args=[report.pk]), f"/en/items/{report.pk}/matches/"
        )
        self.assertEqual(self.client.get("/en/items/999999/").status_code, 404)

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
        self.requester = User.objects.create_user("requester", email="requester@st.biruni.edu.tr", password="StrongPass123!")
        self.staff = User.objects.create_user(
            "contact_admin", password="StrongPass123!", is_staff=True
        )
        self.stranger = User.objects.create_user("contact_stranger", email="stranger@st.biruni.edu.tr", password="StrongPass123!")
        for user in (self.requester, self.stranger):
            UserProfile.objects.create(user=user, email_verified_at=timezone.now(), university_eligible=True)
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

    def ownership_claim_data(self):
        return {
            "initial_message": "I can explain where the item was seen.",
            "loss_location": "Library",
            "loss_timeframe": "Yesterday afternoon",
            "truthful_confirmation": "on",
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
        profile = self.requester.profile
        profile.phone_number = "not-a-number"
        with self.assertRaises(ValidationError):
            profile.full_clean()
        form = UserProfileForm(
            {"phone_number": "+90 (555) 123-45-67", "consent_to_share_phone": True},
            instance=profile,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().phone_number, "+905551234567")

    def test_registration_creates_profile_with_consent(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "profile_student",
                "email": "profile@st.biruni.edu.tr",
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
                reverse("contact_request_create", args=[report.pk]),
                self.ownership_claim_data() if report.report_type == ItemReport.ReportType.FOUND else self.request_data(),
            )
            created = ContactRequest.objects.get(item_report=report)
            self.assertEqual(created.request_type, expected_type)
            if report.report_type == ItemReport.ReportType.FOUND:
                self.assertRedirects(response, reverse("contact_request_detail", args=[created.pk]), fetch_redirect_response=False)
                self.assertEqual(created.status, ContactRequest.Status.PENDING)
            else:
                self.assertRedirects(response, reverse("conversation_detail", args=[created.conversation.pk]), fetch_redirect_response=False)
                self.assertEqual(created.status, ContactRequest.Status.INITIATED)
        self.assertEqual(
            ContactAuditLog.objects.filter(
                event_type=ContactAuditLog.EventType.CONVERSATION_OPENED
            ).count(),
            1,
        )

    def test_self_contact_is_blocked_and_duplicate_opens_existing_conversation(self):
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("contact_request_create", args=[self.found_report.pk])).status_code,
            403,
        )
        self.client.force_login(self.requester)
        create_url = reverse("contact_request_create", args=[self.found_report.pk])
        self.client.post(create_url, self.ownership_claim_data())
        response = self.client.post(create_url, self.ownership_claim_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already have an active claim")
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


class RemovedAIFeatureTests(MediaTestCase):
    def test_removed_management_urls_return_not_found(self):
        staff = User.objects.create_user("no_ai_staff", password="StrongPass123!", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get("/en/management/ai-assistant/").status_code, 404)
        self.assertEqual(self.client.get("/en/management/ai-assistant/settings/").status_code, 404)

    def test_management_navigation_has_no_ai_link(self):
        staff = User.objects.create_user("plain_staff", password="StrongPass123!", is_staff=True)
        self.client.force_login(staff)
        response = self.client.get(reverse("management_dashboard"))
        self.assertNotContains(response, "AI Assistant")
        self.assertNotContains(response, "ai-assistant")

    def test_no_ai_module_or_environment_configuration_is_required(self):
        self.assertIsNone(importlib.util.find_spec("items.ai_assistant"))
        for setting_name in (
            "IMAGE_ANALYSIS_ENABLED", "IMAGE_ANALYSIS_PROVIDER", "IMAGE_ANALYSIS_API_KEY",
            "IMAGE_ANALYSIS_MODEL", "IMAGE_ANALYSIS_TIMEOUT", "OPENAI_API_KEY",
            "OLLAMA_BASE_URL", "OLLAMA_MODEL",
        ):
            self.assertFalse(hasattr(settings, setting_name), setting_name)

    def test_manual_report_and_rule_based_matching_work_without_provider(self):
        found = self.create_report(
            report_type=ItemReport.ReportType.FOUND,
            title="Found black headphones",
            image=test_image("manual-found.jpg"),
        )
        result = MatchingService.compare(self.create_report(image=test_image("manual-lost.jpg")), found)
        self.assertGreater(result.total_score, 0)


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


class InternationalizationTests(TestCase):
    def tearDown(self):
        translation.activate("en")
        super().tearDown()

    def test_language_prefixed_homepages_and_direction(self):
        for code, direction in (("en", "ltr"), ("tr", "ltr"), ("ar", "rtl")):
            with self.subTest(language=code):
                response = self.client.get(f"/{code}/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'lang="{code}"')
                self.assertContains(response, f'dir="{direction}"')

    def test_unprefixed_root_uses_browser_language(self):
        response = self.client.get("/", HTTP_ACCEPT_LANGUAGE="tr-TR,tr;q=0.9")
        self.assertRedirects(response, "/tr/", fetch_redirect_response=False)

    def test_authentication_redirect_keeps_language(self):
        response = self.client.get("/tr/my-reports/")
        self.assertRedirects(
            response,
            "/tr/accounts/login/?next=/tr/my-reports/",
            fetch_redirect_response=False,
        )

    def test_translated_navigation_and_choice_labels(self):
        self.assertContains(self.client.get("/tr/"), "Ana Sayfa")
        self.assertContains(self.client.get("/ar/"), "الرئيسية")
        with translation.override("tr"):
            self.assertEqual(ItemReport(report_type="lost").get_report_type_display(), "Kayıp")
        with translation.override("ar"):
            self.assertEqual(ItemReport(report_type="found").get_report_type_display(), "تم العثور عليه")

    def test_structured_claim_labels_are_translated(self):
        with translation.override("tr"):
            self.assertEqual(gettext("Item type"), "Eşya türü")
            self.assertEqual(gettext("Ownership claim"), "Mülkiyet talebi")
        with translation.override("ar"):
            self.assertEqual(gettext("Item type"), "نوع الغرض")
            self.assertEqual(gettext("Ownership claim"), "مطالبة بالملكية")

    def test_switcher_keeps_path_and_query(self):
        response = self.client.get("/en/items/?q=phone&page=2")
        self.assertContains(response, 'href="/tr/items/?q=phone&amp;page=2"')
        self.assertContains(response, 'href="/ar/items/?q=phone&amp;page=2"')

    def test_user_content_uses_automatic_direction(self):
        owner = User.objects.create_user(username="owner", password="test-pass-123")
        report = ItemReport.objects.create(
            owner=owner,
            report_type="lost",
            title="هاتف أزرق",
            description="A mixed-language description",
            category="electronics",
            colour="blue",
            campus_location="library",
            item_date=date.today(),
            image=test_image(),
        )
        response = self.client.get(f"/ar/items/{report.pk}/")
        self.assertContains(response, 'dir="auto">هاتف أزرق')

    def test_localized_error_pages(self):
        expected_404 = {"en": "Page not found", "tr": "Sayfa bulunamadı", "ar": "الصفحة غير موجودة"}
        expected_403 = {"en": "Permission denied", "tr": "Erişim reddedildi", "ar": "تم رفض الإذن"}
        for code in ("en", "tr", "ar"):
            with self.subTest(language=code):
                self.assertContains(
                    self.client.get(f"/{code}/does-not-exist/"), expected_404[code], status_code=404
                )
                self.assertContains(self.client.get(f"/{code}/403/"), expected_403[code], status_code=403)

    def test_arabic_plural_forms_and_english_fallback(self):
        with translation.override("ar"):
            forms = [
                ngettext("%(count)s report", "%(count)s reports", count) % {"count": count}
                for count in (0, 1, 2, 3, 11, 102)
            ]
            self.assertEqual(len(set(forms)), 6)
            self.assertEqual(gettext("Uncatalogued FindMatch test phrase"), "Uncatalogued FindMatch test phrase")

    def test_rtl_profile_keeps_email_left_to_right(self):
        user = User.objects.create_user(username="rtl-user", email="student@example.edu", password="test-pass-123")
        self.client.force_login(user)
        response = self.client.get("/ar/accounts/profile/")
        self.assertContains(response, 'dir="ltr">student@example.edu')

class ResponsiveInterfaceTests(MediaTestCase):
    def setUp(self):
        self.user = User.objects.create_user("responsive-user", email="responsive@st.biruni.edu.tr", password="StrongPass123!")
        UserProfile.objects.create(user=self.user, email_verified_at=timezone.now(), university_eligible=True)
        self.owner = self.user
        self.report = self.create_report(owner=self.user, title="Blue campus backpack", exact_private_location="Private locker 42")

    def tearDown(self):
        translation.activate("en")
        super().tearDown()

    def test_mobile_and_desktop_navigation_markup_is_available(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'fm-navbar')
        self.assertContains(response, 'class="mobile-bottom-nav"')
        self.assertContains(response, 'aria-label="Mobile navigation"')
        self.assertContains(response, 'class="mobile-primary-action"')

    def test_authenticated_mobile_navigation_uses_authorized_destinations(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("user_dashboard"))
        self.assertContains(response, reverse("my_possible_matches"))
        self.assertContains(response, reverse("user_dashboard"))
        self.assertNotContains(response, reverse("management_dashboard"))

    def test_report_cards_have_responsive_image_metadata_and_public_fields(self):
        response = self.client.get(reverse("item_list"))
        self.assertContains(response, 'class="card-img-top report-image"')
        self.assertContains(response, 'width="640" height="480" loading="lazy"')
        self.assertContains(response, self.report.get_item_type_display())
        self.assertNotContains(response, self.report.exact_private_location)

    def test_filter_panel_preserves_query_and_has_accessible_controls(self):
        response = self.client.get(reverse("item_list"), {"campus_location": self.report.campus_location, "sort": "oldest"})
        self.assertContains(response, 'data-filter-panel')
        self.assertContains(response, 'data-filter-open')
        self.assertContains(response, 'data-filter-close')
        self.assertContains(response, 'name="campus_location"')
        self.assertContains(response, 'sort=oldest')

    def test_report_form_has_guided_progress_and_no_javascript_fallback_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("item_create_lost"))
        self.assertContains(response, 'data-current-step')
        self.assertContains(response, 'data-wizard-actions')
        self.assertContains(response, 'data-report-form-fields')
        self.assertContains(response, 'name="submission_action" value="submit"')

    def test_arabic_shell_is_rtl_and_mobile_labels_are_translatable(self):
        response = self.client.get("/ar/")
        self.assertContains(response, '<html lang="ar" dir="rtl">')
        self.assertContains(response, 'class="mobile-bottom-nav"')
        self.assertContains(response, 'aria-label="اختر اللغة"')
        self.assertContains(response, 'aria-label="صفحة FindMatch الرئيسية"')
        response = self.client.get("/tr/")
        self.assertContains(response, 'aria-label="Dil seçin"')

    def test_anonymous_navigation_uses_compact_grouping(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'class="fm-primary-links"')
        self.assertContains(response, 'id="browseMenuButton"')
        self.assertContains(response, 'id="reportMenuButton"')
        self.assertContains(response, 'id="desktopLanguageMenuButton"')
        self.assertContains(response, 'id="mobileNavigation"')
        self.assertNotContains(response, 'id="profileMenuButton"')

    def test_authenticated_profile_menu_contains_secure_account_actions(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'id="profileMenuButton"')
        self.assertContains(response, reverse("user_dashboard"))
        self.assertContains(response, reverse("my_reports"))
        self.assertContains(response, f'method="post" action="{reverse("logout")}"')
        self.assertNotContains(response, 'class="navbar-text user-chip"')

    def test_staff_navigation_is_not_exposed_to_normal_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, reverse("management_dashboard"))
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        response = self.client.get(reverse("home"))
        self.assertContains(response, reverse("management_dashboard"))
