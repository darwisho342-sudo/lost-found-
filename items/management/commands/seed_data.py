from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image, ImageDraw

from items.alerts import AlertService
from items.models import (
    ClaimAppeal, ContactRequest, Conversation, CustodyMovement, CustodyRecord, ItemReport,
    Notification, StorageIncident, UserProfile,
    UniversityLocation,
)
from items.university import UniversityAccessService


class Command(BaseCommand):
    help = "Create fictional, repeatable FindMatch demonstration data."

    users = (
        ("demo_student", "demo.student@st.biruni.edu.tr", False, False, "FindMatchDemo123!"),
        ("demo_helper", "demo.helper@st.biruni.edu.tr", False, False, "FindMatchDemo123!"),
        ("security_staff", "security@st.biruni.edu.tr", True, False, "SecurityDemo123!"),
        ("campus_admin", "admin@st.biruni.edu.tr", True, True, "AdminDemo123!"),
        ("international_owner", "owner.personal@example.com", False, False, "FindMatchDemo123!"),
        ("international_finder", "finder.personal@example.com", False, False, "FindMatchDemo123!"),
    )

    reports = (
        ("demo_student", "lost", "Black wireless headphones", "Black over-ear wireless headphones in a small hard case.", "electronics", "Black", "library", 1, (25, 32, 42)),
        ("demo_helper", "found", "Black headphones in case", "Black wireless over-ear headphones found inside a hard case.", "electronics", "black", "library", 0, (30, 36, 48)),
        ("demo_student", "lost", "Blue canvas backpack", "Blue canvas backpack with two front pockets and a notebook inside.", "bags", "Blue", "cafeteria", 3, (30, 64, 175)),
        ("demo_helper", "found", "Blue student backpack", "Blue canvas student backpack with front pockets.", "bags", "blue", "cafeteria", 2, (35, 74, 190)),
        ("demo_student", "lost", "Silver house keys", "Three silver keys on a round green keyring.", "keys", "Silver", "main_entrance", 7, (148, 163, 184)),
        ("demo_helper", "found", "Keys with green keyring", "Three silver keys attached to a green circular keyring.", "keys", "silver", "main_entrance", 6, (135, 150, 170)),
        ("demo_student", "lost", "Calculus textbook", "Red covered calculus textbook with handwritten notes.", "books", "Red", "classroom", 12, (185, 28, 28)),
        ("demo_helper", "found", "Brown wallet", "Small brown wallet found near the sports seats.", "wallets", "Brown", "sports_area", 1, (120, 72, 45)),
        ("demo_student", "found", "USB flash drive", "Small white USB drive found beside a laboratory computer.", "electronics", "White", "laboratory", 4, (226, 232, 240)),
        ("demo_helper", "lost", "Student document folder", "Clear folder containing fictional course notes.", "documents", "Clear", "student_affairs", 5, (196, 220, 235)),
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-demo", action="store_true",
            help="Reset only reports and workflow records owned by the six documented demo usernames.",
        )

    def handle(self, *args, **options):
        if options["reset_demo"]:
            demo_usernames = [row[0] for row in self.users]
            demo_reports = ItemReport.objects.filter(owner__username__in=demo_usernames)
            demo_custody = CustodyRecord.objects.filter(found_report__in=demo_reports)
            StorageIncident.objects.filter(custody_record__in=demo_custody).delete()
            CustodyMovement.objects.filter(custody_record__in=demo_custody).delete()
            demo_custody.delete()
            ClaimAppeal.objects.filter(contact_request__item_report__in=demo_reports).delete()
            deleted, _ = demo_reports.delete()
            Notification.objects.filter(recipient__username__in=demo_usernames).delete()
            self.stdout.write(f"Removed {deleted} records owned by documented demo accounts; user accounts were retained.")
        user_objects = {}
        for username, email, is_staff, is_superuser, password in self.users:
            user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
            user.email = email
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.is_active = True
            user.set_password(password)
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if not profile.email_verified_at:
                profile.email_verified_at = timezone.now()
            profile.university_eligible = UniversityAccessService.email_is_eligible(email)
            profile.preferred_scope = "university" if profile.university_eligible else "international"
            profile.university_eligibility_lost_at = None
            profile.save(update_fields=(
                "email_verified_at", "university_eligible", "preferred_scope",
                "university_eligibility_lost_at", "updated_at",
            ))
            user_objects[username] = user

        today = timezone.localdate()
        campus_locations = {}
        for value, label in ItemReport.CampusLocation.choices:
            if value in (ItemReport.CampusLocation.OTHER, ItemReport.CampusLocation.NOT_SURE):
                continue
            location = UniversityLocation.objects.filter(
                campus="Main Campus", location_type=value,
            ).order_by("pk").first()
            if location is None:
                location = UniversityLocation.objects.create(
                    campus="Main Campus", building="", general_area=str(label),
                    location_type=value if value in dict(ItemReport.CampusLocation.choices) else "not_sure",
                )
            campus_locations[value] = location
        created_count = 0
        for index, (username, report_type, title, description, category, colour, location, days_ago, rgb) in enumerate(self.reports, start=1):
            report, created = ItemReport.objects.get_or_create(
                owner=user_objects[username],
                title=title,
                defaults={
                    "scope": ItemReport.Scope.UNIVERSITY,
                    "report_type": report_type,
                    "description": description,
                    "category": category,
                    "colour": colour,
                    "campus_location": location,
                    "item_date": today - timedelta(days=days_ago),
                    "status": ItemReport.Status.ACTIVE,
                    "image": self.make_image(title, rgb, index),
                },
            )
            if created:
                created_count += 1
            structured_types = {
                "electronics": "headphones" if "headphone" in title.casefold() else "usb_drive",
                "bags": "backpack", "keys": "house_keys", "books": "textbook",
                "wallets": "wallet", "documents": "notebook",
            }
            report.item_type = report.item_type or structured_types.get(category, "not_sure")
            report.scope = ItemReport.Scope.UNIVERSITY
            report.primary_colour = report.primary_colour or colour.casefold().replace(" ", "_")
            if report.primary_colour not in dict(report._meta.get_field("primary_colour").choices):
                report.primary_colour = "not_sure"
            report.country = report.country or "Türkiye"
            report.city = report.city or "Istanbul"
            report.place_type = report.place_type or "university_school"
            report.place_name = report.place_name or report.get_campus_location_display()
            report.expires_at = report.expires_at or timezone.now() + timedelta(days=90)
            report.university_location = report.university_location or campus_locations.get(location)
            if "headphone" in title.casefold():
                report.secondary_colour = "grey"
                report.brand = "sony"
                report.model = "WH Demo"
            report.save()

        international_defaults = {
            "report_type": ItemReport.ReportType.LOST,
            "scope": ItemReport.Scope.INTERNATIONAL,
            "description": "Black Samsung phone with a dark blue case.",
            "additional_details": "Black Samsung phone with a dark blue case.",
            "category": "electronics", "item_type": "mobile_phone", "colour": "Black",
            "primary_colour": "black", "secondary_colour": "dark_blue", "brand": "samsung",
            "model": "Galaxy Demo", "country": "TR", "region": "Marmara",
            "city": "Istanbul", "district": "Kadikoy", "place_type": "public_transport",
            "place_name": "Kadikoy Station", "public_location": "Near the public station entrance",
            "item_date": today - timedelta(days=1), "status": ItemReport.Status.ACTIVE,
        }
        international_lost, _ = ItemReport.objects.update_or_create(
            owner=user_objects["international_owner"], title="Black Samsung phone",
            defaults=international_defaults,
        )
        international_found_defaults = dict(international_defaults)
        international_found_defaults.update({
            "report_type": ItemReport.ReportType.FOUND,
            "description": "Black Samsung phone with a dark blue case.",
            "additional_details": "Black Samsung phone with a dark blue case.",
            "item_date": today,
        })
        international_found, _ = ItemReport.objects.update_or_create(
            owner=user_objects["international_finder"], title="Black Samsung phone",
            defaults=international_found_defaults,
        )
        international_claim, _ = ContactRequest.objects.get_or_create(
            item_report=international_found, requesting_user=user_objects["international_owner"],
            receiving_user=user_objects["international_finder"],
            defaults={"request_type": ContactRequest.RequestType.OWNERSHIP_CLAIM,
                      "initial_message": "I can verify this phone privately.",
                      "loss_location": "Kadikoy", "loss_timeframe": "Yesterday",
                      "truthful_confirmation": True, "status": ContactRequest.Status.PENDING},
        )
        AlertService.notify_strong_matches(international_lost)

        lost_phone = ItemReport.objects.get(owner=user_objects["demo_student"], title="Black wireless headphones")
        found_phone = ItemReport.objects.get(owner=user_objects["demo_helper"], title="Black headphones in case")
        claim, _ = ContactRequest.objects.get_or_create(
            item_report=found_phone, requesting_user=user_objects["demo_student"],
            receiving_user=user_objects["demo_helper"],
            defaults={"request_type": ContactRequest.RequestType.OWNERSHIP_CLAIM,
                      "initial_message": "I believe this is my item and can verify it privately.",
                      "truthful_confirmation": True, "status": ContactRequest.Status.PENDING},
        )
        Conversation.objects.get_or_create(
            item_report=lost_phone, first_participant=user_objects["demo_student"],
            second_participant=user_objects["demo_helper"], approved_contact_request=claim,
        )
        custody, custody_created = CustodyRecord.objects.get_or_create(
            found_report=found_phone,
            defaults={"reference": "FM-DEMO-001", "received_by": user_objects["security_staff"],
                      "intake_point": "University Lost and Found Office",
                      "storage_reference": "Demo cabinet A / shelf 1",
                      "status": CustodyRecord.Status.STORED},
        )
        if custody_created:
            CustodyMovement.objects.create(
                custody_record=custody, event_type="intake", recorded_by=user_objects["security_staff"],
                safe_note="Demo item received into University custody.",
            )
        AlertService.notify_strong_matches(lost_phone)
        Notification.objects.get_or_create(
            recipient=user_objects["demo_student"], deduplication_key="demo:claim-ready",
            defaults={"notification_type": Notification.NotificationType.NEW_CLAIM,
                      "title": "Demo ownership workflow",
                      "safe_message": "A fictional local claim is ready for demonstration.",
                      "item_report": found_phone},
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data ready: {len(user_objects)} users and {len(self.reports)} reports "
                f"({created_count} new)."
            )
        )

    @staticmethod
    def make_image(title, rgb, index):
        image = Image.new("RGB", (900, 600), rgb)
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((35, 35, 865, 565), outline="white", width=5)
        drawing.text((70, 270), title, fill="white")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return ContentFile(buffer.getvalue(), name=f"demo-item-{index}.jpg")
