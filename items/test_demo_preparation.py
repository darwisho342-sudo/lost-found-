from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import translation

from .models import ContactRequest, Conversation, ItemReport, Notification, ReturnArrangement
from .services import MatchingService
from .tests import MediaTestCase
from .university import UniversityAccessService


@override_settings(OPEN_UNIVERSITY_ACCESS=True)
class DemoPreparationTests(MediaTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        call_command("seed_data", verbosity=0)

    def tearDown(self):
        translation.activate("en")
        super().tearDown()

    def setUp(self):
        super().setUp()
        translation.activate("en")

    def test_demo_accounts_keep_expected_roles_and_mode_access(self):
        student = User.objects.get(username="demo_student")
        helper = User.objects.get(username="demo_helper")
        personal = User.objects.get(username="international_owner")
        security = User.objects.get(username="security_staff")
        administrator = User.objects.get(username="campus_admin")

        for normal_user in (student, helper, personal):
            with self.subTest(username=normal_user.username):
                self.assertFalse(normal_user.is_staff)
                self.assertFalse(normal_user.is_superuser)
                self.assertTrue(
                    UniversityAccessService.can_access_scope(normal_user, ItemReport.Scope.UNIVERSITY)
                )
                self.assertTrue(
                    UniversityAccessService.can_access_scope(normal_user, ItemReport.Scope.INTERNATIONAL)
                )
        self.assertTrue(security.is_staff)
        self.assertFalse(security.is_superuser)
        self.assertTrue(security.has_perm("items.manage_custody"))
        self.assertTrue(administrator.is_staff)
        self.assertTrue(administrator.is_superuser)

    def test_seeded_matches_qualify_and_create_safe_notifications(self):
        university_lost = ItemReport.objects.get(title="Black wireless headphones")
        university_found = ItemReport.objects.get(title="Black headphones in case")
        international_lost = ItemReport.objects.get(title="Black Samsung phone", report_type="lost")
        international_found = ItemReport.objects.get(title="Black Samsung phone", report_type="found")

        for lost, found in (
            (university_lost, university_found),
            (international_lost, international_found),
        ):
            with self.subTest(scope=lost.scope):
                result = MatchingService.compare(lost, found)
                self.assertGreaterEqual(result.total_score, MatchingService.strong_match_score)
                suggestions = MatchingService.find_matches(lost)
                self.assertIn(found, [suggestion.found_item for suggestion in suggestions])
                self.assertTrue(
                    Notification.objects.filter(
                        recipient=lost.owner,
                        notification_type=Notification.NotificationType.STRONG_MATCH,
                    ).exists()
                )
        self.assertNotEqual(university_lost.scope, international_lost.scope)

    def test_pending_claim_is_private_and_has_no_premature_conversation(self):
        claim = ContactRequest.objects.get(
            item_report__title="Black headphones in case",
            requesting_user__username="demo_student",
        )
        self.assertEqual(claim.status, ContactRequest.Status.PENDING)
        self.assertTrue(claim.answers.exists())
        self.assertFalse(hasattr(claim, "conversation"))

        self.client.force_login(User.objects.get(username="international_owner"))
        response = self.client.get(reverse("contact_request_detail", args=(claim.pk,)))
        self.assertEqual(response.status_code, 403)

    def test_completed_return_uses_completed_claim_conversation_and_confirmations(self):
        report = ItemReport.objects.get(title="Returned red carry-on suitcase")
        claim = ContactRequest.objects.get(item_report=report)
        arrangement = ReturnArrangement.objects.get(contact_request=claim)
        conversation = Conversation.objects.get(approved_contact_request=claim)

        self.assertEqual(report.status, ItemReport.Status.RESOLVED)
        self.assertEqual(claim.status, ContactRequest.Status.COMPLETED)
        self.assertEqual(arrangement.status, "received")
        self.assertIsNotNone(arrangement.finder_confirmed_at)
        self.assertIsNotNone(arrangement.owner_confirmed_at)
        self.assertEqual(conversation.status, Conversation.DealStatus.COMPLETED)
        self.assertFalse(conversation.is_active)

        self.client.force_login(claim.requesting_user)
        response = self.client.get(reverse("return_arrangement", args=(claim.pk,)))
        self.assertContains(response, "Return completed")
        self.assertNotContains(response, "Save return arrangement")
        self.assertEqual(
            self.client.post(reverse("return_confirmation", args=(claim.pk, "owner"))).status_code,
            403,
        )

    def test_demo_role_direct_url_permissions(self):
        normal = User.objects.get(username="demo_student")
        security = User.objects.get(username="security_staff")
        administrator = User.objects.get(username="campus_admin")
        other_report = ItemReport.objects.get(
            owner__username="demo_helper", title="Black headphones in case"
        )

        self.client.force_login(normal)
        self.assertEqual(self.client.get(reverse("management_dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("management_custody")).status_code, 403)
        self.assertEqual(self.client.get(reverse("item_edit", args=(other_report.pk,))).status_code, 403)

        self.client.force_login(security)
        self.assertEqual(self.client.get(reverse("management_custody")).status_code, 200)

        self.client.force_login(administrator)
        self.assertEqual(self.client.get(reverse("management_dashboard")).status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_representative_screenshot_targets_render(self):
        student = User.objects.get(username="demo_student")
        university_lost = ItemReport.objects.get(title="Black wireless headphones")
        pending_claim = ContactRequest.objects.get(
            item_report__title="Black headphones in case",
            requesting_user=student,
        )
        self.client.force_login(student)
        for url in (
            reverse("user_dashboard"),
            reverse("item_create_lost"),
            reverse("item_create_found"),
            university_lost.get_absolute_url(),
            reverse("item_matches", args=(university_lost.pk,)),
            reverse("notification_list"),
            reverse("contact_request_detail", args=(pending_claim.pk,)),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        returned_claim = ContactRequest.objects.get(
            item_report__title="Returned red carry-on suitcase"
        )
        self.client.force_login(returned_claim.requesting_user)
        for url in (
            reverse("contact_request_detail", args=(returned_claim.pk,)),
            reverse("conversation_detail", args=(returned_claim.conversation.pk,)),
            reverse("return_arrangement", args=(returned_claim.pk,)),
            returned_claim.item_report.get_absolute_url(),
        ):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

        self.client.logout()
        self.assertContains(self.client.get("/tr/"), 'lang="tr"')
        self.assertContains(self.client.get("/ar/"), 'lang="ar" dir="rtl"')
