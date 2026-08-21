from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from .alerts import AlertService
from .forms import ItemReportForm, RegistrationForm, ReturnArrangementForm
from .models import (
    ClaimAppeal, ContactRequest, Conversation, CustodyRecord, ItemReport,
    Notification, ReturnArrangement, UserProfile,
)
from .return_service import ReturnWorkflowService
from .security import EmailVerificationService
from .services import MatchingService
from .university import UniversityAccessService


@override_settings(UNIVERSITY_EMAIL_DOMAINS=("st.biruni.edu.tr",))
class ScopeSelectorSwitchTests(TestCase):
    def verified_user(self, username, email, *, cached_eligibility=False, preferred_scope="international", is_staff=False):
        user = User.objects.create_user(
            username, email=email, password="StrongPass123!", is_staff=is_staff
        )
        UserProfile.objects.create(
            user=user, email_verified_at=timezone.now(),
            university_eligible=cached_eligibility, preferred_scope=preferred_scope,
        )
        return user

    def csrf_client(self, user):
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        client.get(reverse("home"))
        return client, client.cookies["csrftoken"].value

    def test_selector_renders_real_post_buttons_and_active_mode(self):
        user = self.verified_user("student", "student@st.biruni.edu.tr")
        client, token = self.csrf_client(user)
        session = client.session
        session["findmatch_scope"] = "university"
        session.save()
        response = client.get(reverse("home"))
        self.assertContains(response, 'type="submit" name="scope" value="university"')
        self.assertContains(response, 'type="submit" name="scope" value="international"')
        self.assertContains(response, 'scope-option active')
        self.assertNotContains(response, "onchange=")

    def test_eligible_button_recalculates_and_saves_university_scope(self):
        user = self.verified_user("eligible", "eligible@st.biruni.edu.tr")
        client, token = self.csrf_client(user)
        response = client.post(
            reverse("switch_scope"), {"scope": "university", "csrfmiddlewaretoken": token}
        )
        self.assertRedirects(response, reverse("user_dashboard"))
        user.profile.refresh_from_db()
        self.assertTrue(user.profile.university_eligible)
        self.assertEqual(user.profile.preferred_scope, "university")
        self.assertEqual(client.session["findmatch_scope"], "university")

    def test_staff_university_button_redirects_to_management_dashboard(self):
        user = self.verified_user("staff", "security@biruni.edu.tr", is_staff=True)
        client, token = self.csrf_client(user)
        response = client.post(
            reverse("switch_scope"), {"scope": "university", "csrfmiddlewaretoken": token}
        )
        self.assertRedirects(response, reverse("management_dashboard"))
        self.assertEqual(client.session["findmatch_scope"], "university")

    def test_personal_account_is_recalculated_and_gets_clear_error(self):
        user = self.verified_user(
            "personal", "person@example.com", cached_eligibility=True,
            preferred_scope="university",
        )
        client, token = self.csrf_client(user)
        response = client.post(
            reverse("switch_scope"), {"scope": "university", "csrfmiddlewaretoken": token}
        )
        self.assertContains(
            response,
            "University Mode is available only to verified Biruni University students",
            status_code=403,
        )
        user.profile.refresh_from_db()
        self.assertFalse(user.profile.university_eligible)
        self.assertEqual(user.profile.preferred_scope, "international")

    def test_international_button_saves_scope_for_personal_account(self):
        user = self.verified_user("personal", "person@example.com")
        client, token = self.csrf_client(user)
        response = client.post(
            reverse("switch_scope"), {"scope": "international", "csrfmiddlewaretoken": token}
        )
        self.assertRedirects(response, reverse("item_list"))
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.preferred_scope, "international")
        self.assertEqual(client.session["findmatch_scope"], "international")

    def test_endpoint_requires_login_post_csrf_and_exact_values(self):
        user = self.verified_user("eligible", "eligible@st.biruni.edu.tr")
        client = Client(enforce_csrf_checks=True)
        client.get(reverse("home"))
        anonymous_token = client.cookies["csrftoken"].value
        self.assertRedirects(
            client.post(
                reverse("switch_scope"),
                {"scope": "university", "csrfmiddlewaretoken": anonymous_token},
            ),
            reverse("login"),
        )
        self.assertEqual(
            client.session[UniversityAccessService.PENDING_SCOPE_KEY], "university"
        )
        client.force_login(user)
        self.assertEqual(client.get(reverse("switch_scope")).status_code, 405)
        self.assertEqual(
            client.post(reverse("switch_scope"), {"scope": "university"}).status_code, 403
        )
        client.get(reverse("home"))
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(
                reverse("switch_scope"), {"scope": "campus", "csrfmiddlewaretoken": token}
            ).status_code,
            400,
        )

    def test_exact_domain_check_normalizes_case_and_whitespace_and_rejects_deception(self):
        self.assertTrue(
            UniversityAccessService.email_is_eligible(
                "  STUDENT@ST.BIRUNI.EDU.TR  "
            )
        )
        self.assertFalse(
            UniversityAccessService.email_is_eligible(
                "student@st.biruni.edu.tr.example.com"
            )
        )
        self.assertFalse(
            UniversityAccessService.email_is_eligible(
                "student+st.biruni.edu.tr@gmail.com"
            )
        )

    def test_registration_normalizes_university_and_personal_email(self):
        university_form = RegistrationForm(data={
            "username": "normalized_student",
            "email": "  STUDENT@ST.BIRUNI.EDU.TR  ",
            "password1": "A-Strong-Passphrase-135!",
            "password2": "A-Strong-Passphrase-135!",
        })
        self.assertTrue(university_form.is_valid(), university_form.errors)
        university_user = university_form.save()
        self.assertEqual(university_user.email, "student@st.biruni.edu.tr")
        self.assertTrue(university_user.profile.university_eligible)

        personal_form = RegistrationForm(data={
            "username": "normalized_personal",
            "email": "  PERSON@GMAIL.COM  ",
            "password1": "A-Strong-Passphrase-246!",
            "password2": "A-Strong-Passphrase-246!",
        })
        self.assertTrue(personal_form.is_valid(), personal_form.errors)
        personal_user = personal_form.save()
        self.assertEqual(personal_user.email, "person@gmail.com")
        self.assertFalse(personal_user.profile.university_eligible)

    def test_pending_university_mode_completes_after_student_login(self):
        user = self.verified_user("pending_student", "student@st.biruni.edu.tr")
        anonymous = Client(enforce_csrf_checks=True)
        anonymous.get(reverse("home"))
        token = anonymous.cookies["csrftoken"].value
        self.assertRedirects(
            anonymous.post(
                reverse("switch_scope"),
                {"scope": "university", "csrfmiddlewaretoken": token},
            ),
            reverse("login"),
        )
        response = anonymous.post(reverse("login"), {
            "username": user.username, "password": "StrongPass123!",
            "csrfmiddlewaretoken": token,
        })
        self.assertRedirects(response, reverse("user_dashboard"))
        self.assertEqual(anonymous.session["findmatch_scope"], "university")
        self.assertNotIn(
            UniversityAccessService.PENDING_SCOPE_KEY, anonymous.session
        )

    def test_pending_university_mode_gives_personal_account_safe_fallback(self):
        user = self.verified_user("pending_personal", "student@gmail.com")
        anonymous = Client(enforce_csrf_checks=True)
        anonymous.get(reverse("home"))
        token = anonymous.cookies["csrftoken"].value
        anonymous.post(
            reverse("switch_scope"),
            {"scope": "university", "csrfmiddlewaretoken": token},
        )
        response = anonymous.post(reverse("login"), {
            "username": user.username, "password": "StrongPass123!",
            "csrfmiddlewaretoken": token,
        }, follow=True)
        self.assertRedirects(response, reverse("item_list"))
        self.assertContains(
            response,
            "University Mode is available only to verified Biruni University students",
        )
        self.assertEqual(anonymous.session["findmatch_scope"], "international")

    def test_direct_university_urls_cannot_bypass_personal_account_permissions(self):
        user = self.verified_user("direct_personal", "student@gmail.com")
        self.client.force_login(user)
        protected = reverse("report_create", args=("lost",))
        self.assertEqual(
            self.client.get(protected, {"scope": "university"}).status_code, 403
        )
        response = self.client.get(reverse("home"), {"scope": "university"})
        self.assertContains(response, "Continue to International Mode", status_code=403)

    def test_scope_selector_uses_valid_localized_post_urls(self):
        user = self.verified_user("localized_student", "student@st.biruni.edu.tr")
        self.client.force_login(user)
        for language in ("en", "tr", "ar"):
            with self.subTest(language=language), translation.override(language):
                switch_url = reverse("switch_scope")
                response = self.client.get(reverse("home"))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'method="post" action="{switch_url}"')
                self.assertContains(
                    response,
                    'type="submit" name="scope" value="university"',
                    count=2,
                )
                self.assertEqual(self.client.get(switch_url).status_code, 405)
                switched = self.client.post(switch_url, {"scope": "university"})
                self.assertRedirects(switched, reverse("user_dashboard"))

    def test_university_permission_feedback_is_translated_and_arabic_is_rtl(self):
        user = self.verified_user("translated_personal", "person@gmail.com")
        self.client.force_login(user)
        expected = {
            "en": "Continue to International Mode",
            "tr": "Uluslararası Moda devam et",
            "ar": "المتابعة إلى الوضع الدولي",
        }
        for language, label in expected.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(reverse("home"), {"scope": "university"})
                self.assertContains(response, label, status_code=403)
                if language == "ar":
                    self.assertContains(
                        response, '<html lang="ar" dir="rtl">', status_code=403
                    )

    def test_login_safe_next_invalid_login_and_logout_have_no_redirect_loop(self):
        user = self.verified_user("login_flow", "login@gmail.com")
        invalid = self.client.post(reverse("login"), {
            "username": user.username, "password": "wrong-password",
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertContains(invalid, "not recognised")
        external_next = "https://example.com/phishing"
        response = self.client.post(
            f'{reverse("login")}?next={external_next}',
            {"username": user.username, "password": "StrongPass123!", "next": external_next},
        )
        self.assertRedirects(response, reverse("home"))
        logout = self.client.post(reverse("logout"))
        self.assertRedirects(logout, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)


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
        university = self.verified_user("student", "student@st.biruni.edu.tr", university=True)
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
