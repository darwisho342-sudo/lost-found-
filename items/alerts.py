"""Saved-search and strong-match notification orchestration."""

from django.urls import reverse

from .models import ItemReport, Notification, SavedSearch, SavedSearchNotification
from .notification_service import NotificationService
from .services import MatchingService


class AlertService:
    @staticmethod
    def _matches_filters(report, filters):
        for field, value in filters.items():
            if value and field in SavedSearch.public_filter_keys():
                current = getattr(report, field, None)
                if field == "date_from" and str(report.item_date) < value:
                    return False
                if field == "date_to" and str(report.item_date) > value:
                    return False
                if field not in ("date_from", "date_to") and str(current or "").casefold() != str(value).casefold():
                    return False
        return True

    @classmethod
    def notify_saved_searches(cls, report):
        if report.report_type != ItemReport.ReportType.FOUND or report.status != ItemReport.Status.ACTIVE:
            return
        for saved in SavedSearch.objects.filter(is_active=True).select_related("user"):
            if not cls._matches_filters(report, saved.filters):
                continue
            link, created = SavedSearchNotification.objects.get_or_create(saved_search=saved, item_report=report)
            if not created:
                continue
            notification = NotificationService.create(
                recipient=saved.user, notification_type=Notification.NotificationType.SAVED_SEARCH_MATCH,
                title="New item for your saved search",
                safe_message="A new public Found report matches your saved filters.",
                item_report=report, destination_url=reverse("item_detail", args=(report.pk,)),
                deduplication_key=f"saved-search:{saved.pk}:{report.pk}",
            )
            link.notification = notification
            link.save(update_fields=("notification",))

    @classmethod
    def notify_strong_matches(cls, report):
        for result in MatchingService.find_matches(report):
            if result.total_score < MatchingService.strong_match_score:
                continue
            other = result.found_item if report.pk == result.lost_item.pk else result.lost_item
            for target in (report, other):
                profile = getattr(target.owner, "profile", None)
                if profile and not profile.notify_strong_matches:
                    continue
                pair = sorted((report.pk, other.pk))
                NotificationService.create(
                    recipient=target.owner, notification_type=Notification.NotificationType.STRONG_MATCH,
                    title="Strong possible match",
                    safe_message="A public report has a strong rule-based similarity score. This is not proof of ownership.",
                    item_report=target, destination_url=reverse("item_matches", args=(target.pk,)),
                    deduplication_key=f"strong-match:{pair[0]}:{pair[1]}:{target.owner_id}",
                )
