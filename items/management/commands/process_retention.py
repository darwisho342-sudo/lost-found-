from django.core.management.base import BaseCommand

from items.lifecycle import ReportLifecycleService
from items.return_service import ReturnWorkflowService


class Command(BaseCommand):
    help = "Expire old reports, send safe warnings, and purge expired private delivery details."

    def handle(self, *args, **options):
        expired = ReportLifecycleService.process_expiration()
        purged = ReturnWorkflowService.purge_expired_private_delivery_data()
        self.stdout.write(self.style.SUCCESS(f"Expired {expired} reports; purged {purged} delivery records."))
