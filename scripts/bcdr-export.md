# bcdr-export.py — BCDR Export (Disaster Recovery)

Standalone script that extracts **all data** from the OpsDeck database and generates a directory with one Excel file (`.xlsx`) per entity type. Intended for offline backups, audits, and data recovery in case of disaster.

## Requirements

```bash
pip install sqlalchemy psycopg2-binary openpyxl
```

## Configuration

All parameters can be supplied either as CLI flags or environment variables. **CLI flags take precedence** over environment variables.

| CLI flag | Environment variable | Default | Description |
|---|---|---|---|
| `--database-url` | `DATABASE_URL` | *(built from POSTGRES_\*)* | Full connection URL (overrides the `POSTGRES_*` vars) |
| `--host` | `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `--port` | `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `--db` | `POSTGRES_DB` | `opsdeck` | Database name |
| `--user` | `POSTGRES_USER` | `opsdeck` | DB user |
| *(no flag)* | `POSTGRES_PASSWORD` | `opsdeck` | DB password. Environment only — a password given as a command-line argument shows up in `ps` for every other user on the host and is written to shell history |
| `--output` / `-o` | `OUTPUT_DIR` | `bcdr_opsdeck_YYYYMMDD_HHMM/` | Output directory |
| *(no flag)* | `BCDR_OUTPUT_ROOT` | *(unset — no restriction)* | When set, the output directory must resolve inside it, and the script exits with an error otherwise. Intended for running the export from a scheduler or an agent, where a wrong `--output` should fail rather than write 56 spreadsheets somewhere unexpected. It constrains a mistaken caller, not a hostile one — whatever can choose the arguments can usually choose the environment too |

Because every parameter is env-configurable and none is required, the script runs with no flags inside a container — ideal for mounting Kubernetes secrets as environment variables:

```yaml
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef: { name: opsdeck-db, key: url }
  - name: OUTPUT_DIR
    value: /backups
```

## Usage

```bash
# Connection via DATABASE_URL (recommended)
python scripts/bcdr-export.py --database-url postgresql://opsdeck:opsdeck@localhost:5432/opsdeck

# Connection via individual parameters (password from the environment)
POSTGRES_PASSWORD=... python scripts/bcdr-export.py --host db.prod.internal --port 5432 --db opsdeck --user opsdeck

# Custom output directory
python scripts/bcdr-export.py --database-url $DATABASE_URL --output /backups/opsdeck_20260224

# Pure environment-variable invocation (no flags)
export DATABASE_URL=postgresql://opsdeck:opsdeck@localhost:5432/opsdeck
export OUTPUT_DIR=/backups/opsdeck
python scripts/bcdr-export.py
```

If neither `--output` nor `OUTPUT_DIR` is set, a `bcdr_opsdeck_YYYYMMDD_HHMM/` directory is created in the current directory.

## Running inside Docker

The DB port is usually not exposed to the host, so it is easier to run from inside the web container:

```bash
# Copy the script into the container and run it
docker cp scripts/bcdr-export.py opsdeck-web-1:/tmp/bcdr-export.py

# Install openpyxl if missing (sqlalchemy and psycopg2 are already in the image)
docker exec opsdeck-web-1 pip install openpyxl

# Run
docker exec opsdeck-web-1 python /tmp/bcdr-export.py \
  --database-url postgresql://opsdeck:opsdeck@db:5432/opsdeck \
  --output /tmp/bcdr-export

# Copy the result back to the host
docker cp opsdeck-web-1:/tmp/bcdr-export/. ./export/
```

## Output

A directory with **57 files** is generated:

| Category | Files |
|---|---|
| **Organization** | Users, Groups, Locations, Org_Settings |
| **Assets & Inventory** | Assets, Peripherals, Software, Licenses, Maintenance_Logs, Disposal_Records, Asset_Inventories |
| **Procurement & Vendors** | Suppliers, Contacts, Subscriptions, Contracts, Purchases, Budgets, Payment_Methods, Cost_Centers, Requirements, Opportunities |
| **Services & Credentials** | Business_Services, Service_Components, Configurations, Credentials, Credential_Secrets, Certificates, Certificate_Versions |
| **Security & Risks** | Risks, Threat_Types, Security_Activities, Activity_Executions, Security_Assessments, Risk_Assessments |
| **Incidents & Changes** | Incidents, Post-Incident_Reviews, Changes |
| **Compliance & Audits** | Frameworks, Framework_Controls, Compliance_Links, Compliance_Rules, Audits, Audit_Items, Policies, Policy_Versions |
| **BCDR & HR** | BCDR_Plans, BCDR_Tests, Onboarding, Offboarding, Onboarding_Packs |
| **Documentation & Comms** | Links, Documents, Tags, Attachments, Email_Templates, Campaigns |

Plus an `_Index.xlsx` file with the summary of all files and counts.

### Format of each file

- Title with entity name and export date
- Styled headers (dark blue, white text)
- Status columns with conditional colors (green/yellow/red)
- Long text columns with left alignment and wrap
- Auto-adjusted column widths
- IDs included so relationships between entities can be reconstructed

## Notes

- **Credential secrets** are exported masked (as stored in the DB, never the real value).
- **Attachments** are exported as metadata (name, type, ID). The physical files are stored separately in the uploads volume.
- Works with PostgreSQL (production) and with SQLite if a `sqlite:///` URL is passed.
- If a table does not exist (for example in an older version), the sheet is generated with an error message instead of failing.
