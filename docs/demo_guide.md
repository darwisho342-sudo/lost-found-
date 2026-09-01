# FindMatch Demonstration Guide

This guide prepares a repeatable, fictional localhost demonstration. It does not require internet access, external APIs, browser automation, or real personal information.

## Prepare or reset the demo

From the repository root with the virtual environment active:

```powershell
python manage.py migrate
python manage.py seed_data --reset-demo
python manage.py check
python manage.py runserver 8000 --noreload
```

Open `http://127.0.0.1:8000/en/`. The reset option deletes only records owned by the documented demo usernames and rebuilds their fictional workflows. It retains the accounts and does not touch unrelated users or reports.

The local credentials in the README are intentionally fake development credentials. Never reuse them outside this localhost demonstration.

### Verify a newly created local demo account

The normal email verification route still works: with the console email backend, copy the verification link printed by the development server. If email delivery is intentionally not being demonstrated, sign in to `/admin/` as `campus_admin`, open **User profiles**, select only the fictional account, and run **Mark selected email addresses as verified**. Only a superuser can see or execute this action. Use **Mark selected email addresses as unverified** to restore the restriction after the rehearsal.

An unverified account must receive 403 when it attempts an ownership claim. After the admin action, the same account may open and submit the private claim form; the report owner can then approve it, which creates the conversation. Rejection does not create a conversation. Manual verification is a localhost demonstration control, not a production verification design.

## Prepared roles

| Role | Username | Intended demonstration access |
|---|---|---|
| Regular Demo User A | `demo_student` | Both modes under the temporary open-access setting; owns the University Lost match and pending claim |
| Regular Demo User B | `demo_helper` | Both modes; owns the University Found match and reviews its pending claim |
| Personal-email user | `international_owner` | Both modes only while `OPEN_UNIVERSITY_ACCESS=True`; owns the International Lost match and returned-suitcase claim |
| Security staff | `security_staff` | Staff dashboard plus the explicit `items.manage_custody` permission |
| Administrator | `campus_admin` | Existing custom management pages and Django administration |

`international_finder` is an additional normal personal-email participant used as the finder in the International examples. No normal account is staff or a superuser.

## Prepared demonstration data

### University match and pending claim

- Lost: **Black wireless headphones**, owned by `demo_student`.
- Found: **Black headphones in case**, owned by `demo_helper`.
- Expected deterministic score: **92%**, above the 85% strong-notification threshold.
- The pair uses the same scope, category, item type, colours, fictional brand/model, compatible date direction, and Main Campus Library location.
- A Strong Possible Match notification is prepared for the owners.
- A separate pending ownership claim contains one fictional private answer. It has no conversation until approval.
- The Found report has a fictional University custody record visible only to authorized staff.

### International match

- Lost and Found: **Black Samsung phone**, owned by `international_owner` and `international_finder`.
- Expected deterministic score: **98%**.
- Both use International Mode with Türkiye, Istanbul, Kadikoy, and the fictional station entrance as structured public location data.
- The pair remains Active so mode filtering, match suggestions, score components, and notifications are easy to demonstrate.

### Completed return

- Found: **Returned red carry-on suitcase**, owned by `international_finder`.
- Claimant: `international_owner`.
- The seed command uses the existing approval, conversation, return-arrangement, finder-confirmation, and owner-confirmation services.
- Expected state: claim Completed, conversation Completed/read-only, arrangement Received/read-only, and report Returned/Resolved.

All locations and item details are fictional. Private answers are available only to the claim participants and authorized staff; they are intentionally omitted from this guide.

## Recommended rehearsal

1. Sign in as `demo_student`; show the normal dashboard and switch University → International → University.
2. Open the University Lost headphones report, then Possible Matches. Explain the 92% component breakdown and that no private claim field contributes.
3. Open Notifications and show the privacy-safe Strong Possible Match notice.
4. Open the pending claim as `demo_student`; sign in as `demo_helper` and show the finder review screen. Leave this prepared example pending.
5. Show that a normal account receives 403 for `/en/management/`, `/en/management/custody/`, and another user's edit URL.
6. Sign in as `security_staff`; show Management → Custody and the fictional stored headphones record.
7. Sign in as `international_owner`; select International Mode and show the 98% phone match and notification.
8. Open the completed red suitcase claim, its read-only conversation, its read-only return arrangement, both confirmation timestamps, and the Returned/Resolved report.
9. Sign in as `campus_admin`; show the custom management dashboard and, if needed, Django administration.
10. Repeat representative pages in Turkish and Arabic, confirming Arabic RTL. Toggle Light and Dark Mode.
11. Resize the browser to approximately 390 px wide and show the responsive navigation, cards, forms, and safe table scrolling.

Do not approve the prepared pending claim during the main rehearsal; it is intentionally separate from the completed-return example. If demonstration actions change the snapshot, rerun `python manage.py seed_data --reset-demo`.

## Screenshot targets

| Target | Suggested account/data | Presentation state |
|---|---|---|
| Homepage | Signed out, then `demo_student` | English Light Mode desktop; Arabic RTL alternative |
| Login and registration | Signed out | Empty safe form; no real details |
| Normal dashboard | `demo_student` | University Mode with fictional activity |
| Report Lost Item | `demo_student` | University Mode form before submission |
| Report Found Item | `demo_helper` | University Mode form and privacy review |
| Report details | University headphones pair | Public structured details only |
| Match score breakdown | `demo_student`, Lost headphones | 92% University comparison |
| International match | `international_owner`, Lost phone | 98% International comparison |
| Notifications | Either match owner | Strong Possible Match notice |
| Ownership claim | `demo_helper`, pending headphones claim | Private participant review |
| Conversation | Returned suitcase claim | Completed/read-only state |
| Return workflow | Returned suitcase claim | Received/read-only record |
| Returned item | Red carry-on suitcase | Returned/Resolved badge |
| Security page | `security_staff` | Custody inventory, no unrelated private detail |
| Administrator page | `campus_admin` | Custom dashboard statistics |
| Mobile view | Any public list/detail at ~390 px | Collapsed navigation and stacked cards |
| Turkish | `/tr/` | Homepage or report list |
| Arabic RTL | `/ar/` | Homepage, report details, or dashboard |
| Dark Mode | Any representative page | Theme toggle after a Light Mode capture |

Capture private screens only with the fictional accounts and data above. Do not include browser password prompts, terminal secrets, local filesystem paths, or unrelated database records.

## Reliability and recovery

- If a match is missing, confirm both reports are Active and the selected mode matches their scope, then reset the demo snapshot.
- If University Mode is unavailable to a normal personal account, confirm `OPEN_UNIVERSITY_ACCESS=True` for this local demonstration.
- Open access never grants staff, custody, or administrator permissions.
- Email verification uses the console backend; links print to the server terminal.
- Public media is under `media/`; private evidence and sensitive images are not publicly addressable and are served only through permission-checked views.
- Run `python manage.py test` before the final presentation if code or data preparation changes.
