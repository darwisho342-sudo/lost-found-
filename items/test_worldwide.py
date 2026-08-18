from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .alerts import AlertService
from .forms import ItemReportForm, ReturnArrangementForm
from .models import (
    ContactRequest, Conversation, ItemReport, Notification, ReturnArrangement,
    SavedSearch, SavedSearchNotification, UserProfile,
)
from .return_service import ReturnWorkflowService
from .security import EmailVerificationService
from .services import MatchingService


class InternationalReportTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("world-owner", email="owner@example.invalid", password="StrongPass123!")

    def form_data(self, **overrides):
        data = {
            "title": "Lost Black Phone in Istanbul", "category": "electronics",
            "item_type": "mobile_phone", "primary_colour": "black", "secondary_colour": "grey",
            "material": "metal", "approximate_size": "small", "pattern": "plain",
            "item_condition": "used", "brand": "samsung", "model": "Galaxy S",
            "country": "TR", "region": "Marmara", "city": "Istanbul", "district": "Fatih",
            "place_type": "public_transport", "place_name": "Sirkeci Station",
            "campus_location": "library",
            "public_location": "Near the main public entrance", "exact_private_location": "Private platform detail",
            "latitude": "41.014000", "longitude": "28.976000", "public_location_precision_km": "5",
            "item_date": date.today().isoformat(), "additional_details": "Black case with a small scratch",
        }
        data.update(overrides)
        return data

    def create_report(self, report_type="lost", status="active", **overrides):
        values = {
            "owner": self.owner, "report_type": report_type,
            "scope": ItemReport.Scope.INTERNATIONAL, "status": status,
            "title": "Black Samsung phone", "description": "Black case with a small scratch",
            "additional_details": "Black case with a small scratch", "category": "electronics",
            "item_type": "mobile_phone", "colour": "Black", "primary_colour": "black",
            "secondary_colour": "grey", "material": "metal", "approximate_size": "small",
            "brand": "samsung", "model": "Galaxy S", "country": "TR", "region": "Marmara",
            "city": "Istanbul", "district": "Fatih", "place_type": "public_transport",
            "place_name": "Sirkeci Station", "public_location": "Near the main entrance",
            "exact_private_location": "Private platform detail", "latitude": Decimal("41.014000"),
            "longitude": Decimal("28.976000"), "item_date": date.today(),
        }
        values.update(overrides)
        return ItemReport.objects.create(**values)

    def test_international_report_requires_country_and_city(self):
        form = ItemReportForm(
            data=self.form_data(country="", city=""), report_type="lost",
            scope=ItemReport.Scope.INTERNATIONAL,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("country", form.errors)
        self.assertIn("city", form.errors)

    def test_private_location_is_not_rendered_publicly(self):
        report = self.create_report()
        response = self.client.get(report.get_absolute_url())
        self.assertContains(response, "Sirkeci Station")
        self.assertNotContains(response, "Private platform detail")
        self.assertNotContains(response, "41.014")

    def test_public_lists_exclude_drafts_expired_and_closed_reports(self):
        active = self.create_report(title="Visible local item")
        self.create_report(title="Private draft item", status="draft")
        self.create_report(title="Expired item", status="expired")
        response = self.client.get(reverse("report_list"), {"scope": "international"})
        self.assertContains(response, active.title)
        self.assertNotContains(response, "Private draft item")
        self.assertNotContains(response, "Expired item")

    def test_deterministic_score_is_100_and_private_fields_are_excluded(self):
        lost = self.create_report(campus_location="library")
        found = self.create_report(report_type="found", campus_location="library", owner=User.objects.create_user("finder"))
        result = MatchingService.compare(lost, found)
        self.assertEqual(result.total_score, 100)
        found.exact_private_location = "Completely different secret place"
        found.save()
        self.assertEqual(MatchingService.compare(lost, found).total_score, 100)

    def test_matching_is_active_opposite_type_only_and_limited(self):
        lost = self.create_report()
        for index in range(7):
            self.create_report(report_type="found", owner=User.objects.create_user(f"finder-{index}"), title=f"Black Samsung phone {index}")
        self.create_report(report_type="found", status="draft", owner=User.objects.create_user("draft-finder"))
        results = MatchingService.find_matches(lost)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(result.total_score >= 70 for result in results))
        self.assertTrue(all(result.found_item.status == ItemReport.Status.ACTIVE for result in results))


class ReturnAlertAndPlatformTests(TestCase):
    def setUp(self):
        self.finder = User.objects.create_user("return-finder", email="finder@example.invalid", password="StrongPass123!")
        self.owner = User.objects.create_user("return-owner", email="owner@example.invalid", password="StrongPass123!")
        for user in (self.finder, self.owner):
            UserProfile.objects.create(user=user, email_verified_at=timezone.now())
        self.report = ItemReport.objects.create(
            owner=self.finder, report_type="found", scope=ItemReport.Scope.INTERNATIONAL,
            title="Found phone", description="Black phone",
            category="electronics", item_type="mobile_phone", colour="Black", primary_colour="black",
            country="TR", city="Istanbul", item_date=date.today(), status="claim_in_progress",
        )
        self.claim = ContactRequest.objects.create(
            item_report=self.report, requesting_user=self.owner, receiving_user=self.finder,
            request_type="ownership_claim", initial_message="This is mine", truthful_confirmation=True,
            status="approved",
        )
        self.conversation = Conversation.objects.create(
            item_report=self.report, approved_contact_request=self.claim,
            first_participant=self.owner, second_participant=self.finder,
        )

    def test_international_return_is_descriptive_without_delivery_integration_fields(self):
        arrangement = ReturnWorkflowService.get_or_create(claim=self.claim, user=self.owner)
        form = ReturnArrangementForm(data={
            "return_method": "safe_public_meeting", "status": "arranging",
            "safe_public_location": "Busy public meeting point",
        }, instance=arrangement, user=self.owner)
        self.assertTrue(form.is_valid(), form.errors)
        ReturnWorkflowService.update(arrangement=arrangement, user=self.owner, form=form)
        arrangement.refresh_from_db()
        self.assertEqual(arrangement.return_method, "safe_public_meeting")
        self.assertEqual(arrangement.delivery_address, "")
        self.assertNotIn("delivery_address", form.fields)

    def test_two_person_return_confirmation_resolves_once(self):
        arrangement = ReturnArrangement.objects.create(contact_request=self.claim, return_method="safe_public_meeting")
        ReturnWorkflowService.confirm(arrangement=arrangement, user=self.finder, role="finder")
        ReturnWorkflowService.confirm(arrangement=arrangement, user=self.owner, role="owner")
        self.claim.refresh_from_db(); self.report.refresh_from_db(); self.conversation.refresh_from_db()
        self.assertEqual(self.claim.status, ContactRequest.Status.COMPLETED)
        self.assertEqual(self.report.status, ItemReport.Status.RESOLVED)
        self.assertFalse(self.conversation.is_active)
        ReturnWorkflowService.confirm(arrangement=arrangement, user=self.owner, role="owner")
        self.assertEqual(ReturnArrangement.objects.filter(contact_request=self.claim).count(), 1)

    def test_saved_search_alert_is_deduplicated_and_safe(self):
        saved = SavedSearch.objects.create(user=self.owner, name="Istanbul phones", filters={"country": "Türkiye", "city": "Istanbul"})
        report = ItemReport.objects.create(
            owner=self.finder, report_type="found", title="Public phone", description="Phone",
            category="electronics", item_type="mobile_phone", colour="Black", primary_colour="black",
            country="Türkiye", city="Istanbul", exact_private_location="Never notify this",
            item_date=date.today(), status="active",
        )
        AlertService.notify_saved_searches(report); AlertService.notify_saved_searches(report)
        self.assertEqual(SavedSearchNotification.objects.filter(saved_search=saved, item_report=report).count(), 1)
        notification = Notification.objects.get(recipient=self.owner, notification_type="saved_search_match")
        self.assertNotIn("Never notify this", notification.safe_message)

    def test_health_check_and_privacy_export(self):
        self.assertEqual(self.client.get(reverse("health_check")).json(), {"status": "ok"})
        self.client.force_login(self.owner)
        response = self.client.get(reverse("account_data_export"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.owner.email)
        self.assertNotContains(response, "delivery_address")

    def test_email_verification_gates_claims_and_signed_link_verifies(self):
        unverified = User.objects.create_user("unverified", email="unverified@student.demo.edu", password="StrongPass123!")
        UserProfile.objects.create(user=unverified)
        self.report.status = ItemReport.Status.ACTIVE
        self.report.save(update_fields=("status", "updated_at"))
        self.client.force_login(unverified)
        self.assertEqual(self.client.get(reverse("contact_request_create", args=(self.report.pk,))).status_code, 403)
        response = self.client.get(reverse("verify_email", args=(EmailVerificationService.token(unverified),)))
        self.assertRedirects(response, reverse("profile"))
        unverified.profile.refresh_from_db()
        self.assertIsNotNone(unverified.profile.email_verified_at)
