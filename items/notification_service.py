from django.utils import timezone

from .models import Notification


class NotificationService:
    @staticmethod
    def create(
        *, notification_type, title, safe_message, deduplication_key,
        recipient=None, recipient_id=None,
        conversation=None, item_report=None, destination_url=""
    ):
        defaults = {
            "notification_type": notification_type,
            "title": title,
            "safe_message": safe_message,
            "conversation": conversation,
            "item_report": item_report,
            "destination_url": destination_url,
        }
        if recipient is not None:
            defaults["recipient"] = recipient
        else:
            defaults["recipient_id"] = recipient_id
        notification, _ = Notification.objects.get_or_create(
            deduplication_key=deduplication_key,
            defaults=defaults,
        )
        return notification

    @staticmethod
    def mark_conversation_messages_read(*, recipient, conversation):
        return Notification.objects.filter(
            recipient=recipient,
            conversation=conversation,
            notification_type=Notification.NotificationType.NEW_MESSAGE,
            is_read=False,
        ).update(is_read=True, read_at=timezone.now())
