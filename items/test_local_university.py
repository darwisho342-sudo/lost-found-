from datetime import date

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import RegistrationForm
from .admin_actions import AdminReportActionService
from .models import CustodyRecord, ItemReport, StorageIncident, UserProfile
from .services import MatchingService
from .tests import MediaTestCase, test_image
from .university import UniversityAccessService


class UniversityAccessTests(TestCase):
    def test_personal_email_registers_but_does_not_gain_university_access(self):
        personal = RegistrationForm(data={
            "username": "outside", "email": "outside@gmail.com",
            "password1": "A-Strong-Passphrase-135!", "password2": "A-Strong-Passphrase-135!",
        })
        self.assertTrue(personal.is_valid(), personal.errors)
        accepted = RegistrationForm(data={
            "username": "student", "email": "student@student.demo.edu",
            "password1": "A-Strong-Passphrase-135!", "password2": "A-Strong-Passphrase-135!",
        })
        self.assertTrue(accepted.is_valid(), accepted.errors)

    def test_verified_access_requires_domain_timestamp_and_active_account(self):
        user = User.objects.create_user("verified", email="verified@student.demo.edu")
        profile = UserProfile.objects.create(
            user=user, email_verified_at=timezone.now(), university_eligible=True,
            preferred_scope=ItemReport.Scope.UNIVERSITY,
        )
        self.assertTrue(UniversityAccessService.is_verified(user))
        profile.university_eligibility_lost_at = timezone.now()
        profile.save(update_fields=("university_eligibility_lost_at", "updated_at"))
        self.assertFalse(UniversityAccessService.is_verified(user))
        user.is_active = False
        user.save(update_fields=("is_active",))
        self.assertFalse(UniversityAccessService.is_verified(user))

    def test_local_session_and_email_defaults(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 259200)
        self.assertEqual(settings.SITE_URL, "http://127.0.0.1:8000")
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3")


class LocalReportMatchingAndCustodyTests(MediaTestCase):
    def matching_report(self, report_type, owner, **overrides):
        values = {
            "owner": owner, "report_type": report_type, "title": "Black Samsung Mobile Phone",
            "description": "Black phone with a small scratch", "additional_details": "Black phone with a small scratch",
            "category": "electronics", "item_type": "mobile_phone", "colour": "Black",
            "primary_colour": "black", "secondary_colour": "grey", "brand": "samsung",
            "model": "Galaxy S", "campus_location": "library", "item_date": date.today(),
        }
        values.update(overrides)
        return ItemReport.objects.create(**values)

    def test_requested_local_matching_formula_totals_100_and_ignores_private_location(self):
        finder = User.objects.create_user("finder")
        lost = self.matching_report("lost", self.owner, exact_private_location="Private floor one")
        found = self.matching_report("found", finder, exact_private_location="Different private floor")
        result = MatchingService.compare(lost, found)
        self.assertEqual(result.total_score, 100)
        self.assertEqual(
            (result.category_points, result.item_type_points, result.description_points,
             result.primary_colour_points, result.secondary_colour_points, result.brand_points,
             result.model_points, result.location_points, result.date_points, result.title_points),
            (15, 15, 15, 10, 5, 10, 5, 10, 10, 5),
        )

    def test_sensitive_document_image_moves_out_of_public_media(self):
        report = self.matching_report(
            "found", self.owner, item_type="passport", image=test_image("passport.jpg")
        )
        self.assertFalse(bool(report.image))
        self.assertTrue(bool(report.private_sensitive_image))
        self.assertTrue(report.image_is_hidden)
        self.assertTrue(report.require_official_handover)
        report.private_sensitive_image.delete(save=False)

    def test_staff_only_custody_inventory_and_missing_incident(self):
        staff = User.objects.create_user("security", email="security@staff.demo.edu", is_staff=True)
        found = self.matching_report("found", self.owner)
        record = CustodyRecord.objects.create(
            found_report=found, reference="FM-TEST-001", received_by=staff,
            intake_point="Security desk", storage_reference="Cabinet A",
        )
        self.assertIsNotNone(record.retention_expires_at)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("management_custody")).status_code, 403)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("management_custody")).status_code, 200)
        response = self.client.post(
            reverse("management_custody_incident", args=(record.pk,)),
            {"summary": "Item could not be located during reconciliation."},
        )
        self.assertRedirects(response, reverse("management_custody"))
        record.refresh_from_db()
        self.assertEqual(record.status, CustodyRecord.Status.MISSING)
        self.assertTrue(StorageIncident.objects.filter(custody_record=record).exists())

    def test_only_found_reports_enter_custody(self):
        staff = User.objects.create_user("security-two", is_staff=True)
        lost = self.matching_report("lost", self.owner)
        record = CustodyRecord(
            found_report=lost, reference="FM-TEST-002", received_by=staff,
            intake_point="Desk", storage_reference="Shelf",
        )
        with self.assertRaises(ValidationError):
            record.full_clean()

    def test_staff_hide_image_action_moves_file_to_private_storage(self):
        staff = User.objects.create_user("image-moderator", is_staff=True)
        report = self.matching_report("found", self.owner, image=test_image("unsafe-public.jpg"))
        result = AdminReportActionService.apply(
            administrator=staff, reports=ItemReport.objects.filter(pk=report.pk), action="hide_images"
        )
        report.refresh_from_db()
        self.assertEqual(result.success_count, 1)
        self.assertFalse(bool(report.image))
        self.assertTrue(bool(report.private_sensitive_image))
        self.assertTrue(report.image_is_hidden)
        report.private_sensitive_image.delete(save=False)
