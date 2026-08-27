"""Privacy-safe duplicate report checks without image recognition."""

from difflib import SequenceMatcher
from datetime import timedelta

from .models import ItemReport
from .services import MatchingService


class DuplicateReportService:
    @classmethod
    def candidates(cls, report):
        if not report.item_date:
            return []
        queryset = ItemReport.objects.filter(
            owner=report.owner, scope=report.scope, report_type=report.report_type, category=report.category,
            item_type=report.item_type, is_deleted=False,
            item_date__range=(report.item_date - timedelta(days=2), report.item_date + timedelta(days=2)),
        ).exclude(pk=report.pk)
        duplicate_ids = []
        normalized_title = MatchingService.normalize_text(report.title)
        for candidate in queryset[:20]:
            title_ratio = SequenceMatcher(None, normalized_title, MatchingService.normalize_text(candidate.title)).ratio()
            if report.scope == ItemReport.Scope.UNIVERSITY:
                same_location = (
                    candidate.university_location_id == report.university_location_id
                    and candidate.campus_location == report.campus_location
                )
            else:
                same_location = (
                    MatchingService.normalize_text(candidate.country) == MatchingService.normalize_text(report.country)
                    and MatchingService.normalize_text(candidate.city) == MatchingService.normalize_text(report.city)
                )
            same_hash = bool(report.image_sha256 and report.image_sha256 == candidate.image_sha256)
            if (title_ratio >= .88 and same_location) or same_hash:
                duplicate_ids.append(candidate.pk)
        return duplicate_ids
