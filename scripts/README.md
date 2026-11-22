# OpsDeck Scripts

Helper and integration scripts for OpsDeck. Each script has its own `.md` with full documentation, environment variables, and options.

- **bcdr-export.py** — Extracts all data from the OpsDeck database into a directory of Excel files, for offline backups and disaster recovery. See [bcdr-export.md](bcdr-export.md).
  ```bash
  python scripts/bcdr-export.py --database-url $DATABASE_URL --output /backups/opsdeck
  ```

- **google-provision.py** — *Unsupported: needs OpsDeck API endpoints that do not exist yet; exits with an error.* Meant to provision or suspends users in Google Workspace from pending OpsDeck onboardings/offboardings (OpsDeck → Google). See [google-provision.md](google-provision.md).
  ```bash
  python scripts/google-provision.py provision --dry-run
  ```

- **google-import.py** — Imports Google Workspace users that don't yet exist in OpsDeck, optionally scoped to an org unit (Google → OpsDeck). See [google-import.md](google-import.md).
  ```bash
  python scripts/google-import.py --org-unit /Employees --dry-run
  ```

- **jira-sync.py** — Syncs Jira tickets (changes, incidents, onboardings) into OpsDeck via its REST API (Jira → OpsDeck). See [jira-sync.md](jira-sync.md).
  ```bash
  python scripts/jira-sync.py --dry-run
  ```
