# google-provision.py — OpsDeck to Google Workspace Sync

> **Unsupported.** The script depends on OpsDeck API endpoints that do not exist
> (`/api/v1/onboardings/pending-provisioning`, `/api/v1/offboardings/pending-suspension`,
> `.../mark-provisioned`, `.../mark-suspended`), so it exits with an error instead of
> running. The rest of this page describes the intended design and is kept for reference.

Script that reads pending onboardings/offboardings from OpsDeck and provisions or suspends users in Google Workspace via the Admin Directory API.

## Requirements

```bash
pip install requests google-auth google-api-python-client
```

## Environment variables

### Required

| Variable | Description | Example |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to the service account JSON | `/etc/opsdeck/sa.json` |
| `GOOGLE_DELEGATED_USER` | Admin email for domain-wide delegation | `admin@yourdomain.com` |
| `OPSDECK_URL` | OpsDeck base URL | `https://opsdeck.internal` |
| `OPSDECK_API_TOKEN` | Bearer token (requires admin role) | `abc123...` |

### Optional

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_ORG_UNIT` | `/` | OU path for new users |
| `GOOGLE_DOMAIN` | *(empty)* | Domain for validation (e.g. `yourdomain.com`) |

## Usage

```bash
# Configure variables
export GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/service-account.json
export GOOGLE_DELEGATED_USER=admin@yourdomain.com
export OPSDECK_URL=https://opsdeck.internal
export OPSDECK_API_TOKEN=your-opsdeck-token

# Preview provisioning (creates nothing in Google)
python scripts/google-provision.py provision --dry-run

# Run provisioning
python scripts/google-provision.py provision --execute

# Preview suspensions
python scripts/google-provision.py suspend --dry-run

# Run suspensions
python scripts/google-provision.py suspend --execute

# All at once (provision + suspend)
python scripts/google-provision.py all --dry-run
python scripts/google-provision.py all --execute
```

## Commands

| Command | Description |
|---|---|
| `provision` | Creates users in Google from pending onboardings in OpsDeck |
| `suspend` | Suspends users in Google from pending offboardings in OpsDeck |
| `all` | Runs provision + suspend |

`--dry-run` or `--execute` is always required to avoid accidental runs.

## Provisioning flow

1. Reads pending onboardings from `GET /api/v1/onboardings/pending-provisioning`
2. Validates the email domain (if `GOOGLE_DOMAIN` is configured)
3. Creates the user in Google Workspace with:
   - Email, name (split into givenName/familyName)
   - Random temporary password (24 chars, must be changed at first login)
   - Configured OU path
   - Department and job_title if available
4. Marks the onboarding as provisioned in OpsDeck via `POST /api/v1/onboardings/{id}/mark-provisioned`
5. If the user already exists in Google (409), it is marked as provisioned anyway

## Suspension flow

1. Reads pending offboardings from `GET /api/v1/offboardings/pending-suspension`
2. Suspends the user in Google using `external_id` (Google ID) or email as a fallback
3. Marks the offboarding as suspended in OpsDeck via `POST /api/v1/offboardings/{id}/mark-suspended`
4. If the user does not exist in Google (404), it is marked as suspended anyway

## Google Cloud configuration

For the script to work you need:

1. **Service Account** with domain-wide delegation enabled
2. **Scope** authorized in the Google admin console: `https://www.googleapis.com/auth/admin.directory.user`
3. **JSON key** of the service account downloaded and referenced in `GOOGLE_SERVICE_ACCOUNT_JSON`

## Notes

- Google credentials are only required in `--execute` mode. `--dry-run` mode only needs access to the OpsDeck API.
- Temporary passwords are generated with `secrets.choice()` and are 24 alphanumeric characters + symbols.
- If `GOOGLE_DOMAIN` is configured, emails that do not match are skipped without error.
