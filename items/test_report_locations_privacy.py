from datetime import date

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import ItemReportForm
from .models import ItemReport, PrivateVerificationQuestion, UniversityLocation


@override_settings(OPEN_UNIVERSITY_ACCESS=True)
class ReportLocationAndPrivacyTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            "location_owner", email="owner@example.com", password="StrongPass123!"
        )
        self.stranger = User.objects.create_user(
            "location_stranger", email="stranger@example.com", password="StrongPass123!"
        )
        self.staff = User.objects.create_user(
            "location_staff", email="staff@example.com", password="StrongPass123!",
            is_staff=True,
        )
        self.university_location = UniversityLocation.objects.create(
            campus="Biruni Campus", building="Library Building",
            general_area="Main entrance", location_type="library",
        )
        self.client.force_login(self.owner)

    def select_scope(self, scope):
        session = self.client.session
        session["findmatch_scope"] = scope
        session.save()

    def report_data(self, scope="university", **overrides):
        data = {
            "scope": scope, "title": "Found black backpack", "category": "bags",
            "item_type": "backpack", "primary_colour": "black",
            "material": "fabric", "approximate_size": "medium",
            "item_condition": "good", "brand": "no_visible_brand",
            "item_date": date.today().isoformat(), "submission_action": "submit",
            "place_type": "university_school", "place_name": "Main library",
            "public_location": "Near the staffed library entrance",
            "exact_private_location": "Locked cabinet B, shelf 4",
        }
        if scope == "university":
            data.update({
                "university_location": str(self.university_location.pk),
                "university_floor": "Second floor",
                "university_room_or_area": "Study room 204",
            })
        else:
            data.update({
                "country": "TR", "region": "Marmara", "city": "Istanbul",
                "district": "Fatih",
            })
        data.update(overrides)
        return data

    def create_report(self, scope="university", report_type="found", **overrides):
        self.select_scope(scope)
        response = self.client.post(
            reverse("report_create", args=(report_type,)),
            self.report_data(scope, **overrides),
        )
        report = ItemReport.objects.latest("pk")
        self.assertRedirects(response, reverse("item_matches", args=(report.pk,)))
        return report

    def test_university_location_fields_are_saved_separately(self):
        report = self.create_report("university")
        self.assertEqual(report.university_location, self.university_location)
        self.assertEqual(report.university_location.campus, "Biruni Campus")
        self.assertEqual(report.university_location.building, "Library Building")
        self.assertEqual(report.university_floor, "Second floor")
        self.assertEqual(report.university_room_or_area, "Study room 204")
        self.assertEqual(report.campus_location, "library")
        self.assertEqual(report.place_type, "university_school")
        self.assertEqual(report.place_name, "Biruni Campus")
        self.assertEqual(report.public_location, "Biruni Campus — Library Building — Main entrance")
        self.assertIn("Biruni Campus", report.public_location_display)

    def test_international_location_and_region_label_are_saved(self):
        report = self.create_report("international", report_type="lost")
        self.assertEqual(report.country, "TR")
        self.assertEqual(report.region, "Marmara")
        self.assertEqual(report.city, "Istanbul")
        self.assertEqual(report.district, "Fatih")
        form = ItemReportForm(report_type="lost", scope="international")
        self.assertEqual(form.fields["region"].label, "Region / State / Governorate")

    def test_required_location_fields_are_enforced_by_django(self):
        university = ItemReportForm(
            data=self.report_data(
                "university", university_location="",
            ),
            report_type="found", scope="university",
        )
        self.assertFalse(university.is_valid())
        self.assertIn("university_location", university.errors)

        international = ItemReportForm(
            data=self.report_data("international", country="", city=""),
            report_type="lost", scope="international",
        )
        self.assertFalse(international.is_valid())
        self.assertIn("country", international.errors)
        self.assertIn("city", international.errors)

    def test_other_location_choices_require_details(self):
        country = ItemReportForm(
            data=self.report_data(
                "international", country="OTHER", custom_country="",
            ),
            report_type="lost", scope="international",
        )
        self.assertFalse(country.is_valid())
        self.assertIn("custom_country", country.errors)

        place = ItemReportForm(
            data=self.report_data("international", place_type="other", place_name=""),
            report_type="lost", scope="international",
        )
        self.assertFalse(place.is_valid())
        self.assertIn("place_name", place.errors)

        report = self.create_report(
            "international", report_type="lost", country="OTHER",
            custom_country="Example Republic", place_type="other",
            place_name="Community collection desk",
        )
        self.assertEqual(report.custom_country, "Example Republic")
        self.assertEqual(report.place_name, "Community collection desk")

    def test_public_pages_and_search_never_expose_private_locations(self):
        report = self.create_report("university")
        self.client.logout()
        detail = self.client.get(reverse("item_detail", args=(report.pk,)))
        self.assertContains(detail, report.public_location)
        self.assertNotContains(detail, report.exact_private_location)
        self.assertNotContains(detail, report.university_floor)
        self.assertNotContains(detail, report.university_room_or_area)

        search = self.client.get(
            reverse("item_list"), {"scope": "university", "query": "cabinet B shelf 4"}
        )
        self.assertNotContains(search, report.title)

    def test_found_public_text_rejects_private_identifying_details(self):
        unsafe_values = (
            "Serial number ABC-12345",
            "The hidden mark is a blue star",
            "Exact contents are two bank cards",
            "Contact owner@example.com",
            "Call +90 555 123 4567",
            "Full card number 4111 1111 1111 1111",
        )
        for value in unsafe_values:
            with self.subTest(value=value):
                form = ItemReportForm(
                    data=self.report_data("international", additional_details=value),
                    report_type="found", scope="international",
                )
                self.assertFalse(form.is_valid())
                self.assertIn("additional_details", form.errors)

    def test_private_verification_details_never_appear_publicly(self):
        report = self.create_report("international")
        question = PrivateVerificationQuestion.objects.create(
            item_report=report, question_type="hidden_mark",
            question_text="Describe the hidden mark",
            expected_answer="Small silver star under the lining",
        )
        self.client.logout()
        response = self.client.get(reverse("item_detail", args=(report.pk,)))
        self.assertNotContains(response, question.question_text)
        self.assertNotContains(response, question.expected_answer)
        self.assertNotContains(response, self.owner.email)

    def test_only_owner_and_staff_can_access_private_report_information(self):
        report = self.create_report("university")
        owner_response = self.client.get(reverse("item_detail", args=(report.pk,)))
        self.assertContains(owner_response, report.exact_private_location)
        self.assertContains(owner_response, report.university_room_or_area)

        self.client.force_login(self.stranger)
        stranger_detail = self.client.get(reverse("item_detail", args=(report.pk,)))
        self.assertNotContains(stranger_detail, report.exact_private_location)
        self.assertNotContains(stranger_detail, report.university_room_or_area)
        self.assertEqual(
            self.client.get(reverse("item_edit", args=(report.pk,))).status_code, 403
        )

        self.client.force_login(self.staff)
        staff_detail = self.client.get(reverse("item_detail", args=(report.pk,)))
        self.assertContains(staff_detail, report.exact_private_location)
        self.assertContains(staff_detail, report.university_room_or_area)
        self.assertEqual(
            self.client.get(reverse("item_edit", args=(report.pk,))).status_code, 200
        )
