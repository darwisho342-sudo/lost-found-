# Free Local University and International MVP implementation checklist

This checklist records implemented repository work against the final two-mode specification. It does not claim completion for future external integrations.

## Scope and preservation

- [x] Keep SQLite, Django templates, local Bootstrap assets, Pillow, console email, and local media.
- [x] Preserve the existing database and applied migrations; add forward-only migrations 0019 through 0023.
- [x] Reuse existing report, claim, conversation, message, notification, moderation, return, and audit models.
- [x] Keep both University and International modes in one local application without external services.
- [x] Document external AI, SSO, courier integrations, payments, maps, production databases, and hosting as future work only.

## University access

- [x] Environment-driven University name, exact allowed email domains, campuses, office, session age, and retention period.
- [x] Administrator-managed University campus/building/general-area choices with legacy report compatibility.
- [x] Accept personal email registration; independently record ordinary email verification and exact-domain University eligibility.
- [x] Central server-side scope access service and verified-user enforcement on reports, matches, claims, conversations, dashboards, and notifications.
- [x] Preserve account records when eligibility is lost; inactive accounts remain blocked.

## Reports and matching

- [x] Central structured categories/item types and backend pair validation.
- [x] Required primary colour, optional appearance fields, campus area, future-date rejection, safe text validation, title suggestions, and duplicate warnings.
- [x] Conditional managed-campus University locations and manual country/city International locations, with private exact location excluded from public pages.
- [x] Up to three locally processed images when safe, with sensitive-document image restrictions.
- [x] Pillow image validation/re-encoding and 5 MB limit.
- [x] Move sensitive-document images to private storage and require official handover.
- [x] Exact deterministic 100-point formula, same-scope/country gating, 70 threshold, 85 strong threshold, top-five result limit, breakdown, dismissal, and deduplicated notices.

## Claims, messaging, moderation, and custody

- [x] Private questions/answers/evidence, no self-claims, duplicate pending-claim constraint, dispute states, and object permissions.
- [x] Finder-to-owner contact, protected conversations, unread indicators, masked contact consent, soft-deleted messages, and read-only completion.
- [x] Local in-app notifications and privacy-safe audit events.
- [x] Custom staff dashboard for reports, users, conversations, audit events, and custody inventory.
- [x] University custody intake, private storage reference, retention warning, high-value flags, append-only movement history, missing-item incidents, controlled disposition, and official release.
- [x] International participant-confirmed return with descriptive safe meeting, authority, or private-shipping methods and no courier/payment integration.
- [x] One appeal per rejected claim, content reporting, staff moderation queues, and recent-auth checks for sensitive administration.
- [x] Reversible report hiding/soft deletion and confirmed bulk actions.

## Interface, data, and verification

- [x] English, Turkish, and Arabic interface with RTL support.
- [x] Mobile-first navigation, responsive forms/cards/tables, keyboard focus, skip link, and reduced-motion rules.
- [x] Idempotent demo command with University and personal-email International accounts, reports, strong matches, claims, conversation, notification, and University custody record.
- [x] Local installation, verification, workflow, privacy, matching, custody, limitations, and future-work documentation.
- [ ] University SSO, external AI, real email/SMS, maps, courier booking/tracking, payments, PostgreSQL, cloud storage, and public hosting (intentionally postponed).
