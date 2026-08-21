from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from items.university import UniversityAccessService


class Command(BaseCommand):
    help = "Recalculate cached University eligibility from configured exact email domains."

    def handle(self, *args, **options):
        eligible_count = 0
        international_only_count = 0
        for user in User.objects.select_related("profile").iterator():
            profile = UniversityAccessService.synchronize_eligibility(user)
            if profile.university_eligible:
                eligible_count += 1
            else:
                international_only_count += 1
        self.stdout.write(self.style.SUCCESS(
            f"University access recalculated: {eligible_count} eligible, "
            f"{international_only_count} International-only."
        ))
