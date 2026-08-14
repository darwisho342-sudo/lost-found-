# Database and media operations

## Development and production choices

SQLite is the default local database. PostgreSQL is selected only when `DB_ENGINE=postgresql`; credentials come from environment variables and must never be committed. Use the same application release and migrations at both ends.

## SQLite to PostgreSQL transfer

1. Stop writes and make recoverable copies of `db.sqlite3`, `media/`, and `private_media/`.
2. On the SQLite configuration, run `python manage.py check`, `python manage.py migrate`, and `python manage.py dumpdata --natural-foreign --natural-primary --exclude contenttypes --exclude auth.permission --indent 2 --output findmatch-data.json`.
3. Create an empty PostgreSQL database and least-privileged application user. Require TLS for a remote database.
4. Set `DB_ENGINE=postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, and `DB_SSLMODE` in the deployment secret manager.
5. Run `python manage.py migrate` against the empty PostgreSQL database.
6. Load the export with `python manage.py loaddata findmatch-data.json`. Treat the export as sensitive because it can contain private application records.
7. Run `python manage.py check`, `python manage.py test`, and privacy-safe row-count comparisons for users, reports, claims, questions, answers, evidence references, conversations, messages, notifications, return arrangements, organizations, custody events, and audit events.
8. Verify representative foreign-key relationships and permission-protected downloads with two normal users and an administrator.
9. Copy public and private media without changing relative names. Keep private media outside the public web root.
10. Switch application traffic only after verification. Retain the original read-only backup until the rollback window closes.

Primary keys are preserved by Django serialization. After import, PostgreSQL sequences should be checked and reset with `python manage.py sqlsequencereset items auth | python manage.py dbshell` when the deployment process requires it.

## Backup and restore

For PostgreSQL, use an encrypted `pg_dump` custom-format backup plus separate encrypted public/private media backups. Restore to an empty database with `pg_restore`, run migrations, restore media, then perform row-count and permission checks. Test restoration regularly in a non-production environment.

For SQLite, stop application writes before copying `db.sqlite3`. A database copy without matching media backups is incomplete. Never place database exports, private media, environment files, or credentials in Git.
