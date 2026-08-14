# FindMatch worldwide upgrade checklist

This checklist records implementation and verification status. It contains no schedule estimates.

## Foundation and compatibility

- [x] Inventory existing reports, claims, conversations, notifications, permissions, media, translations, tests, and documentation.
- [x] Preserve SQLite as the local default and preserve existing records through additive migrations.
- [x] Add environment-driven PostgreSQL configuration and deployment documentation.
- [x] Add a safe health-check endpoint and production security settings.

## Reports, locations, and matching

- [x] Add international public and private location fields with legacy campus compatibility.
- [x] Keep structured category, item-type, appearance, brand, date, and private verification choices centralized.
- [x] Extend lifecycle statuses, drafts, expiration, renewal, and privacy-safe public filtering.
- [x] Upgrade deterministic matching to international location and 70/85 thresholds.
- [x] Add duplicate-report detection and image hashing without image recognition.
- [ ] Add guided reporting sections, draft persistence, privacy preview, and no-JavaScript fallback. The single-page accessible fallback, draft action, progress outline, and privacy review are implemented; per-step server persistence and edit-section preview navigation remain.

## Claims, returns, and organizations

- [x] Keep private ownership questions, claimant answers, evidence, clarification, approval, rejection, dispute, and two-party confirmation.
- [x] Require verified email for claims and private messaging.
- [x] Add return methods, delivery consent, statuses, private addresses/tracking, and dispute retention.
- [ ] Add trusted organizations, staff roles, custody transfer, and collection confirmation. The permission-aware data model and Django Admin management exist; the full organization-facing custody UI remains.

## Alerts, privacy, and moderation

- [x] Add strong-match notifications and saved-search alerts with deduplication.
- [x] Add privacy/notification preferences, consent controls, data export, and deactivation requests.
- [ ] Add rate limits, content-report records, high-value warnings, and privacy-safe moderation indicators. Enforcement and data foundations exist; a complete end-user abuse-report UI and duplicate-merge appeal flow remain.
- [x] Add Privacy Policy and Terms pages with legal-review caveats.

## User experience and operations

- [x] English, Turkish, and Arabic infrastructure with Arabic RTL support.
- [ ] Translate all newly added interface content and verify responsive/accessibility-critical markup.
- [ ] Expand the personal dashboard and custom staff dashboard with privacy-safe data. The combined personal dashboard exists; organization/dispute analytics controls remain to be added to the staff UI.
- [ ] Add optional map/email configuration with complete manual/offline fallbacks. Manual fields, explicit browser geolocation, console email, verification, and environment switches work; provider autocomplete adapters remain external configuration work.
- [x] Add upload metadata removal and manual image preparation controls.

## Verification and documentation

- [x] Create and inspect migrations, then run migrate, check, migration drift check, and the complete test suite.
- [ ] Add tests for international locations, matching thresholds, privacy, return workflow, alerts, SQLite compatibility, and health checks. Core coverage exists; a live PostgreSQL integration run and browser accessibility automation remain external-environment checks.
- [x] Review templates, notifications, logs, and services for private-data exposure and abandoned AI code.
- [x] Update README, environment example, database transfer/backup guide, deployment checklist, demonstration instructions, and work log.
