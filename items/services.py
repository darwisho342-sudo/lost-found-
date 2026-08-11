import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from django.db.models import QuerySet

from .models import ItemReport


@dataclass(frozen=True)
class MatchResult:
    lost_item: ItemReport
    found_item: ItemReport
    category_points: int
    description_points: int
    colour_points: int
    location_points: int
    date_points: int

    @property
    def total_score(self):
        return min(
            100,
            self.category_points
            + self.description_points
            + self.colour_points
            + self.location_points
            + self.date_points,
        )


class MatchingService:
    """Calculate transparent, local match suggestions without storing them."""

    minimum_score = 50
    maximum_results = 5

    @staticmethod
    def normalize_text(value):
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))

    @classmethod
    def description_points(cls, first, second):
        first = cls.normalize_text(first)
        second = cls.normalize_text(second)
        if not first or not second:
            return 0
        return round(SequenceMatcher(None, first, second).ratio() * 25)

    @staticmethod
    def date_points(first_date, second_date):
        difference = abs((first_date - second_date).days)
        if difference == 0:
            return 15
        if difference == 1:
            return 13
        if difference <= 3:
            return 10
        if difference <= 7:
            return 7
        if difference <= 14:
            return 3
        return 0

    @classmethod
    def compare(cls, first, second):
        if first.report_type == second.report_type:
            raise ValueError("Matching requires one lost report and one found report.")
        lost_item = first if first.report_type == ItemReport.ReportType.LOST else second
        found_item = second if lost_item is first else first
        return MatchResult(
            lost_item=lost_item,
            found_item=found_item,
            category_points=25 if first.category == second.category else 0,
            description_points=cls.description_points(
                first.description, second.description
            ),
            colour_points=(
                20
                if cls.normalize_text(first.colour) == cls.normalize_text(second.colour)
                else 0
            ),
            location_points=(
                15 if first.campus_location == second.campus_location else 0
            ),
            date_points=cls.date_points(first.item_date, second.item_date),
        )

    @classmethod
    def find_matches(cls, report, queryset: QuerySet | None = None):
        opposite_type = (
            ItemReport.ReportType.FOUND
            if report.report_type == ItemReport.ReportType.LOST
            else ItemReport.ReportType.LOST
        )
        candidates = queryset if queryset is not None else ItemReport.objects.all()
        candidates = candidates.filter(
            report_type=opposite_type,
            status__in=[ItemReport.Status.ACTIVE, ItemReport.Status.POSSIBLE_MATCH],
            is_hidden=False,
            is_deleted=False,
        ).exclude(pk=report.pk)
        matches = [cls.compare(report, candidate) for candidate in candidates]
        matches = [match for match in matches if match.total_score >= cls.minimum_score]
        return sorted(matches, key=lambda match: match.total_score, reverse=True)[
            : cls.maximum_results
        ]
