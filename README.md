# FindMatch

FindMatch is an international lost-and-found platform built with Django, Bootstrap 5, SQLite or PostgreSQL, and Pillow. Visitors browse privacy-safe public reports; verified registered users manage reports, claims, conversations, saved alerts, and return arrangements. Staff members have a custom operational dashboard as well as Django's technical administration site.

The interface uses a responsive Campus Portal design: a navy navigation bar, turquoise accents, three-column item cards, homepage statistics, side-by-side match comparisons and a dark staff-dashboard sidebar. All visual assets are stored locally.

The application is designed to run locally on Windows. It does not use external APIs, paid services, machine-learning libraries or cloud hosting. Bootstrap is stored inside the project, so the interface does not require an internet connection after installation.

## Requirements

- Windows 10 or 11
- Python 3.12 or newer (Python 3.13 was used during development)
- A terminal such as PowerShell

## Windows setup

Open PowerShell in the project folder, then run:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_data
python manage.py test
python manage.py runserver
```

If PowerShell blocks virtual-environment activation, run this once in the current terminal and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

Open [http://127.0.0.1:8000/en/](http://127.0.0.1:8000/en/) in a browser. Turkish uses `/tr/` and Arabic uses `/ar/`. The administrator panel remains at [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/).

Staff members can open the custom dashboard at [http://127.0.0.1:8000/en/management/](http://127.0.0.1:8000/en/management/). It contains report totals, recent activity, report moderation and user management. Regular users receive a permission-denied page if they try to access it.

After logging in, staff accounts are sent directly to the custom dashboard. Regular accounts are sent to the normal homepage.

Registered users can open [http://127.0.0.1:8000/my-matches/](http://127.0.0.1:8000/my-matches/) to review possible matches across all their active reports.

The interface uses a responsive premium campus-portal design: a navy-to-purple homepage hero, real report previews, explainable match comparisons, grouped report forms, personal-report summaries and a separate dark staff dashboard. Poppins, Bootstrap and Bootstrap Icons are stored locally, so the visual design does not depend on a runtime CDN.

Stop the server with `Ctrl+C`.

## Application URLs

All user-facing routes begin with `/en/`, `/tr/`, or `/ar/`; the table below shows the part after the language prefix. Django admin, static/media files, and `/i18n/` are intentionally unprefixed.

| Page | URL |
|---|---|
| Home | `/` |
| Browse all reports | `/items/` |
| Lost items | `/items/lost/` |
| Found items | `/items/found/` |
| Item details | `/items/<id>/` |
| Report lost item | `/items/create/lost/` |
| Report found item | `/items/create/found/` |
| Edit or delete item | `/items/<id>/edit/`, `/items/<id>/delete/` |
| Resolve or close item | `/items/<id>/resolve/`, `/items/<id>/close/` |
| Possible matches | `/items/<id>/matches/` |
| My Reports | `/my-reports/` |
| My possible matches | `/my-matches/` |
| Profile and contact consent | `/accounts/profile/`, `/accounts/profile/edit/` |
| Conversation initiation history | `/contact-requests/sent/`, `/contact-requests/received/` |
| Initiation details and old-Pending start | `/contact-requests/<id>/`, `/contact-requests/<id>/start/` |
| Secure conversations | `/conversations/`, `/conversations/<id>/` |
| Complete a return | `/conversations/<id>/complete/` |
| Notifications | `/notifications/` |
| Register, login and logout | `/accounts/register/`, `/accounts/login/`, `/accounts/logout/` |
| Custom staff administration | `/management/` |
| Staff reports and users | `/management/reports/`, `/management/users/` |
| Staff conversations and audit | `/management/conversations/`, `/management/audit/` |
| Django administration | `/admin/` |
| Demonstration error pages | `/403/`, `/404/` |

## Internationalization

FindMatch supports English (source and fallback), Turkish, and Arabic through Django's built-in translation system. The URL prefix has first priority; Django then considers its saved language preference, the browser's `Accept-Language` header, and finally English. The shared language switcher retains the current path, report identifier, filters, pagination, and query string. Arabic pages use `dir="rtl"`; user-written content uses `dir="auto"`, while phone numbers and email addresses remain left-to-right.

Wrap Python UI text with `gettext()` or `gettext_lazy()` and template text with `{% translate %}` or `{% blocktranslate %}`. To update catalogs on Windows, install **GNU gettext 0.19 or newer** and make sure `msguniq.exe`, `xgettext.exe`, and `msgfmt.exe` are on `PATH`, then run:

```powershell
.venv\Scripts\python.exe manage.py makemessages -l tr -l ar
.venv\Scripts\python.exe manage.py compilemessages
.venv\Scripts\python.exe manage.py test
```

This checkout includes `tools/compile_locales.py` only as a dependency-free development fallback for the existing simple PO catalogs. GNU gettext plus Django's `compilemessages` remains the supported catalog workflow. To add another language, append it to `LANGUAGES`, generate its catalog, translate every `msgstr`, compile it, and add RTL checks when applicable. RTL CSS belongs in `static/css/core/rtl.css`; prefer logical properties such as `margin-inline-start` and never mirror photographs, phone numbers, or fixed-direction charts.

Deployment order is: install dependencies, update and compile catalogs, run migrations when needed, run `collectstatic`, and restart Django. `collectstatic` does not compile translations. Commit both PO and MO files and keep caches separated by language-prefixed URL.

Earlier `/reports/`, `/login/` and `/dashboard/` links redirect to or remain compatible with the canonical routes where appropriate.

## Demonstration accounts

Running `python manage.py seed_data` creates these fictional local accounts:

| Role | Username | Password |
|---|---|---|
| Student | `demo_student` | `FindMatchDemo123!` |
| Student | `demo_helper` | `FindMatchDemo123!` |
| Administrator | `campus_admin` | `AdminDemo123!` |

These credentials are only for a local demonstration. Change them before sharing a copy of the database.

## Main project structure

```text
config/                     Django settings and project URLs
items/                      Main application
  management/commands/     Repeatable sample-data command
  migrations/              Database schema history
  admin.py                  Administrator configuration
  forms.py                  Registration, report and filter validation
  models.py                 ItemReport database model
  services.py               Smart matching algorithm
  conversation_service.py  Transactional private-conversation initiation
  tests.py                  Public, account, matching and dashboard tests
  urls.py                   Application routes
  views.py                  Page and permission logic
templates/                  Shared, item and authentication templates
static/                     FindMatch styles and local Bootstrap files
docs/work_log.md            Implementation record
media/                      Local user uploads (created when needed)
```

## Deterministic Smart Matching

`MatchingService` compares a lost report only with found reports, or a found report only with lost reports. It calculates suggestions when requested and does not permanently store them.

- Same category: 15 points
- Same item type: 15 points
- Similar title: up to 10 points
- Similar public additional details: up to 15 points
- Same primary and secondary colours: 10 and 5 points
- Same normalized brand and similar model: 10 and 5 points
- International public/approximate location: 20 points
- Date proximity: up to 10 points

The current balanced 100-point formula is: category 12, item type 12, title 8, public details 8, primary colour 8, secondary colour 4, brand 6, model 4, material 4, approximate size 4, international public/approximate location 20, and date 10. Only opposite-type Active reports scoring at least 70 are shown. Scores from 70–84 are Possible matches; scores from 85–100 are Strong possible matches and may create a deduplicated notification. At most five results are displayed. Exact locations, claims, evidence, addresses, tracking, contacts, usernames, and messages are never compared. A score is not proof of ownership and never approves a claim.

## Secure contact and messaging

- A user can privately claim a found item or report that they found a lost item without creating another report.
- A registered non-owner can start a private conversation directly from a visible, non-closed report. Creation and the initial message are committed in one database transaction.
- Existing conversations are reused for the same report and participant pair; owner blocks prevent new conversations.
- Only the two participants and authorized staff can open a conversation. Messages appear immediately in oldest-to-newest order and are never classified or held for approval.
- Existing Pending `ContactRequest` rows are not auto-converted by migration. Either participant may open that historical record and start its conversation explicitly; new records are saved as non-blocking initiation history.
- Phone numbers remain private unless the conversation is Active and the phone-number owner has explicitly enabled consent.
- Phone masking is enabled by default and exposes only the final four digits. Users may opt to share the full number, while administrators require `items.view_unmasked_phone_numbers` to override masking.
- Revoking consent hides the number immediately.
- Messages use ordinary Django forms and page refreshes. Deleted messages are retained as soft-deleted records without their original displayed body.
- The staff-only audit log records safe event descriptions and never stores message bodies or phone numbers.

## Report moderation, deal completion and notifications

- The custom staff report page supports selecting one or all reports and applying reviewed, active, resolved, closed, hidden or deleted states. Sensitive bulk actions require a separate confirmation screen.
- Report deletion is a soft delete: public browsing, item details and match generation exclude the report, while its database row and linked audit history remain available to staff.
- A return can be completed only by the receiving participant. Staff can also complete a return from the management area.
- Completion is atomic and repeat-safe: the conversation becomes read-only, the report becomes resolved, competing pending contact requests close, and both participants receive a notification.
- Staff can deactivate a conversation only after entering a reason; both participants are notified and the thread becomes read-only with phone access disabled. Staff may reactivate deactivated or completed conversations, with an option to return the report to Active.
- The notification bell polls a small authenticated JSON endpoint every 15 seconds while the page is visible. Notifications never include private messages, phone numbers or verification details.
- The implementation uses Django templates, forms, messages and database transactions only—there is no REST framework, React, Celery or WebSocket dependency.

## Structured reports and secure ownership verification

Reports use stable choice values from `items/choices.py` for category, category-dependent item type, colours, appearance, brand, international place type, and return method. Country and city are required for new reports; region, district, place name, approximate map location, and private exact location are supported. Existing campus records remain valid through legacy fields. JavaScript improves conditional fields, title suggestions, explicit geolocation, and manual image preparation, while Django forms and models enforce important rules on the server.

Found-report owners can save up to three private verification questions. Expected answers are stored separately and never rendered on public report, browse, search, notification, or match pages. A signed-in claimant submits private answers, approximate loss details, a truthfulness confirmation, and optional private evidence. The finder may request one clarification, approve, reject, or report the claim as suspicious. Approval creates the private conversation and never reveals contact details automatically.

After claim approval, participants can record a safe public meeting, official return point, security/police handover, pickup, courier/postal delivery, or custom private arrangement. Delivery addresses require explicit owner consent and are excluded from search, matching, analytics, notifications, and audit descriptions. Both participants must confirm handover/receipt before completion resolves the report, closes the conversation, and closes competing pending claims.

FindMatch has no AI assistant, image-recognition provider, generated form content, OpenAI integration, or Ollama integration. Smart Matching is a local rule-based comparison implemented with explicit field weights and Python's `SequenceMatcher`. Sensitive-information checks are deterministic Django validation rules. The application requires no AI provider, API key, background worker, or network request.

## Useful commands

```powershell
python manage.py check
python manage.py makemigrations --check
python manage.py migrate
python manage.py test
python manage.py seed_data
python manage.py runserver
```

The seed command is repeatable and does not create duplicate demonstration reports when run more than once.

## Privacy and upload notes

- Public pages never display account email addresses.
- Users can edit or change the status of only their own reports; staff users may manage all reports.
- Report removal always uses a confirmation page and preserves a staff-visible audit copy. Staff may also hide reports without deleting them.
- Hidden reports remain available to their owner and staff but are excluded from public browsing and matching.
- Images must be readable image files no larger than 5 MB.
- Uploaded media and SQLite are suitable for this local demonstration, not a production deployment.
- Users should not put contact details, student IDs or other private information in report descriptions.

## Worldwide configuration

Copy `.env.example` values into environment variables appropriate to the host. FindMatch does not load `.env` files itself in production, avoiding a hidden configuration dependency. SQLite remains the default. Set `DB_ENGINE=postgresql` plus `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, and `DB_SSLMODE` only after PostgreSQL is ready. The `psycopg` driver is included; no Directus or REST layer is used.

Email defaults to Django's console backend, so registration, reporting, browsing, and matching remain functional without an email provider. Claims and private messaging require a verified email; configure SMTP variables for real delivery. Maps are disabled by default. Manual country/city/place fields are complete, and browser geolocation is requested only after the user presses **Use my current location**. A future restricted public browser key may be provided through `MAP_PUBLIC_BROWSER_KEY`; never put a secret provider key in templates or JavaScript.

The unlocalized `/health/` endpoint checks database connectivity and returns only `{"status":"ok"}` or a generic unavailable response. Production mode reads hosts and security controls from environment variables, enables secure cookies, HTTPS redirect, HSTS, MIME sniffing protection, and clickjacking protection. Set `SECURE_HSTS_PRELOAD=1` only after every current and future subdomain is permanently HTTPS-ready; browser preload can be difficult to reverse.

## Location and privacy boundaries

Public report data may include country, region, city, district, place type, place name, a safe general description, and coordinates rounded according to the user's selected precision. Exact location and full-precision coordinates are private. They are never included in public templates, search filters, match explanations, notifications, normal analytics, or audit descriptions.

Private claim evidence and message attachments use private storage and permission-checked download views. Delivery addresses, courier details, and tracking references are participant-only. Delivery consent may be withdrawn before shipment; private delivery details have a configurable operational retention deadline and can be purged with `python manage.py process_retention` unless an authorized dispute/safety hold applies.

## PostgreSQL transfer, backup, and restore

See `docs/database_operations.md` for the tested provider-neutral procedure. In summary: back up SQLite and media, export Django data with natural dependencies, create an empty PostgreSQL database/user, configure environment variables, run migrations, load data transactionally, verify row counts and relationships, then switch traffic. Preserve `media/` and `private_media/` separately; database dumps do not contain uploaded file bytes.

## Return, organization, and alert workflows

Approved claims gain a private return record with safe meeting, verified organization, security/police, pickup, courier/post, or custom methods. Return status changes generate privacy-safe deduplicated notifications. The finder confirms handover/shipment and the claimant confirms receipt; only both confirmations complete the claim, resolve the report, close competing claims, and make the conversation read-only.

Staff approve trusted organizations before they can be selected. Organization membership and privacy-safe custody events are represented separately. Saved searches store only allow-listed public filters and notify once per new matching Found report. FindMatch never transports an item, purchases shipping, guarantees delivery, or makes a legal determination of ownership.

## Retention and legal review

Active reports receive an expiration window and owners receive a privacy-safe warning before expiry. Expired reports leave public search and matching but are not automatically erased. Owners can renew eligible reports. Delivery data defaults to a limited retention window; evidence, conversations, audit records, public photographs, and legal/safety holds require an operator-approved retention policy before public deployment.

The included Privacy Policy and Terms are project notices, not professional legal advice. Obtain qualified privacy, security, consumer, courier, accessibility, and jurisdiction-specific legal review before a worldwide public launch. The project does not claim automatic GDPR, Turkish-law, or worldwide compliance.
