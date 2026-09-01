from datetime import date
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import StreamingHttpResponse
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from PIL import Image

from .forms import ItemReportForm, OwnershipClaimForm
from .models import (
    MAX_IMAGE_SIZE, ClaimEvidence, ContactRequest, ItemReport, ReportImage,
    UniversityLocation, private_evidence_storage,
)


def image_upload(name="item.jpg", image_format="JPEG", content_type="image/jpeg", colour="blue"):
    output = BytesIO()
    Image.new("RGB", (48, 48), colour).save(output, format=image_format)
    return SimpleUploadedFile(name, output.getvalue(), content_type=content_type)


@override_settings(OPEN_UNIVERSITY_ACCESS=True)
class ReportImageAndPermissionTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_directory = TemporaryDirectory()
        cls.private_directory = TemporaryDirectory()
        cls.media_override = override_settings(
            MEDIA_ROOT=cls.media_directory.name,
            PRIVATE_MEDIA_ROOT=cls.private_directory.name,
        )
        cls.media_override.enable()
        cls.old_private_location = private_evidence_storage._location
        private_evidence_storage._location = Path(cls.private_directory.name)
        private_evidence_storage.__dict__.pop("base_location", None)
        private_evidence_storage.__dict__.pop("location", None)

    @classmethod
    def tearDownClass(cls):
        private_evidence_storage._location = cls.old_private_location
        private_evidence_storage.__dict__.pop("base_location", None)
        private_evidence_storage.__dict__.pop("location", None)
        cls.media_override.disable()
        cls.private_directory.cleanup()
        cls.media_directory.cleanup()
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(
            "image_owner", email="owner@example.com", password="StrongPass123!"
        )
        self.other = User.objects.create_user(
            "image_other", email="other@example.com", password="StrongPass123!"
        )
        self.staff = User.objects.create_user(
            "image_staff", email="staff@example.com", password="StrongPass123!",
            is_staff=True,
        )
        self.client.force_login(self.owner)
        self.university_location = UniversityLocation.objects.create(
            campus="Main Campus", building="Library", general_area="Library",
            location_type="library",
        )
        session = self.client.session
        session["findmatch_scope"] = "university"
        session.save()

    def form_data(self, **overrides):
        data = {
            "scope": "university", "title": "Black backpack", "category": "bags",
            "item_type": "backpack", "primary_colour": "black", "brand": "no_visible_brand",
            "university_location": str(self.university_location.pk),
            "item_date": date.today().isoformat(),
            "submission_action": "submit",
        }
        data.update(overrides)
        return data

    def create_report(self, **overrides):
        values = {
            "owner": self.owner, "scope": "university", "report_type": "lost",
            "title": "Owner report", "description": "Public description",
            "category": "bags", "item_type": "backpack", "colour": "Black",
            "primary_colour": "black", "campus_location": "library",
            "university_location": self.university_location,
            "item_date": date.today(), "status": ItemReport.Status.ACTIVE,
        }
        values.update(overrides)
        return ItemReport.objects.create(**values)

    def test_valid_jpg_jpeg_png_and_webp_images_are_verified_and_safely_named(self):
        formats = (
            ("camera.jpg", "JPEG", "image/jpeg"),
            ("camera.jpeg", "JPEG", "image/jpeg"),
            ("camera.png", "PNG", "image/png"),
            ("camera.webp", "WEBP", "image/webp"),
        )
        for filename, image_format, content_type in formats:
            with self.subTest(filename=filename):
                form = ItemReportForm(
                    data=self.form_data(),
                    files={"image": image_upload(filename, image_format, content_type)},
                    report_type="lost", scope="university",
                )
                self.assertTrue(form.is_valid(), form.errors)
                report = form.save(commit=False)
                report.owner = self.owner
                report.report_type = "lost"
                report.save()
                stored_name = Path(report.image.name).name
                self.assertNotIn("camera", stored_name)
                self.assertRegex(stored_name, r"^[0-9a-f]{32}\.(?:jpg|png|webp)$")
                report.image.delete(save=False)
                report.delete()

    def test_more_than_three_images_is_rejected_without_losing_form_values(self):
        files = MultiValueDict({
            "image": [image_upload("primary.jpg")],
            "additional_images": [
                image_upload("two.jpg"), image_upload("three.jpg"), image_upload("four.jpg"),
            ],
        })
        form = ItemReportForm(
            data=self.form_data(title="Keep this title"), files=files,
            report_type="lost", scope="university",
        )
        self.assertFalse(form.is_valid())
        self.assertIn("additional_images", form.errors)
        self.assertEqual(form.data["title"], "Keep this title")

    def test_each_image_is_limited_to_five_megabytes(self):
        oversized = image_upload("large.jpg")
        oversized = SimpleUploadedFile(
            "large.jpg", oversized.read() + b"x" * (MAX_IMAGE_SIZE + 1),
            content_type="image/jpeg",
        )
        for field_name in ("image", "additional_images"):
            with self.subTest(field=field_name):
                files = MultiValueDict({field_name: [oversized]})
                form = ItemReportForm(
                    data=self.form_data(), files=files,
                    report_type="lost", scope="university",
                )
                self.assertFalse(form.is_valid())
                self.assertIn(field_name, form.errors)
                oversized.seek(0)

    def test_fake_forbidden_and_mismatched_files_are_rejected(self):
        png_bytes = image_upload("real.png", "PNG", "image/png").read()
        invalid_uploads = (
            SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg"),
            SimpleUploadedFile("vector.svg", b"<svg></svg>", content_type="image/svg+xml"),
            SimpleUploadedFile("program.exe", b"MZ\x00\x02", content_type="application/x-msdownload"),
            SimpleUploadedFile("wrong.jpg", png_bytes, content_type="image/jpeg"),
            SimpleUploadedFile("unknown.jpg", image_upload().read(), content_type="application/octet-stream"),
        )
        for upload in invalid_uploads:
            with self.subTest(filename=upload.name):
                form = ItemReportForm(
                    data=self.form_data(), files={"image": upload},
                    report_type="lost", scope="university",
                )
                self.assertFalse(form.is_valid())
                self.assertIn("image", form.errors)

    def test_editing_preserves_owner_and_ignores_staff_only_post_fields(self):
        report = self.create_report()
        response = self.client.post(reverse("item_edit", args=(report.pk,)), self.form_data(
            title="Updated by owner", owner=str(self.other.pk), status="resolved",
            is_hidden="1", is_reviewed="1",
        ))
        self.assertRedirects(response, report.get_absolute_url())
        report.refresh_from_db()
        self.assertEqual(report.owner, self.owner)
        self.assertEqual(report.title, "Updated by owner")
        self.assertEqual(report.status, ItemReport.Status.ACTIVE)
        self.assertFalse(report.is_hidden)
        self.assertFalse(report.is_reviewed)

    def test_owner_delete_and_close_require_confirmation_post_and_csrf(self):
        report = self.create_report()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        session = csrf_client.session
        session["findmatch_scope"] = "university"
        session.save()

        delete_url = reverse("item_delete", args=(report.pk,))
        confirmation = csrf_client.get(delete_url)
        self.assertContains(confirmation, "Yes, remove report")
        report.refresh_from_db()
        self.assertFalse(report.is_deleted)
        self.assertEqual(csrf_client.post(delete_url).status_code, 403)
        token = confirmation.cookies["csrftoken"].value
        response = csrf_client.post(delete_url, {"csrfmiddlewaretoken": token})
        self.assertRedirects(response, reverse("my_reports"))
        report.refresh_from_db()
        self.assertTrue(report.is_deleted)

        close_report = self.create_report(title="Close with confirmation")
        close_url = reverse("item_close", args=(close_report.pk,))
        confirmation = csrf_client.get(close_url)
        self.assertContains(confirmation, "Yes, mark closed")
        close_report.refresh_from_db()
        self.assertEqual(close_report.status, ItemReport.Status.ACTIVE)
        token = confirmation.cookies["csrftoken"].value
        self.assertEqual(csrf_client.post(close_url).status_code, 403)
        response = csrf_client.post(close_url, {"csrfmiddlewaretoken": token})
        self.assertRedirects(response, close_report.get_absolute_url())
        close_report.refresh_from_db()
        self.assertEqual(close_report.status, ItemReport.Status.CLOSED)

    def test_direct_urls_cannot_edit_delete_or_continue_another_users_report(self):
        report = self.create_report()
        self.client.force_login(self.other)
        edit_url = reverse("item_edit", args=(report.pk,))
        delete_url = reverse("item_delete", args=(report.pk,))
        self.assertEqual(self.client.get(edit_url).status_code, 403)
        self.assertEqual(self.client.post(edit_url, self.form_data(title="Stolen edit")).status_code, 403)
        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url).status_code, 403)
        report.refresh_from_db()
        self.assertEqual(report.owner, self.owner)
        self.assertFalse(report.is_deleted)

        report.status = ItemReport.Status.DRAFT
        report.save(update_fields=("status", "updated_at"))
        self.assertEqual(self.client.get(report.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(edit_url).status_code, 403)

    def test_private_sensitive_image_has_no_public_url_and_uses_protected_view(self):
        report = self.create_report(
            report_type="found", item_type="passport", image=image_upload("passport.jpg")
        )
        report.refresh_from_db()
        self.assertFalse(bool(report.image))
        self.assertTrue(bool(report.private_sensitive_image))
        with self.assertRaises(ValueError):
            _ = report.private_sensitive_image.url

        url = reverse("private_report_image", args=(report.pk,))
        self.client.logout()
        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.owner)
        owner_response = self.client.get(url)
        self.assertIsInstance(owner_response, StreamingHttpResponse)
        self.assertIn("attachment", owner_response["Content-Disposition"])
        owner_response.close()
        self.client.force_login(self.staff)
        staff_response = self.client.get(url)
        self.assertEqual(staff_response.status_code, 200)
        staff_response.close()

    def test_private_claim_evidence_is_verified_and_permission_checked(self):
        report = self.create_report(report_type="found")
        claim = ContactRequest.objects.create(
            item_report=report,
            requesting_user=self.other,
            receiving_user=self.owner,
            request_type=ContactRequest.RequestType.OWNERSHIP_CLAIM,
            initial_message="I can identify this item privately.",
            truthful_confirmation=True,
        )
        evidence = ClaimEvidence.objects.create(
            contact_request=claim,
            file=image_upload("evidence.jpg"),
        )
        with self.assertRaises(ValueError):
            _ = evidence.file.url
        url = reverse("claim_evidence_download", args=(evidence.pk,))

        self.client.logout()
        self.assertRedirects(self.client.get(url), f"{reverse('login')}?next={url}")
        stranger = User.objects.create_user("evidence_stranger")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.other)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        response.close()

    def test_claim_evidence_rejects_corrupt_and_mismatched_uploads(self):
        report = self.create_report(report_type="found")
        data = {
            "initial_message": "I can identify this item privately.",
            "loss_location": "Library",
            "loss_timeframe": "Yesterday",
            "truthful_confirmation": "on",
        }
        invalid_uploads = (
            SimpleUploadedFile("fake.jpg", b"not an image", content_type="image/jpeg"),
            SimpleUploadedFile(
                "wrong.jpg", image_upload("real.png", "PNG", "image/png").read(),
                content_type="image/jpeg",
            ),
            SimpleUploadedFile(
                "truncated.pdf", b"%PDF-1.7\nmissing trailer", content_type="application/pdf"
            ),
        )
        for upload in invalid_uploads:
            with self.subTest(filename=upload.name):
                form = OwnershipClaimForm(
                    data=data, files={"evidence": upload}, item_report=report
                )
                self.assertFalse(form.is_valid())
                self.assertIn("evidence", form.errors)

        valid = OwnershipClaimForm(
            data=data, files={"evidence": image_upload("proof.png", "PNG", "image/png")},
            item_report=report,
        )
        self.assertTrue(valid.is_valid(), valid.errors)
