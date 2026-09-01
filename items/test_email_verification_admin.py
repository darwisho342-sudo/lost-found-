from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from .admin import UserProfileAdmin
from .forms import ItemReportForm
from .models import ContactRequest, ItemReport, UserProfile
from .ownership import OwnershipVerificationService


class EmailVerificationAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            "verification_admin",
            "verification-admin@example.test",
            "StrongPass123!",
        )
        self.account = User.objects.create_user(
            "demo_claimant",
            "demo-claimant@example.test",
            "StrongPass123!",
        )
        self.profile, _ = UserProfile.objects.get_or_create(user=self.account)

    def run_action(self, action):
        self.client.force_login(self.superuser)
        return self.client.post(
            reverse("admin:items_userprofile_changelist"),
            {
                "action": action,
                "_selected_action": [str(self.profile.pk)],
            },
            follow=True,
        )

    @override_settings(DEBUG=True)
    def test_superuser_can_verify_and_unverify_selected_accounts(self):
        response = self.run_action("mark_email_verified")
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.email_verified_at)

        response = self.run_action("mark_email_unverified")
        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.email_verified_at)

    @override_settings(DEBUG=True)
    def test_non_superuser_cannot_run_or_see_verification_actions(self):
        staff = User.objects.create_user(
            "ordinary_staff",
            "ordinary-staff@example.test",
            "StrongPass123!",
            is_staff=True,
        )
        model_admin = UserProfileAdmin(UserProfile, admin.site)
        request = RequestFactory().get("/admin/items/userprofile/")
        request.user = staff
        actions = model_admin.get_actions(request)
        self.assertNotIn("mark_email_verified", actions)
        self.assertNotIn("mark_email_unverified", actions)
        with self.assertRaises(PermissionDenied):
            model_admin.mark_email_verified(
                request,
                UserProfile.objects.filter(pk=self.profile.pk),
            )
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.email_verified_at)

    @override_settings(DEBUG=False)
    def test_manual_verification_actions_are_disabled_outside_local_debug(self):
        model_admin = UserProfileAdmin(UserProfile, admin.site)
        request = RequestFactory().get("/admin/items/userprofile/")
        request.user = self.superuser
        actions = model_admin.get_actions(request)
        self.assertNotIn("mark_email_verified", actions)
        self.assertNotIn("mark_email_unverified", actions)
        with self.assertRaises(PermissionDenied):
            model_admin.mark_email_verified(
                request,
                UserProfile.objects.filter(pk=self.profile.pk),
            )

    def test_new_account_is_not_verified_implicitly(self):
        account = User.objects.create_user(
            "new_unverified_account",
            "new-account@example.test",
            "StrongPass123!",
        )
        profile, _ = UserProfile.objects.get_or_create(user=account)
        self.assertIsNone(profile.email_verified_at)

    @override_settings(DEBUG=True, OPEN_UNIVERSITY_ACCESS=True)
    def test_admin_verification_unlocks_claim_form_and_unverify_locks_it_again(self):
        report = ItemReport.objects.create(
            owner=self.superuser,
            scope=ItemReport.Scope.UNIVERSITY,
            report_type=ItemReport.ReportType.FOUND,
            title="Fictional found phone",
            description="A fictional report used only by this test.",
            category=ItemReport.Category.ELECTRONICS,
            colour="black",
        )
        claim_url = reverse("contact_request_create", args=[report.pk])
        self.client.force_login(self.account)
        denied = self.client.get(claim_url)
        self.assertEqual(denied.status_code, 403)
        self.assertContains(denied, "superuser can verify the account", status_code=403)

        self.run_action("mark_email_verified")
        self.client.force_login(self.account)
        self.assertEqual(self.client.get(claim_url).status_code, 200)

        self.run_action("mark_email_unverified")
        self.client.force_login(self.account)
        self.assertEqual(self.client.get(claim_url).status_code, 403)

    def test_rejected_claim_does_not_create_a_conversation(self):
        report = ItemReport.objects.create(
            owner=self.superuser,
            scope=ItemReport.Scope.INTERNATIONAL,
            report_type=ItemReport.ReportType.FOUND,
            title="Fictional rejected claim item",
            description="A fictional report used only by this test.",
            category=ItemReport.Category.ELECTRONICS,
            colour="black",
            country="TR",
            city="Istanbul",
        )
        claim = ContactRequest.objects.create(
            item_report=report,
            requesting_user=self.account,
            receiving_user=self.superuser,
            request_type=ContactRequest.RequestType.OWNERSHIP_CLAIM,
            initial_message="This fictional item may be mine.",
            truthful_confirmation=True,
        )
        self.assertFalse(hasattr(claim, "conversation"))
        updated, conversation = OwnershipVerificationService.change_status(
            claim=claim,
            actor=self.superuser,
            action="reject",
        )
        self.assertEqual(updated.status, ContactRequest.Status.REJECTED)
        self.assertIsNone(conversation)
        self.assertFalse(hasattr(updated, "conversation"))


class StructuredChoiceTranslationTests(TestCase):
    def test_turkish_placeholders_and_colour_are_translated(self):
        with translation.override("tr"):
            form = ItemReportForm(report_type="lost", scope="international")
            self.assertEqual(form.fields["primary_colour"].choices[0][1], "Bir ana renk seçin")
            self.assertEqual(form.fields["secondary_colour"].choices[0][1], "Belirtilmemiş")
            self.assertEqual(dict(form.fields["primary_colour"].choices)["black"], "Siyah")

    def test_arabic_placeholders_and_colour_are_translated(self):
        with translation.override("ar"):
            form = ItemReportForm(report_type="lost", scope="international")
            self.assertEqual(form.fields["primary_colour"].choices[0][1], "اختر لونًا أساسيًا")
            self.assertEqual(form.fields["secondary_colour"].choices[0][1], "غير محدد")
            self.assertEqual(dict(form.fields["primary_colour"].choices)["black"], "أسود")
