# FindMatch

FindMatch is a beginner-friendly university lost-and-found demonstration built with Django, Bootstrap 5, SQLite and Pillow. Visitors can browse and filter reports. Registered users can submit and manage their own reports and review transparent possible-match scores. Staff members have a custom administrator dashboard as well as Django's built-in administration site.

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

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in a browser. The administrator panel is at [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/).

Staff members can open the custom dashboard at [http://127.0.0.1:8000/management/](http://127.0.0.1:8000/management/). It contains report totals, recent activity, report moderation and user management. Regular users receive a permission-denied page if they try to access it.

After logging in, staff accounts are sent directly to the custom dashboard. Regular accounts are sent to the normal homepage.

Registered users can open [http://127.0.0.1:8000/my-matches/](http://127.0.0.1:8000/my-matches/) to review possible matches across all their active reports.

The interface uses a responsive premium campus-portal design: a navy-to-purple homepage hero, real report previews, explainable match comparisons, grouped report forms, personal-report summaries and a separate dark staff dashboard. Poppins, Bootstrap and Bootstrap Icons are stored locally, so the visual design does not depend on a runtime CDN.

Stop the server with `Ctrl+C`.

## Application URLs

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
| Staff AI Assistant | `/management/ai-assistant/` |
| Restricted AI Assistant settings | `/management/ai-assistant/settings/` |
| Django administration | `/admin/` |
| Demonstration error pages | `/403/`, `/404/` |

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

## Smart matching algorithm

`MatchingService` compares a lost report only with found reports, or a found report only with lost reports. It calculates suggestions when requested and does not permanently store them.

- Same category: 25 points
- Description similarity with Python `SequenceMatcher`: up to 25 points
- Same normalized colour: 20 points
- Same location: 15 points
- Date proximity: up to 15 points

The possible-matches page displays the five strongest results scoring at least 50%. It shows every component so users can understand the suggestion. A score is not proof that two reports describe the same item.

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

## Configurable administrator AI Assistant

- The custom dashboard includes a staff-only advisory assistant for report summaries, authorized conversation summaries, structured-data suggestions, reviewed content drafts, user-support hints, moderation-risk checks, deterministic matching explanations and aggregate analytics.
- The master switch defaults to disabled. When enabled, at least one globally available capability must be selected.
- Superusers and staff granted `items.manage_ai_assistant` may change global settings. Other staff may use enabled capabilities and disable individual capabilities for their own account.
- The initial provider is local and deterministic. It does not call a paid or external AI API and cannot mutate reports, users, claims, conversations or permissions.
- Any future provider secret must use an environment variable named like `FINDMATCH_AI_<PROVIDER>_API_KEY`; API keys are never database fields.
- Assistant outputs redact email addresses, phone numbers and common ownership evidence. Outputs are drafts or explanations only and are never sent or saved automatically.
- The dedicated AI audit log stores safe event metadata only. It deliberately excludes prompts, results, messages, phone numbers and ownership evidence.
- The assistant relies on the existing `MatchingService` and `ContentModerationService`; it cannot override normal matching, moderation or confirmation workflows.

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
