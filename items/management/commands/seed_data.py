from datetime import timedelta
from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image, ImageDraw

from items.models import ItemReport, UserProfile


class Command(BaseCommand):
    help = "Create fictional, repeatable FindMatch demonstration data."

    users = (
        ("demo_student", "student@example.invalid", False, "FindMatchDemo123!"),
        ("demo_helper", "helper@example.invalid", False, "FindMatchDemo123!"),
        ("campus_admin", "admin@example.invalid", True, "AdminDemo123!"),
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

    def handle(self, *args, **options):
        user_objects = {}
        for username, email, is_staff, password in self.users:
            user, _ = User.objects.get_or_create(username=username, defaults={"email": email})
            user.email = email
            user.is_staff = is_staff
            user.is_superuser = is_staff
            user.set_password(password)
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            if not profile.email_verified_at:
                profile.email_verified_at = timezone.now()
                profile.save(update_fields=("email_verified_at", "updated_at"))
            user_objects[username] = user

        today = timezone.localdate()
        created_count = 0
        for index, (username, report_type, title, description, category, colour, location, days_ago, rgb) in enumerate(self.reports, start=1):
            report, created = ItemReport.objects.get_or_create(
                owner=user_objects[username],
                title=title,
                defaults={
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
            report.primary_colour = report.primary_colour or colour.casefold().replace(" ", "_")
            if report.primary_colour not in dict(report._meta.get_field("primary_colour").choices):
                report.primary_colour = "not_sure"
            report.country = report.country or "Türkiye"
            report.city = report.city or "Istanbul"
            report.place_type = report.place_type or "university_school"
            report.place_name = report.place_name or report.get_campus_location_display()
            report.expires_at = report.expires_at or timezone.now() + timedelta(days=90)
            report.save()

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
