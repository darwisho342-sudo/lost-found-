from datetime import date

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ItemReport, UniversityLocation


@override_settings(OPEN_UNIVERSITY_ACCESS=True)
class CoreReportingWorkflowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            "reporter", email="personal@example.com", password="StrongPass123!"
        )
        self.client.force_login(self.user)
        self.university_location = UniversityLocation.objects.create(
            campus="Main Campus", building="Library", general_area="Library",
            location_type="library",
        )

    def select_scope(self, scope):
        session = self.client.session
        session["findmatch_scope"] = scope
        session.save()

    def valid_data(self, scope="university", **overrides):
        data = {
            "scope": scope,
            "title": "Black backpack",
            "category": "bags",
            "item_type": "backpack",
            "custom_item_type": "",
            "primary_colour": "black",
            "secondary_colour": "grey",
            "material": "fabric",
            "approximate_size": "medium",
            "pattern": "plain",
            "item_condition": "good",
            "brand": "no_visible_brand",
            "custom_brand": "",
            "model": "",
            "item_date": date.today().isoformat(),
            "additional_details": "Two front pockets",
            "submission_action": "submit",
        }
        if scope == "university":
            data["university_location"] = str(self.university_location.pk)
        else:
            data.update({
                "country": "TR", "city": "Istanbul",
                "place_type": "university_school", "place_name": "Central library",
            })
        data.update(overrides)
        return data

    def test_creates_lost_and_found_reports_in_both_open_modes(self):
        for scope in ItemReport.Scope.values:
            for report_type in ItemReport.ReportType.values:
                with self.subTest(scope=scope, report_type=report_type):
                    self.select_scope(scope)
                    response = self.client.post(
                        reverse("report_create", args=(report_type,)),
                        self.valid_data(
                            scope, title=f"{scope} {report_type} backpack",
                            item_date=date.today().isoformat(),
                        ),
                    )
                    report = ItemReport.objects.get(
                        title=f"{scope} {report_type} backpack"
                    )
                    self.assertRedirects(
                        response, reverse("item_matches", args=(report.pk,))
                    )
                    self.assertEqual(report.owner, self.user)
                    self.assertEqual(report.scope, scope)
                    self.assertEqual(report.report_type, report_type)
                    self.assertEqual(report.status, ItemReport.Status.ACTIVE)

    def test_final_submission_enforces_required_fields_on_server(self):
        self.select_scope("university")
        response = self.client.post(
            reverse("report_create", args=("lost",)),
            {"scope": "university", "submission_action": "submit"},
        )
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        for field_name in ("category", "item_type", "primary_colour", "item_date"):
            self.assertIn(field_name, form.errors)
        self.assertFalse(ItemReport.objects.exists())

    def test_other_choices_require_and_preserve_detail_fields(self):
        self.select_scope("university")
        invalid = self.valid_data(
            item_type="other", custom_item_type="", brand="other", custom_brand="",
        )
        response = self.client.post(reverse("report_create", args=("found",)), invalid)
        self.assertEqual(response.status_code, 200)
        self.assertIn("custom_item_type", response.context["form"].errors)
        self.assertIn("custom_brand", response.context["form"].errors)

        valid = self.valid_data(
            title="Other custom item", item_type="other", custom_item_type="Instrument case",
            brand="other", custom_brand="Handmade",
        )
        response = self.client.post(reverse("report_create", args=("found",)), valid)
        report = ItemReport.objects.get(title="Other custom item")
        self.assertRedirects(response, reverse("item_matches", args=(report.pk,)))
        self.assertEqual(report.custom_item_type, "Instrument case")
        self.assertEqual(report.custom_brand, "Handmade")
        self.assertEqual(report.public_location, "Main Campus — Library")

    def test_partial_draft_can_be_saved_continued_and_submitted(self):
        self.select_scope("international")
        response = self.client.post(
            reverse("report_create", args=("lost",)),
            {
                "scope": "international", "category": "electronics",
                "item_type": "laptop", "brand": "lenovo",
                "submission_action": "draft",
            },
        )
        draft = ItemReport.objects.get()
        self.assertRedirects(response, reverse("my_reports"))
        self.assertEqual(draft.owner, self.user)
        self.assertEqual(draft.status, ItemReport.Status.DRAFT)
        self.assertIsNone(draft.item_date)

        response = self.client.get(reverse("item_edit", args=(draft.pk,)))
        self.assertContains(response, "Continue your draft")
        self.assertEqual(response.context["form"].initial["item_type"], "laptop")
        self.assertEqual(response.context["form"].initial["brand"], "lenovo")

        completed = self.valid_data(
            "international", title="Completed laptop draft", category="electronics",
            item_type="laptop", brand="lenovo",
        )
        response = self.client.post(reverse("item_edit", args=(draft.pk,)), completed)
        self.assertRedirects(response, reverse("item_matches", args=(draft.pk,)))
        draft.refresh_from_db()
        self.assertEqual(draft.status, ItemReport.Status.ACTIVE)
        self.assertEqual(draft.title, "Completed laptop draft")
        self.assertIsNotNone(draft.expires_at)

    def test_saving_draft_again_preserves_wizard_values(self):
        self.select_scope("university")
        first = self.client.post(
            reverse("report_create", args=("found",)),
            {
                "scope": "university", "category": "bags", "item_type": "other",
                "custom_item_type": "Camera pouch", "primary_colour": "purple",
                "submission_action": "draft",
            },
        )
        draft = ItemReport.objects.get()
        self.assertRedirects(first, reverse("my_reports"))
        second = self.client.post(
            reverse("item_edit", args=(draft.pk,)),
            {
                "scope": "university", "category": "bags", "item_type": "other",
                "custom_item_type": "Camera pouch", "primary_colour": "purple",
                "material": "fabric", "submission_action": "draft",
            },
        )
        self.assertRedirects(second, reverse("my_reports"))
        draft.refresh_from_db()
        self.assertEqual(draft.item_type, "other")
        self.assertEqual(draft.custom_item_type, "Camera pouch")
        self.assertEqual(draft.primary_colour, "purple")
        self.assertEqual(draft.material, "fabric")

    def test_invalid_final_step_keeps_bound_values_for_back_navigation(self):
        self.select_scope("international")
        data = self.valid_data("international", item_date="")
        response = self.client.post(reverse("report_create", args=("lost",)), data)
        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.data["category"], "bags")
        self.assertEqual(form.data["primary_colour"], "black")
        self.assertEqual(form.data["city"], "Istanbul")
        self.assertContains(response, "data-step-back")
        self.assertFalse(ItemReport.objects.exists())

    def test_repeated_submission_is_not_created_twice(self):
        self.select_scope("university")
        url = reverse("report_create", args=("lost",))
        data = self.valid_data(title="One submission only")
        first = self.client.post(url, data)
        report = ItemReport.objects.get()
        self.assertRedirects(first, reverse("item_matches", args=(report.pk,)))

        second = self.client.post(url, data)
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "looks similar to one of your recent reports")
        self.assertEqual(ItemReport.objects.count(), 1)

    def test_normal_user_cannot_continue_another_users_draft(self):
        other = User.objects.create_user("other", password="StrongPass123!")
        draft = ItemReport.objects.create(
            owner=other, scope="university", report_type="lost",
            status=ItemReport.Status.DRAFT,
        )
        self.select_scope("university")
        self.assertEqual(
            self.client.get(reverse("item_edit", args=(draft.pk,))).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("item_detail", args=(draft.pk,))).status_code, 404
        )
