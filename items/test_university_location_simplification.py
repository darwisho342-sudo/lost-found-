from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from .forms import ItemReportForm
from .models import ItemReport, UniversityLocation


@override_settings(OPEN_UNIVERSITY_ACCESS=True)
class UniversityLocationSimplificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "simple_location_user", email="simple@example.com", password="StrongPass123!"
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["findmatch_scope"] = "university"
        session.save()
        self.library = UniversityLocation.objects.create(
            campus="Main Campus", building="Library", general_area="Library",
            location_type="library",
        )
        self.classroom = UniversityLocation.objects.create(
            campus="Main Campus", building="Classroom", general_area="Classroom",
            location_type="classroom",
        )

    def report_data(self, **overrides):
        data = {
            "scope": "university", "title": "Simplified campus report",
            "category": "bags", "item_type": "backpack", "primary_colour": "black",
            "brand": "no_visible_brand", "university_location": str(self.classroom.pk),
            "item_date": date.today().isoformat(), "submission_action": "submit",
        }
        data.update(overrides)
        return data

    def test_university_page_displays_one_location_selector_and_only_private_extras(self):
        response = self.client.get(reverse("report_create", args=["lost"]))
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertIn("university_location", form.fields)
        for removed in ("campus_location", "custom_location", "place_type", "place_name", "public_location"):
            self.assertNotIn(removed, form.fields)
            self.assertNotContains(response, f'id="id_{removed}"')
        self.assertContains(response, 'name="university_location"', count=1)
        self.assertContains(response, "Additional private location details")

    def test_single_and_multiple_campus_labels_are_clean_and_unique(self):
        duplicate_library = UniversityLocation.objects.create(
            campus="Main Campus", building="", general_area="Library",
            location_type="library",
        )
        form = ItemReportForm(report_type="lost", scope="university")
        labels = [str(label) for value, label in form.fields["university_location"].choices if value]
        self.assertEqual(labels.count("Library"), 1)
        self.assertEqual(labels.count("Classroom"), 1)
        self.assertNotIn("Main Campus · Library · Library", labels)
        selected_ids = {int(str(value)) for value, label in form.fields["university_location"].choices if value}
        self.assertEqual(len({self.library.pk, duplicate_library.pk} & selected_ids), 1)

        UniversityLocation.objects.create(
            campus="Other Campus", building="Library", general_area="Library",
            location_type="library",
        )
        multi_campus = ItemReportForm(report_type="found", scope="university")
        multi_labels = [str(label) for value, label in multi_campus.fields["university_location"].choices if value]
        self.assertIn("Main Campus — Library", multi_labels)
        self.assertIn("Other Campus — Library", multi_labels)

    def test_server_generates_all_public_location_fields_and_ignores_posted_values(self):
        response = self.client.post(
            reverse("report_create", args=["lost"]),
            self.report_data(
                campus_location="cafeteria", place_type="hotel",
                place_name="Untrusted place", public_location="Untrusted public location",
            ),
        )
        report = ItemReport.objects.get(title="Simplified campus report")
        self.assertRedirects(response, reverse("item_matches", args=[report.pk]))
        self.assertEqual(report.university_location, self.classroom)
        self.assertEqual(report.campus_location, "classroom")
        self.assertEqual(report.place_type, "university_school")
        self.assertEqual(report.place_name, "Main Campus")
        self.assertEqual(report.public_location, "Main Campus — Classroom")
        self.assertNotIn("Untrusted", report.public_location_display)

    def test_floor_room_and_additional_private_details_are_optional_and_private(self):
        response = self.client.post(reverse("report_create", args=["found"]), self.report_data())
        report = ItemReport.objects.get()
        self.assertRedirects(response, reverse("item_matches", args=[report.pk]))
        self.assertEqual(report.university_floor, "")
        self.assertEqual(report.university_room_or_area, "")
        self.assertEqual(report.exact_private_location, "")

        report.university_floor = "Second floor"
        report.university_room_or_area = "Room 204"
        report.exact_private_location = "Locked cabinet near the desk"
        report.save()
        self.client.logout()
        public = self.client.get(reverse("report_detail", args=[report.pk]))
        self.assertContains(public, "Main Campus — Classroom")
        self.assertNotContains(public, "Second floor")
        self.assertNotContains(public, "Room 204")
        self.assertNotContains(public, "Locked cabinet near the desk")

    def test_drafts_editing_and_translated_forms_keep_the_single_selector(self):
        draft_response = self.client.post(
            reverse("report_create", args=["lost"]),
            {"scope": "university", "university_location": self.library.pk, "submission_action": "draft"},
        )
        draft = ItemReport.objects.get(status=ItemReport.Status.DRAFT)
        self.assertRedirects(draft_response, reverse("my_reports"))
        self.assertEqual(draft.public_location, "Main Campus — Library")
        edit = self.client.get(reverse("report_edit", args=[draft.pk]))
        self.assertContains(edit, 'name="university_location"', count=1)
        self.assertNotContains(edit, 'id="id_campus_location"')
        for language in ("tr", "ar"):
            with self.subTest(language=language), translation.override(language):
                localized = self.client.get(reverse("report_edit", args=[draft.pk]))
                self.assertContains(localized, 'name="university_location"', count=1)

    def test_international_mode_keeps_complete_manual_location_form(self):
        session = self.client.session
        session["findmatch_scope"] = "international"
        session.save()
        response = self.client.get(reverse("report_create", args=["found"]))
        form = response.context["form"]
        for field_name in (
            "country", "region", "city", "district", "place_type",
            "place_name", "public_location", "exact_private_location",
        ):
            self.assertIn(field_name, form.fields)
            self.assertContains(response, f'id="id_{field_name}"')
