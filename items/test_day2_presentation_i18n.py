from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext

from .forms import ItemReportForm


@override_settings(OPEN_UNIVERSITY_ACCESS=True)
class Day2PresentationAndTranslationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "day2_i18n_user", email="day2@example.com", password="StrongPass123!"
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["findmatch_scope"] = "university"
        session.save()

    def test_report_form_renders_translated_controls_and_javascript_messages(self):
        expected = {
            "tr": ("Bize ne olduğunu anlatın", "Ek özel konum ayrıntıları", "Seçili görseli kaldır"),
            "ar": ("أخبرنا ماذا حدث", "تفاصيل إضافية للموقع الخاص", "إزالة الصورة المحددة"),
        }
        for language, strings in expected.items():
            with self.subTest(language=language), translation.override(language):
                response = self.client.get(reverse("report_create", args=["lost"]))
                self.assertEqual(response.status_code, 200)
                for translated_string in strings:
                    self.assertContains(response, translated_string)
                self.assertContains(response, f'lang="{language}"')
                self.assertContains(response, 'data-remove-image-label=')

    def test_arabic_report_form_uses_rtl_without_reversing_date_or_file_controls(self):
        with translation.override("ar"):
            response = self.client.get(reverse("report_create", args=["found"]))
        self.assertContains(response, 'dir="rtl"')
        self.assertContains(response, 'type="date"')
        self.assertContains(response, 'type="file"', count=2)
        self.assertContains(response, "css/core/rtl.css")

        rtl_css = (Path(settings.BASE_DIR) / "static/css/core/rtl.css").read_text(encoding="utf-8")
        self.assertIn('input[type="date"]', rtl_css)
        self.assertIn('input[type="file"]', rtl_css)
        self.assertIn("direction:ltr", rtl_css.replace(" ", ""))

    def test_report_field_labels_and_help_text_are_localized(self):
        expectations = {
            "tr": {
                "title": "Başlık",
                "brand": "Marka",
                "public_location": "Güvenli genel konum",
                "image": "Ana görsel",
            },
            "ar": {
                "title": "العنوان",
                "brand": "العلامة التجارية",
                "public_location": "الموقع العام الآمن",
                "image": "الصورة الرئيسية",
            },
        }
        for language, labels in expectations.items():
            with self.subTest(language=language), translation.override(language):
                form = ItemReportForm(report_type="found", scope="international")
                for field_name, expected_label in labels.items():
                    self.assertEqual(str(form.fields[field_name].label), expected_label)
                self.assertNotEqual(
                    str(form.fields["image"].help_text),
                    "Maximum 5 MB. Do not upload images showing private numbers, PINs, addresses, messages, or unrelated people's faces.",
                )

    def test_server_validation_error_is_rendered_with_its_field(self):
        response = self.client.post(
            reverse("report_create", args=["lost"]),
            {"scope": "university", "submission_action": "submit"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'for="id_category"')
        self.assertContains(response, 'class="invalid-feedback d-block"')
        self.assertIn("category", response.context["form"].errors)

    def test_mobile_report_css_keeps_controls_accessible_and_images_responsive(self):
        css = (Path(settings.BASE_DIR) / "static/css/pages/report-form.css").read_text(encoding="utf-8")
        compact = css.replace(" ", "")
        self.assertIn("@media(max-width:575.98px)", compact)
        self.assertIn('flex:00100%', compact)
        self.assertIn("min-height:46px", compact)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("[data-additional-image-previews] img", css)
        self.assertIn("max-width:100%", compact)
        self.assertNotIn(".wizard-actions .btn-outline-primary { display:none", css)

    def test_day2_catalog_contains_translations_for_dynamic_image_errors(self):
        messages = (
            "Use a JPG, JPEG, PNG, or WebP image file.",
            "The uploaded file does not have an allowed image content type.",
            "The image contents, filename extension, and content type do not match.",
            "Location is unavailable. Enter the fields manually.",
        )
        for language in ("tr", "ar"):
            with self.subTest(language=language), translation.override(language):
                for message in messages:
                    self.assertNotEqual(gettext(message), message)
