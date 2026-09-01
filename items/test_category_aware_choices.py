from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import translation

from .choices import appearance_fields_for
from .forms import AdminReportFilterForm, ItemReportForm
from .models import ItemReport
from .services import MatchingService


class CategoryAwareChoiceTests(TestCase):
    def form(self, category, item_type, **overrides):
        data = {
            "category": category,
            "item_type": item_type,
            "primary_colour": "black",
            "brand": "",
            "country": "TR",
            "city": "Istanbul",
            "item_date": date.today().isoformat(),
            **overrides,
        }
        return ItemReportForm(
            data=data,
            report_type=ItemReport.ReportType.LOST,
            scope=ItemReport.Scope.INTERNATIONAL,
        )

    def test_clothing_jacket_excludes_electronics_brands(self):
        form = self.form("clothing", "jacket", brand="nike")
        brands = dict(form.fields["brand"].choices)
        self.assertIn("nike", brands)
        self.assertIn("adidas", brands)
        self.assertNotIn("apple", brands)
        self.assertNotIn("samsung", brands)
        self.assertNotIn("lenovo", brands)
        self.assertNotIn("model", appearance_fields_for("clothing", "jacket"))

    def test_phone_and_computer_brand_sets_are_item_specific(self):
        phone_brands = dict(self.form("electronics", "mobile_phone").fields["brand"].choices)
        laptop_brands = dict(self.form("electronics", "laptop").fields["brand"].choices)
        self.assertIn("samsung", phone_brands)
        self.assertIn("huawei", phone_brands)
        self.assertNotIn("dell", phone_brands)
        self.assertIn("lenovo", laptop_brands)
        self.assertIn("dell", laptop_brands)
        self.assertIn("asus", laptop_brands)
        self.assertNotIn("samsung", laptop_brands)

    def test_brand_fallbacks_remain_available(self):
        brands = dict(self.form("clothing", "jacket").fields["brand"].choices)
        self.assertIn("", brands)
        self.assertIn("other", brands)
        self.assertIn("not_sure", brands)
        self.assertIn("no_visible_brand", brands)

    def test_edit_form_preserves_valid_category_brand(self):
        owner = User.objects.create_user("category_edit_owner", password="StrongPass123!")
        report = ItemReport.objects.create(
            owner=owner,
            scope=ItemReport.Scope.INTERNATIONAL,
            report_type=ItemReport.ReportType.LOST,
            title="Black jacket",
            description="",
            category="clothing",
            item_type="jacket",
            colour="black",
            primary_colour="black",
            brand="nike",
            country="TR",
            city="Istanbul",
            item_date=date.today(),
        )
        form = ItemReportForm(instance=report, report_type="lost", scope="international")
        self.assertEqual(form.initial["brand"], "nike")
        self.assertIn("nike", dict(form.fields["brand"].choices))
        self.assertNotIn("apple", dict(form.fields["brand"].choices))

    def test_bound_values_and_dynamic_maps_survive_validation_error(self):
        form = self.form("clothing", "jacket", brand="nike", city="")
        self.assertFalse(form.is_valid())
        self.assertIn("city", form.errors)
        self.assertEqual(form.data["brand"], "nike")
        self.assertIn("nike", dict(form.fields["brand"].choices))
        self.assertIn("data-choice-map", form.fields["item_type"].widget.attrs)
        self.assertIn("data-choice-map", form.fields["brand"].widget.attrs)
        self.assertIn("data-appearance-map", form.fields["category"].widget.attrs)

    def test_irrelevant_posted_brand_is_rejected(self):
        form = self.form("clothing", "jacket", brand="apple")
        self.assertFalse(form.is_valid())
        self.assertIn("brand", form.errors)

    def test_matching_still_scores_valid_structured_brand(self):
        common = {
            "scope": ItemReport.Scope.INTERNATIONAL,
            "title": "Black Nike jacket",
            "description": "Black winter jacket",
            "category": "clothing",
            "item_type": "jacket",
            "colour": "black",
            "primary_colour": "black",
            "brand": "nike",
            "country": "TR",
            "city": "Istanbul",
            "item_date": date.today(),
        }
        lost = ItemReport(report_type=ItemReport.ReportType.LOST, **common)
        found = ItemReport(report_type=ItemReport.ReportType.FOUND, **common)
        result = MatchingService.compare(lost, found)
        self.assertEqual(result.item_type_points, 15)
        self.assertEqual(result.brand_points, 10)


class ManagementFilterTranslationTests(TestCase):
    EXPECTED = {
        "en": {
            "item_type": "Item type", "primary_colour": "Primary colour",
            "brand": "Brand", "material": "Material", "country": "Country",
            "place_type": "Place type", "status": "Status",
            "date_from": "Date from", "date_to": "Date to",
            "sort": "Sort", "visibility": "Visibility",
        },
        "tr": {
            "item_type": "Eşya türü", "primary_colour": "Ana renk",
            "brand": "Marka", "material": "Malzeme", "country": "Ülke",
            "place_type": "Yer türü", "status": "Durum",
            "date_from": "Başlangıç tarihi", "date_to": "Bitiş tarihi",
            "sort": "Sıralama", "visibility": "Görünürlük",
        },
        "ar": {
            "item_type": "نوع الغرض", "primary_colour": "اللون الأساسي",
            "brand": "العلامة التجارية", "material": "المادة", "country": "الدولة",
            "place_type": "نوع المكان", "status": "الحالة",
            "date_from": "التاريخ من", "date_to": "التاريخ إلى",
            "sort": "الترتيب", "visibility": "الظهور",
        },
    }

    def test_management_filter_labels_translate(self):
        for language, expected in self.EXPECTED.items():
            with self.subTest(language=language), translation.override(language):
                form = AdminReportFilterForm()
                self.assertEqual(
                    {name: str(form.fields[name].label) for name in expected},
                    expected,
                )

    def test_management_report_page_uses_translated_labels_and_rtl(self):
        administrator = User.objects.create_superuser(
            "translated_management_admin",
            "translated-management@example.test",
            "StrongPass123!",
        )
        self.client.force_login(administrator)
        english = self.client.get("/en/management/reports/")
        turkish = self.client.get("/tr/management/reports/")
        arabic = self.client.get("/ar/management/reports/")
        self.assertContains(english, "Date from")
        self.assertContains(turkish, "Başlangıç tarihi")
        self.assertContains(turkish, "Görünürlük")
        self.assertContains(arabic, "التاريخ من")
        self.assertContains(arabic, "الظهور")
        self.assertContains(arabic, '<html lang="ar" dir="rtl">')

    def test_dynamic_choice_labels_translate(self):
        with translation.override("tr"):
            form = ItemReportForm(
                data={"category": "clothing", "item_type": "jacket"},
                report_type="lost", scope="international", draft_mode=True,
            )
            self.assertEqual(dict(form.fields["item_type"].choices)["jacket"], "Ceket")
            self.assertEqual(dict(form.fields["brand"].choices)["no_visible_brand"], "Görünür Bir Marka Yok")
            self.assertEqual(form.fields["brand"].choices[0][1], "Belirtilmemiş")
        with translation.override("ar"):
            form = ItemReportForm(
                data={"category": "clothing", "item_type": "jacket"},
                report_type="lost", scope="international", draft_mode=True,
            )
            self.assertEqual(dict(form.fields["item_type"].choices)["jacket"], "السترة")
            self.assertEqual(dict(form.fields["brand"].choices)["no_visible_brand"], "لا علامة تجارية مرئية")
            self.assertEqual(form.fields["brand"].choices[0][1], "غير محدد")
