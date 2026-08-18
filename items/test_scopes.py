from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .alerts import AlertService
from .forms import ItemReportForm, ReturnArrangementForm
from .models import (
    ClaimAppeal, ContactRequest, Conversation, CustodyRecord, ItemReport,
    Notification, ReturnArrangement, UserProfile,
)
from .return_service import ReturnWorkflowService
from .security import EmailVerificationService
from .services import MatchingService
from .university import UniversityAccessService


class ScopeAuthenticationTests(TestCase):
    def verified_user(self, username, email, university=False):
        user = User.objects.create_user(username, email=email, password="StrongPass123!")
        UserProfile.objects.create(
            user=user, email_verified_at=timezone.now(), university_eligible=university,
            preferred_scope="university" if university else "international",
        )
        return user

    def test_signed_verification_grants_personal_email_international_only(self):
        user = User.objects.create_user("personal", email="person@example.com")
        UserProfile.objects.create(user=user)
        verified = EmailVerificationService.verify(EmailVerificationService.token(user), User)
        self.assertEqual(verified, user)
        user.profile.refresh_from_db()
        self.assertIsNotNone(user.profile.email_verified_at)
        self.assertFalse(user.profile.university_eligible)
        self.assertEqual(user.profile.preferred_scope, ItemReport.Scope.INTERNATIONAL)
        self.assertFalse(UniversityAccessService.can_access_scope(user, ItemReport.Scope.UNIVERSITY))
        self.assertTrue(UniversityAccessService.can_access_scope(user, ItemReport.Scope.INTERNATIONAL))

    def test_personal_account_cannot_guess_university_private_route(self):
        personal = self.verified_user("personal", "person@example.com")
        self.client.force_login(personal)
        response = self.client.get(reverse("report_create", args=("lost",)), {"scope": "university"})
        self.assertEqual(response.status_code, 403)

    def test_university_account_can_open_both_report_modes(self):
        university = self.verified_user("student", "student@student.demo.edu", university=True)
        self.client.force_login(university)
        self.assertEqual(self.client.get(reverse("report_create", args=("lost",)), {"scope": "university"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("report_create", args=("lost",)), {"scope": "international"}).status_code, 200)


class ScopeReportAndMatchingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner")
        self.finder = User.objects.create_user("finder")

    def international_data(self, **overrides):
        data = {
            "title": "Black Samsung phone", "category": "electronics",
            "item_type": "mobile_phone", "primary_colour": "black",
            "secondary_colour": "dark_blue", "brand": "samsung", "model": "Galaxy Demo",
            "country": "TR", "region": "Marmara", "city": "Istanbul", "district": "Kadikoy",
            "place_type": "public_transport", "place_name": "Kadikoy Station",
            "public_location": "Near the public entrance", "exact_private_location": "Private platform",
            "item_date": date.today().isoformat(), "additional_details": "Black phone in a dark blue case",
        }
        data.update(overrides)
        return data

    def report(self, report_type, owner, **overrides):
        values = {
            "owner": owner, "report_type": report_type, "scope": "international",
            "title": "Black Samsung phone", "description": "Black phone in a dark blue case",
            "additional_details": "Black phone in a dark blue case", "category": "electronics",
            "item_type": "mobile_phone", "colour": "Black", "primary_colour": "black",
            "secondary_colour": "dark_blue", "brand": "samsung", "model": "Galaxy Demo",
            "country": "TR", "city": "Istanbul", "district": "Kadikoy",
            "place_type": "public_transport", "place_name": "Kadikoy Station",
            "item_date": date.today(), "status": "active",
        }
        values.update(overrides)
        return ItemReport.objects.create(**values)

    def test_conditional_international_form_and_private_location(self):
        form = ItemReportForm(
            data=self.international_data(), report_type="lost", scope="international"
        )
        self.assertTrue(form.is_valid(), form.errors)
        report = form.save(commit=False)
        report.owner = self.owner
        report.report_type = "lost"
        report.save()
        self.assertEqual(report.scope, "international")
        self.assertEqual(report.country, "TR")
        response = self.client.get(report.get_absolute_url())
        self.assertContains(response, "Kadikoy Station")
        self.assertNotContains(response, "Private platform")

    def test_same_scope_country_matching_is_exact_and_cross_scope_is_excluded(self):
        lost = self.report("lost", self.owner)
        found = self.report("found", self.finder)
        self.assertEqual(MatchingService.compare(lost, found).total_score, 100)
        wrong_country = self.report("found", User.objects.create_user("other"), country="GB")
        university = self.report(
            "found", User.objects.create_user("campus"), scope="university", country="",
            city="", district="", place_type="", place_name="", campus_location="library",
        )
        matches = MatchingService.find_matches(lost)
        self.assertEqual([result.found_item for result in matches], [found])
        self.assertNotIn(wrong_country, [result.found_item for result in matches])
        self.assertNotIn(university, [result.found_item for result in matches])

    def test_strong_notification_is_deduplicated(self):
        lost = self.report("lost", self.owner)
        found = self.report("found", self.finder)
        AlertService.notify_strong_matches(found)
        AlertService.notify_strong_matches(found)
        self.assertEqual(Notification.objects.filter(notification_type="strong_match").count(), 2)


class InternationalReturnAndAppealTests(TestCase):
    def setUp(self):
        self.finder = User.objects.create_user("finder", email="finder@example.com")
        self.owner = User.objects.create_user("owner", email="owner@example.com")
        for user in (self.finder, self.owner):
            UserProfile.objects.create(user=user, email_verified_at=timezone.now(), preferred_scope="international")
        self.report = ItemReport.objects.create(
            owner=self.finder, report_type="found", scope="international", title="Found phone",
            description="Phone", category="electronics", item_type="mobile_phone", colour="Black",
            primary_colour="black", country="TR", city="Istanbul", item_date=date.today(),
            status=ItemReport.Status.CLAIM_IN_PROGRESS,
        )
        self.claim = ContactRequest.objects.create(
            item_report=self.report, requesting_user=self.owner, receiving_user=self.finder,
            request_type="ownership_claim", initial_message="Mine", truthful_confirmation=True,
            status="approved",
        )
        self.conversation = Conversation.objects.create(
            item_report=self.report, approved_contact_request=self.claim,
            first_participant=self.owner, second_participant=self.finder,
        )

    def test_international_return_requires_both_participants(self):
        arrangement = ReturnArrangement.objects.create(
            contact_request=self.claim, return_method="safe_public_meeting"
        )
        ReturnWorkflowService.confirm(arrangement=arrangement, user=self.finder, role="finder")
        self.claim.refresh_from_db()
        self.assertNotEqual(self.claim.status, ContactRequest.Status.COMPLETED)
        ReturnWorkflowService.confirm(arrangement=arrangement, user=self.owner, role="owner")
        self.claim.refresh_from_db(); self.report.refresh_from_db(); self.conversation.refresh_from_db()
        self.assertEqual(self.claim.status, ContactRequest.Status.COMPLETED)
        self.assertEqual(self.report.status, ItemReport.Status.RESOLVED)
        self.assertFalse(self.conversation.is_active)

    def test_rejected_claim_can_be_appealed_once(self):
        self.claim.status = ContactRequest.Status.REJECTED
        self.claim.save(update_fields=("status",))
        appeal = ClaimAppeal.objects.create(
            contact_request=self.claim, submitted_by=self.owner,
            reason="Please review additional masked evidence.",
        )
        self.assertEqual(appeal.status, ClaimAppeal.Status.PENDING)
        with self.assertRaises(IntegrityError):
            ClaimAppeal.objects.create(
                contact_request=self.claim, submitted_by=self.owner, reason="Duplicate"
            )

    def test_international_report_cannot_enter_university_custody(self):
        staff = User.objects.create_user("staff", is_staff=True)
        record = CustodyRecord(
            found_report=self.report, reference="INT-NO", received_by=staff,
            intake_point="Office", storage_reference="Private bin",
        )
        with self.assertRaises(ValidationError):
            record.full_clean()
