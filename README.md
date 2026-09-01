# FindMatch

FindMatch is a free local Django Lost and Found MVP with two modes in one application:

- **University Mode** for verified accounts from administrator-approved exact email domains.
- **International Mode** for any verified email account, using manual country/city fields.

It uses Django templates, local Bootstrap 5 assets, SQLite, Pillow, local media/private media, console email, in-app notifications, and deterministic Python matching. It needs no hosting, maps, geocoding, AI, SSO, SMS, courier, payment, commission, Redis, Celery, PostgreSQL, or other online service.

## Install and run locally

On Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py check
python manage.py test
python manage.py runserver 8000
```

Open [http://127.0.0.1:8000/en/](http://127.0.0.1:8000/en/). Turkish is `/tr/` and Arabic is `/ar/`. Stop with `Ctrl+C`. In VS Code, select **Run FindMatch** and press F5; stop with Shift+F5 or the red stop button.

SQLite data is in `db.sqlite3`, public uploads in `media/`, and protected files in `private_media/`. Back up all three before maintenance.

## Local environment

The project uses its existing direct environment-variable approach. `.env.example` is documentation; it is not loaded by a second package.

```text
DJANGO_SECRET_KEY=replace-with-a-long-random-value
DJANGO_DEBUG=1
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
SITE_URL=http://127.0.0.1:8000
SQLITE_PATH=db.sqlite3
UNIVERSITY_NAME=Demo University
UNIVERSITY_EMAIL_DOMAINS=st.biruni.edu.tr
OPEN_UNIVERSITY_ACCESS=True
UNIVERSITY_CAMPUSES=Main Campus
UNIVERSITY_SECURITY_OFFICE=University Lost and Found Office
INTERNATIONAL_MODE_ENABLED=True
SESSION_COOKIE_AGE=259200
ITEM_RETENTION_DAYS=90
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

`OPEN_UNIVERSITY_ACCESS=True` temporarily allows every authenticated local user
to use both modes. Set it to `False` to restore verified University-domain access
for University Mode; staff and superuser authorization remains role-based in
either configuration.

Do not put a real secret in `.env.example`.

## Accounts, verification, and modes

Registration accepts University and personal email addresses. It sends a signed, expiring verification link through Django's console email backend; during a local demo, the link appears in the server terminal. The temporary mode-access bypass is controlled only by `OPEN_UNIVERSITY_ACCESS` and does not mark personal email addresses as University-verified.

Email verification and University eligibility are stored separately:

- An exact approved University domain grants both modes after verification.
- A verified personal email grants International Mode only.
- Provider names such as Gmail/Outlook never grant University access unless explicitly configured as an exact approved domain.
- Unverified or suspended accounts cannot report, claim, message, or use private workflows.
- Private object URLs recheck participant/owner/staff and report-scope access server-side.

The visible mode selector remembers the latest valid selection in the session/profile. University and International records still use one report, claim, conversation, notification, and database system. Sensitive profile, claim-review, custody-release, and administrator actions require recent password authentication. Sessions last three days by default and long pages receive a pre-expiry warning.

## Roles

- **Visitor:** landing/legal pages and privacy-safe public report details.
- **Verified personal-email user:** International reports, matches, claims, private conversations, notifications, and two-participant return confirmation.
- **Verified University user:** both modes plus University-private workflows.
- **Security/Lost and Found staff:** University intake, private storage, claim review for officially held items, movements, incidents, and handover when the existing `items.manage_custody` permission is assigned.
- **Administrator:** users, both report scopes, claims/appeals, moderation, conversations, locations, custody, audit events, and safe statistics.

The custom staff dashboard is `/en/management/`; Django's technical admin is `/admin/`.

## Demo accounts and data

`python manage.py seed_data` is idempotent and creates only fictional development data:

| Role | Username | Email | Password |
|---|---|---|---|
| University student A | `demo_student` | `demo.student@st.biruni.edu.tr` | `FindMatchDemo123!` |
| University student B | `demo_helper` | `demo.helper@st.biruni.edu.tr` | `FindMatchDemo123!` |
| Security staff | `security_staff` | `security@st.biruni.edu.tr` | `SecurityDemo123!` |
| Administrator | `campus_admin` | `admin@st.biruni.edu.tr` | `AdminDemo123!` |
| Personal user A | `international_owner` | `owner.personal@example.com` | `FindMatchDemo123!` |
| Personal user B | `international_finder` | `finder.personal@example.com` | `FindMatchDemo123!` |

The command creates campus locations, ten varied University reports, an active University match, two active International phone reports, a private pending University claim, a custody record, a separate completed International return, and safe in-app notifications. The current deterministic seed scores are **92%** for the University headphones pair and **98%** for the International phone pair. It never runs automatically.

To reset only documented demo workflow records while retaining the six demo accounts:

```powershell
python manage.py seed_data --reset-demo
```

This option targets only reports owned by the documented demo usernames and their related workflow records. It does not delete other users or the database.

## Structured reports and images

Both modes share stable category-dependent item types, colours, material, size, pattern, condition, brand/model, date validation, an editable generated title, sensitive-text checks, duplicate warnings, drafts, and privacy review.

- University reports use administrator-managed campus/building/general areas.
- International reports require a bundled stable country code and City; region, district, place type/name, safe public location, and exact private location are conditional.
- Exact location is never public, searchable, matched, notified, or included in analytics/audit descriptions.
- One primary image plus two optional additional images is supported.
- Pillow verifies real JPG/PNG/WebP content, enforces 5 MB, bounds dimensions, resizes, re-encodes, and strips ordinary metadata.
- Sensitive document images are moved to protected storage or replaced publicly by a safe placeholder. Additional public images are rejected for sensitive-document types.
- Users can report content/messages; staff can hide reports/messages and immediately hide all report images.

## Explainable Smart Matching

Matching is deterministic—not AI—and compares only Active Lost with Active Found reports in the same mode. University reports use the configured University/campus location. International reports require the same country and score compatible city/district/place fields; no physical distance is claimed.

| Component | Points |
|---|---:|
| Category | 15 |
| Item type | 15 |
| Public description similarity | 15 |
| Primary colour | 10 |
| Secondary colour | 5 |
| Brand | 10 |
| Model similarity | 5 |
| Compatible scope location | 10 |
| Date compatibility | 10 |
| Title similarity | 5 |

Blank/`Not Sure` values score zero. Private questions/answers, evidence, exact locations/times, contacts, usernames, messages, and storage records are excluded. Only the top five scores of at least 70 are displayed; 85+ creates one deduplicated Strong Possible Match notification. Users can dismiss suggestions. A score is never ownership proof and never auto-approves a claim.

## Claims, conversations, returns, and custody

Found-item owners can configure up to three private questions. Claims enforce verified scope access, no self-claims, one active claim per user/report, truthful confirmation, attempt/rate limits, protected evidence, and expected-answer secrecy. Review supports more information, approval, rejection, cancellation, dispute, completion, and one administrator-reviewed appeal. Lost reports support **I Found This Item** without requiring another report.

Approved claims open protected conversations with read state, safe private attachments, message reporting, masked/consent-controlled phones, administrator deactivation, and read-only completion.

- **University:** staff records intake/private storage, append-only movements, reconciliation, locked/high-value controls, optional two-staff release, incidents, official handover, and retention/disposition decisions. A missing item cannot be normally released. Participant confirmation alone cannot mark it Returned.
- **International:** the finder normally retains custody. Participants choose a descriptive safe meeting/local authority/privately arranged shipping method; FindMatch books nothing, calculates no fees, stores no tracking integration, and processes no payment. Both participants normally confirm return before completion.

Unclaimed items are never automatically awarded, donated, deleted, or disposed. An administrator records the University's actual authorized decision. Final policy requires University/legal approval.

## Security, accessibility, and languages

Safeguards include Django password hashing, CSRF, POST-only state changes, server-side scope/object permissions, safe sessions, file validation, rate limits, database constraints, transactions for important workflows, escaped output, soft hiding/deletion, and privacy-safe audit/notification text. These safeguards are not a claim that the MVP is impossible to attack or legally certified.

English, Turkish, and Arabic are local; Arabic uses RTL and user text uses `dir="auto"`. The interface has a skip link, labels/errors, keyboard focus, responsive navigation/drawer/bottom navigation, reduced-motion support, constrained images, mobile forms/cards, and safe table scrolling.

## Test and maintenance commands

```powershell
python manage.py makemigrations
python manage.py migrate
python manage.py check
python manage.py test
python manage.py makemigrations --check
python tools\compile_locales.py
python manage.py process_retention --dry-run
```

## Local demonstration

### Local email verification

Normal registration and email-link verification remain the application workflow. With the local console email backend, verification links are printed in the development server terminal.

For an offline classroom demonstration, a **superuser only** may also open `/admin/items/userprofile/`, select one or more fictional demo profiles, and choose **Mark selected email addresses as verified**. The inverse action restores the normal unverified restrictions. Both actions update the existing `UserProfile.email_verified_at` timestamp; they do not introduce a second source of truth, automatically verify new registrations, or grant staff/custody permissions.

Do not use manual administrator verification as a production identity check. Before deployment, remove or explicitly disable this local operational shortcut and configure a real email provider, verified sending domain, expiry/rate-limit monitoring, and an auditable support process.

Prepared University workflow:

1. Sign in as `demo_student`, choose University Mode, and open **Black wireless headphones**.
2. Open its match suggestions to show the **92%** breakdown against **Black headphones in case**.
3. Show the deduplicated Strong Possible Match notification.
4. Open the prepared pending claim as `demo_student`, then review it as `demo_helper`; no conversation exists before approval and private answers never appear on public pages.
5. Sign in as `security_staff` and open Management → Custody to show the permission-protected fictional intake record.

Prepared International workflow:

1. Sign in as `international_owner`, select International Mode, and open the Lost **Black Samsung phone**.
2. Show its **98%** breakdown against the corresponding Found phone and its safe notification.
3. Open **Returned red carry-on suitcase** to show a separate completed claim, completed conversation, two confirmations, read-only return record, and final Returned/Resolved status.
4. Switch the same normal personal account between International and University Mode while `OPEN_UNIVERSITY_ACCESS=True`; confirm that this does not expose staff or administrator pages.

The complete rehearsal, screenshot checklist, roles, expected states, and recovery steps are in [`docs/demo_guide.md`](docs/demo_guide.md).

## Current limitations and future extensions

This is a localhost demonstration, so International Mode is not publicly worldwide until future deployment. Real University SSO/directory/deactivation, external AI or embeddings, real email/SMS, online maps/geocoding, courier booking/tracking, delivery payments/commission, PostgreSQL production setup, cloud storage, legal-policy approval, and public hosting remain documented future work only. None is simulated or required.

See `docs/work_log.md` and `docs/local_university_mvp_checklist.md` for implementation history and the audit checklist.
