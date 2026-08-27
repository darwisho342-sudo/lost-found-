from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext


class VisualThemeTests(TestCase):
    def test_public_layout_has_one_accessible_theme_toggle(self):
        for page_name in ("home", "item_list", "login"):
            with self.subTest(page=page_name):
                response = self.client.get(reverse(page_name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-theme-toggle", count=1)
                self.assertContains(response, 'aria-label="Switch to dark theme"')
                self.assertContains(response, 'data-label-light="Switch to light theme"')

    def test_management_layout_has_one_toggle_and_keeps_shared_scroll_shell(self):
        staff = User.objects.create_user(
            "theme_staff", password="StrongPass123!", is_staff=True, is_superuser=True
        )
        self.client.force_login(staff)
        response = self.client.get(reverse("management_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-theme-toggle", count=1)
        self.assertContains(response, 'class="admin-layout app-shell"')
        self.assertContains(response, 'class="admin-page main-content"')

    def test_theme_is_applied_before_styles_and_interactive_script_persists_it(self):
        response = self.client.get(reverse("home"))
        content = response.content.decode()
        initializer = content.index('const key = "findmatch-theme"')
        first_stylesheet = content.index('rel="stylesheet"')
        self.assertLess(initializer, first_stylesheet)
        self.assertIn("document.documentElement.dataset.theme = theme", content)
        self.assertIn("document.documentElement.dataset.bsTheme = theme", content)

        javascript = (Path(settings.BASE_DIR) / "static/js/findmatch.js").read_text(encoding="utf-8")
        for behavior in (
            'const storageKey = "findmatch-theme"',
            "localStorage.setItem(storageKey, selected)",
            'root.dataset.theme = selected',
            'root.dataset.bsTheme = selected',
            'setAttribute("aria-pressed"',
            'prefers-color-scheme: dark',
        ):
            self.assertIn(behavior, javascript)

    def test_semantic_tokens_define_both_requested_palettes(self):
        css = (Path(settings.BASE_DIR) / "static/css/core/variables.css").read_text(encoding="utf-8")
        self.assertIn('html[data-theme="dark"]', css)
        for token in (
            "--color-background", "--color-surface", "--color-surface-elevated",
            "--color-text", "--color-text-muted", "--color-border", "--color-primary",
            "--color-coral", "--color-cyan", "--color-warning", "--color-success",
            "--color-danger", "--shadow-sm", "--shadow-md", "--shadow-lg", "--focus-ring",
        ):
            self.assertGreaterEqual(css.count(token), 2, token)
        for color in ("#F4F7FC", "#5B5FF5", "#071225", "#0F1B31", "#6D70FF", "#25C3D0"):
            self.assertIn(color, css)

    def test_theme_labels_are_translated_and_arabic_remains_rtl(self):
        expectations = {
            "tr": "Koyu temaya geç",
            "ar": "التبديل إلى المظهر الداكن",
        }
        for language, expected in expectations.items():
            with self.subTest(language=language), translation.override(language):
                self.assertEqual(gettext("Switch to dark theme"), expected)
                response = self.client.get(reverse("home"))
                self.assertContains(response, expected)
                if language == "ar":
                    self.assertContains(response, '<html lang="ar" dir="rtl">')

    def test_motion_is_restrained_and_reduced_motion_is_supported(self):
        css_root = Path(settings.BASE_DIR) / "static/css"
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in css_root.rglob("*.css")
            if "vendor" not in path.parts
        )
        self.assertIn("prefers-reduced-motion: reduce", combined)
        self.assertIn("fm-fade-rise", combined)
        self.assertIn("fm-panel-in", combined)
        self.assertNotIn("transition: all", combined.lower())

    def test_header_groups_do_not_shrink_or_overlap(self):
        response = self.client.get(reverse("item_list"))
        self.assertContains(response, 'class="navbar-brand fm-brand"')
        self.assertContains(response, 'class="fm-primary-links"')
        self.assertContains(response, 'class="fm-header-utilities"')

        css = (Path(settings.BASE_DIR) / "static/css/components/navigation.css").read_text(
            encoding="utf-8"
        )
        for rule in (
            "grid-template-columns:max-content minmax(0,1fr) max-content",
            ".fm-primary-links > *,.fm-nav-actions > * { flex:0 0 auto; }",
            "@media (min-width:1400px)",
            "@media (max-width:1399.98px)",
            ".fm-primary-links,.desktop-scope-selector,.fm-nav-actions { display:none; }",
            "overflow-wrap:normal",
        ):
            self.assertIn(rule, css)

    def test_compact_header_keeps_notifications_inside_authenticated_drawer(self):
        user = User.objects.create_user("drawer_user", password="StrongPass123!")
        self.client.force_login(user)
        response = self.client.get(reverse("item_list"))
        self.assertContains(response, 'class="fm-header-utilities"')
        self.assertContains(response, reverse("notification_list"))
        self.assertContains(response, ">Notifications<")
        self.assertNotContains(response, 'class="mobile-notification-link"')

    def test_public_header_is_sticky_at_every_navigation_breakpoint(self):
        css = (Path(settings.BASE_DIR) / "static/css/components/navigation.css").read_text(
            encoding="utf-8"
        )
        sticky_rule = css.split(".fm-navbar {", 1)[1].split("}", 1)[0]
        for declaration in ("position:sticky", "top:0", "width:100%", "z-index:1030"):
            self.assertIn(declaration, sticky_rule)
        self.assertNotIn("position:relative", sticky_rule)
        self.assertIn(":target { scroll-margin-top:var(--fm-sticky-header-offset); }", css)

    def test_icon_buttons_use_non_overlapping_inline_flex_layout(self):
        button_css = (Path(settings.BASE_DIR) / "static/css/components/buttons.css").read_text(
            encoding="utf-8"
        )
        reports_css = (Path(settings.BASE_DIR) / "static/css/pages/reports-list.css").read_text(
            encoding="utf-8"
        )
        for rule in ("align-items:center", "display:inline-flex", "gap:.5rem", "white-space:nowrap"):
            self.assertIn(rule, button_css)
        self.assertIn(".btn > i,.btn > svg { flex:0 0 auto; position:static; }", button_css)
        self.assertIn(".search-submit i", reports_css)
