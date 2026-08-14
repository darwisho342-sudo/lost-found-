import re
import unicodedata
from math import asin, cos, radians, sin, sqrt
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

    @staticmethod
    def approximate_distance_km(first, second):
        values = (first.public_latitude, first.public_longitude, second.public_latitude, second.public_longitude)
        if any(value is None for value in values):
            return None
        lat1, lon1, lat2, lon2 = map(radians, map(float, values))
        delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
        value = sin(delta_lat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
        return 6371 * 2 * asin(sqrt(value))

    @classmethod
    def location_points(cls, lost, found):
        points = sum(
            cls.exact_points(lost, found, field, maximum)
            for field, maximum in (
                ("country", 5), ("region", 2), ("city", 5), ("district", 2),
                ("place_type", 2), ("place_name", 2),
            )
        )
        distance = cls.approximate_distance_km(lost, found)
        if distance is not None:
            points += 2 if distance <= 2 else 1 if distance <= 10 else 0
        elif not lost.country and not found.country:
            # Compatibility for reports created before international locations.
            points += cls.exact_points(lost, found, "campus_location", 10, "custom_location")
        return min(points, 20)

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
        # Legacy rows remain matchable through their existing colour/description fields.
        lost_primary = lost.primary_colour or lost.colour
        found_primary = found.primary_colour or found.colour
        return MatchResult(
            lost_item=lost, found_item=found,
            category_points=cls.exact_points(lost, found, "category", 12, "custom_item_type"),
            item_type_points=cls.exact_points(lost, found, "item_type", 12, "custom_item_type"),
            title_points=cls.similarity_points(lost.title, found.title, 8),
            description_points=cls.similarity_points(lost.public_details, found.public_details, 8),
            primary_colour_points=8 if cls.normalize_text(lost_primary) and cls.normalize_text(lost_primary) == cls.normalize_text(found_primary) and cls.normalize_text(lost_primary) != "not sure" else 0,
            secondary_colour_points=cls.exact_points(lost, found, "secondary_colour", 4),
            brand_points=cls.exact_points(lost, found, "brand", 6, "custom_brand"),
            model_points=cls.similarity_points(lost.model, found.model, 4),
            material_points=cls.exact_points(lost, found, "material", 4),
            size_points=cls.exact_points(lost, found, "approximate_size", 4),
            location_points=cls.location_points(lost, found),
            date_points=cls.date_points(lost.item_date, found.item_date),
        )

    @classmethod
    def find_matches(cls, report, queryset: QuerySet | None = None):
        if report.status != ItemReport.Status.ACTIVE:
            return []
        opposite = ItemReport.ReportType.FOUND if report.report_type == ItemReport.ReportType.LOST else ItemReport.ReportType.LOST
        candidates = queryset if queryset is not None else ItemReport.objects.all()
        candidates = candidates.filter(report_type=opposite, status=ItemReport.Status.ACTIVE, is_hidden=False, is_deleted=False).exclude(pk=report.pk)
        results = (cls.compare(report, candidate) for candidate in candidates)
        return sorted((result for result in results if result.total_score >= cls.minimum_score), key=lambda result: result.total_score, reverse=True)[:cls.maximum_results]
