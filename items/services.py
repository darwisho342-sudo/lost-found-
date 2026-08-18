import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from django.db.models import QuerySet

from .models import ItemReport


@dataclass(frozen=True)
class MatchResult:
    lost_item: ItemReport
    found_item: ItemReport
    category_points: int = 0
    item_type_points: int = 0
    title_points: int = 0
    description_points: int = 0
    primary_colour_points: int = 0
    secondary_colour_points: int = 0
    brand_points: int = 0
    model_points: int = 0
    material_points: int = 0
    size_points: int = 0
    location_points: int = 0
    date_points: int = 0

    @property
    def colour_points(self):  # Compatibility for existing templates/integrations.
        return self.primary_colour_points + self.secondary_colour_points

    @property
    def total_score(self):
        return min(100, sum((self.category_points, self.item_type_points, self.title_points,
            self.description_points, self.primary_colour_points, self.secondary_colour_points,
            self.brand_points, self.model_points, self.material_points, self.size_points,
            self.location_points, self.date_points)))

    @property
    def strength_label(self):
        return "strong" if self.total_score >= 85 else "possible"


class MatchingService:
    """Transparent matching of public structured report fields only."""

    minimum_score = 70
    strong_match_score = 85
    maximum_results = 5
    zero_values = {"", "not_sure"}
    synonyms = {"navy": "dark blue", "lacivert": "dark blue", "siyah": "black",
                "telefon": "mobile phone", "cep telefonu": "mobile phone", "phone": "mobile phone",
                "çanta": "bag", "canta": "bag", "حقيبة": "bag", "هاتف": "mobile phone"}

    @classmethod
    def normalize_text(cls, value):
        value = unicodedata.normalize("NFKC", str(value or "")).casefold()
        value = " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))
        return cls.synonyms.get(value, value)

    @classmethod
    def comparable_value(cls, report, field, custom_field=None):
        value = getattr(report, field, "") or ""
        if value in cls.zero_values:
            return ""
        if value == "other":
            value = getattr(report, custom_field, "") if custom_field else ""
        return cls.normalize_text(value)

    @classmethod
    def exact_points(cls, first, second, field, points, custom_field=None):
        a = cls.comparable_value(first, field, custom_field)
        b = cls.comparable_value(second, field, custom_field)
        return points if a and b and a == b else 0

    @classmethod
    def similarity_points(cls, first, second, maximum):
        a, b = cls.normalize_text(first), cls.normalize_text(second)
        if not a or not b:
            return 0
        ratio = SequenceMatcher(None, a, b).ratio()
        return round(maximum * ratio) if ratio >= .35 else 0

    @classmethod
    def location_points(cls, lost, found):
        if lost.scope == ItemReport.Scope.UNIVERSITY:
            if lost.university_location_id and found.university_location_id:
                first, second = lost.university_location, found.university_location
                if first.pk == second.pk:
                    return 10
                points = 4 if cls.normalize_text(first.campus) == cls.normalize_text(second.campus) else 0
                points += 3 if first.building and cls.normalize_text(first.building) == cls.normalize_text(second.building) else 0
                points += 3 if first.general_area and cls.normalize_text(first.general_area) == cls.normalize_text(second.general_area) else 0
                return points
            return cls.exact_points(lost, found, "campus_location", 10, "custom_location")
        if cls.normalize_text(lost.country) != cls.normalize_text(found.country):
            return 0
        return min(10, sum((
            cls.exact_points(lost, found, "city", 4),
            cls.exact_points(lost, found, "district", 2),
            cls.exact_points(lost, found, "place_type", 2),
            cls.similarity_points(lost.place_name, found.place_name, 2),
        )))

    @staticmethod
    def date_points(lost_date, found_date):
        difference = (found_date - lost_date).days
        if difference < -1:
            return 0
        distance = abs(difference)
        if distance == 0: return 10
        if distance <= 2: return 8
        if distance <= 7: return 5
        if distance <= 14: return 2
        return 0

    @classmethod
    def compare(cls, first, second):
        if first.report_type == second.report_type:
            raise ValueError("Matching requires one lost report and one found report.")
        lost = first if first.report_type == ItemReport.ReportType.LOST else second
        found = second if lost is first else first
        if lost.scope != found.scope:
            raise ValueError("Matching requires reports in the same scope.")
        if (lost.scope == ItemReport.Scope.INTERNATIONAL
                and cls.normalize_text(lost.country) != cls.normalize_text(found.country)):
            raise ValueError("International matching requires the same country.")
        # Legacy rows remain matchable through their existing colour/description fields.
        lost_primary = lost.primary_colour or lost.colour
        found_primary = found.primary_colour or found.colour
        return MatchResult(
            lost_item=lost, found_item=found,
            category_points=cls.exact_points(lost, found, "category", 15),
            item_type_points=cls.exact_points(lost, found, "item_type", 15, "custom_item_type"),
            title_points=cls.similarity_points(lost.title, found.title, 5),
            description_points=cls.similarity_points(lost.public_details, found.public_details, 15),
            primary_colour_points=10 if cls.normalize_text(lost_primary) and cls.normalize_text(lost_primary) == cls.normalize_text(found_primary) and cls.normalize_text(lost_primary) != "not sure" else 0,
            secondary_colour_points=cls.exact_points(lost, found, "secondary_colour", 5),
            brand_points=cls.exact_points(lost, found, "brand", 10, "custom_brand"),
            model_points=cls.similarity_points(lost.model, found.model, 5),
            material_points=0,
            size_points=0,
            location_points=cls.location_points(lost, found),
            date_points=cls.date_points(lost.item_date, found.item_date),
        )

    @classmethod
    def find_matches(cls, report, queryset: QuerySet | None = None):
        if report.status != ItemReport.Status.ACTIVE:
            return []
        opposite = ItemReport.ReportType.FOUND if report.report_type == ItemReport.ReportType.LOST else ItemReport.ReportType.LOST
        candidates = queryset if queryset is not None else ItemReport.objects.all()
        candidates = candidates.filter(
            report_type=opposite, scope=report.scope, status=ItemReport.Status.ACTIVE,
            is_hidden=False, is_deleted=False,
        ).exclude(pk=report.pk)
        if report.scope == ItemReport.Scope.INTERNATIONAL:
            candidates = candidates.filter(country__iexact=report.country)
        results = (cls.compare(report, candidate) for candidate in candidates)
        return sorted((result for result in results if result.total_score >= cls.minimum_score), key=lambda result: result.total_score, reverse=True)[:cls.maximum_results]
