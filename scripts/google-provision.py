#!/usr/bin/env python3
"""
OpsDeck → Google Workspace Sync Script

UNSUPPORTED: this script calls OpsDeck API endpoints that do not exist
(/api/v1/onboardings/pending-provisioning, /api/v1/offboardings/pending-suspension
and the mark-provisioned / mark-suspended actions). It exits with an error
instead of running. Kept for reference until those endpoints are built.

Reads pending onboardings/offboardings from OpsDeck API and provisions
or suspends users in Google Workspace via the Admin Directory API.

Usage:
    python google-provision.py provision --dry-run    # Preview new Google users
    python google-provision.py provision --execute    # Create users in Google
    python google-provision.py suspend --dry-run      # Preview suspensions
    python google-provision.py suspend --execute      # Suspend users in Google
    python google-provision.py all --dry-run          # Preview both
    python google-provision.py all --execute          # Run both

Environment variables (required):
    GOOGLE_SERVICE_ACCOUNT_JSON   Path to service account JSON file
    GOOGLE_DELEGATED_USER         Admin email for domain-wide delegation
    OPSDECK_URL                   OpsDeck base URL (e.g. https://opsdeck.internal)
    OPSDECK_API_TOKEN             Bearer token (admin role required)

Environment variables (optional):
    GOOGLE_ORG_UNIT               OU path for new users (default: /)
    GOOGLE_DOMAIN                 Domain validation (e.g. yourdomain.com)
"""

import argparse
import json
import os
import sys
import time

import requests

# ─── Configuration ──────────────────────────────────────────────────────────

GOOGLE_SA_JSON_PATH = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
GOOGLE_DELEGATED_USER = os.environ.get("GOOGLE_DELEGATED_USER", "")
GOOGLE_ORG_UNIT = os.environ.get("GOOGLE_ORG_UNIT", "/")
GOOGLE_DOMAIN = os.environ.get("GOOGLE_DOMAIN", "")

OPSDECK_URL = os.environ.get("OPSDECK_URL", "").rstrip("/")
OPSDECK_API_TOKEN = os.environ.get("OPSDECK_API_TOKEN", "")


# ─── Google Admin SDK Client ───────────────────────────────────────────────

def get_google_service():
    """Build an authenticated Google Admin SDK service using service account."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        print("Error: google-auth and google-api-python-client are required.")
        print("Install with: pip install google-auth google-api-python-client")
        sys.exit(1)

    credentials = service_account.Credentials.from_service_account_file(
        GOOGLE_SA_JSON_PATH,
        scopes=["https://www.googleapis.com/auth/admin.directory.user"],
        subject=GOOGLE_DELEGATED_USER,
    )
    return build("admin", "directory_v1", credentials=credentials)


def google_create_user(service, email, name, org_unit, department=None, job_title=None):
    """Create a user in Google Workspace. Returns the Google user object."""
    parts = name.split(" ", 1)
    given_name = parts[0]
    family_name = parts[1] if len(parts) > 1 else parts[0]

    body = {
        "primaryEmail": email,
        "name": {"givenName": given_name, "familyName": family_name},
        "password": _generate_temp_password(),
        "changePasswordAtNextLogin": True,
        "orgUnitPath": org_unit,
    }

    if department:
        body["organizations"] = [{"department": department, "title": job_title or ""}]

    return service.users().insert(body=body).execute()


def google_suspend_user(service, user_key):
    """Suspend a user in Google Workspace."""
    return service.users().patch(
        userKey=user_key,
        body={"suspended": True},
    ).execute()


def _generate_temp_password():
    """Generate a strong temporary password for initial provisioning."""
    import secrets
    import string
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(24))


# ─── OpsDeck API Client ───────────────────────────────────────────────────

def opsdeck_headers():
    return {
        "Authorization": f"Bearer {OPSDECK_API_TOKEN}",
        "Content-Type": "application/json",
    }


def opsdeck_get(endpoint):
    """GET from OpsDeck API."""
    url = f"{OPSDECK_URL}/api/v1/{endpoint}"
    resp = requests.get(url, headers=opsdeck_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


def opsdeck_post(endpoint, payload=None):
    """POST to OpsDeck API."""
    url = f"{OPSDECK_URL}/api/v1/{endpoint}"
    resp = requests.post(url, json=payload or {}, headers=opsdeck_headers(), timeout=30)
    resp.raise_for_status()
    return resp.json()


# ─── Provision (OpsDeck → Google) ─────────────────────────────────────────

def provision(dry_run=True):
    """Create Google users from pending OpsDeck onboardings."""
    print("\n── Provision: OpsDeck → Google ─────────────────────────")
    print(f"  Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print(f"  OU:   {GOOGLE_ORG_UNIT}")
    print()

    pending = opsdeck_get("onboardings/pending-provisioning")
    if not pending:
        print("  No pending onboardings. Nothing to do.")
        return {"created": 0, "skipped": 0, "errors": 0}

    print(f"  Found {len(pending)} onboarding(s) pending provisioning.\n")

    service = None if dry_run else get_google_service()
    stats = {"created": 0, "skipped": 0, "errors": 0}

    for item in pending:
        user = item["user"]
        email = user["email"]
        name = user["name"]
        dept = user.get("department") or ""
        title = user.get("job_title") or ""

        # Domain validation
        if GOOGLE_DOMAIN and not email.endswith(f"@{GOOGLE_DOMAIN}"):
            print(f"  SKIP: {email} — domain mismatch (expected @{GOOGLE_DOMAIN})")
            stats["skipped"] += 1
            continue

        if dry_run:
            print(f"  Would CREATE: {email} ({name})")
            print(f"    OU: {GOOGLE_ORG_UNIT}, dept: {dept}, title: {title}")
            print(f"    changePasswordAtNextLogin: true")
            stats["created"] += 1
            continue

        try:
            result = google_create_user(
                service, email, name, GOOGLE_ORG_UNIT,
                department=dept, job_title=title,
            )
            google_id = result.get("id")
            print(f"  CREATED: {email} (Google ID: {google_id})")

            # Mark as provisioned in OpsDeck
            opsdeck_post(
                f"onboardings/{item['id']}/mark-provisioned",
                {"google_id": google_id},
            )
            stats["created"] += 1

        except Exception as e:
            error_msg = str(e)
            # Handle "user already exists" gracefully
            if "Entity already exists" in error_msg or "409" in error_msg:
                print(f"  EXISTS: {email} — already in Google, marking as provisioned")
                try:
                    opsdeck_post(f"onboardings/{item['id']}/mark-provisioned")
                except Exception:
                    pass
                stats["skipped"] += 1
            else:
                print(f"  ERROR: {email} — {error_msg}")
                stats["errors"] += 1

    print(f"\n  Summary: {stats['created']} created, {stats['skipped']} skipped, {stats['errors']} errors")
    return stats


# ─── Suspend (OpsDeck → Google) ──────────────────────────────────────────

def suspend(dry_run=True):
    """Suspend Google users from completed OpsDeck offboardings."""
    print("\n── Suspend: OpsDeck → Google ───────────────────────────")
    print(f"  Mode: {'DRY RUN' if dry_run else 'EXECUTE'}")
    print()

    pending = opsdeck_get("offboardings/pending-suspension")
    if not pending:
        print("  No pending offboardings. Nothing to do.")
        return {"suspended": 0, "skipped": 0, "errors": 0}

    print(f"  Found {len(pending)} offboarding(s) pending suspension.\n")

    service = None if dry_run else get_google_service()
    stats = {"suspended": 0, "skipped": 0, "errors": 0}

    for item in pending:
        user = item["user"]
        email = user["email"]
        name = user["name"]
        departure = item.get("departure_date", "?")
        # Prefer external_id (Google ID) over email for lookup
        user_key = user.get("external_id") or email

        if dry_run:
            print(f"  Would SUSPEND: {email} ({name})")
            print(f"    Departure: {departure}, lookup key: {user_key}")
            stats["suspended"] += 1
            continue

        try:
            google_suspend_user(service, user_key)
            print(f"  SUSPENDED: {email}")

            # Mark as suspended in OpsDeck
            opsdeck_post(f"offboardings/{item['id']}/mark-suspended")
            stats["suspended"] += 1

        except Exception as e:
            error_msg = str(e)
            # Handle "user not found" gracefully (already deleted/suspended)
            if "Resource Not Found" in error_msg or "404" in error_msg:
                print(f"  NOT FOUND: {email} — already gone from Google, marking as suspended")
                try:
                    opsdeck_post(f"offboardings/{item['id']}/mark-suspended")
                except Exception:
                    pass
                stats["skipped"] += 1
            else:
                print(f"  ERROR: {email} — {error_msg}")
                stats["errors"] += 1

    print(f"\n  Summary: {stats['suspended']} suspended, {stats['skipped']} skipped, {stats['errors']} errors")
    return stats


# ─── CLI ────────────────────────────────────────────────────────────────────

def validate_env(need_google=True):
    """Check that required environment variables are set."""
    missing = []
    for var in ("OPSDECK_URL", "OPSDECK_API_TOKEN"):
        if not os.environ.get(var):
            missing.append(var)
    if need_google:
        for var in ("GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_DELEGATED_USER"):
            if not os.environ.get(var):
                missing.append(var)
    if missing:
        print(f"Error: missing required environment variables:\n  {', '.join(missing)}")
        print("\nSet them before running this script. See --help for details.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Sync OpsDeck onboardings/offboardings to Google Workspace",
    )
    parser.add_argument(
        "command",
        choices=["provision", "suspend", "all"],
        help="What to sync: provision (create users), suspend (suspend users), all (both)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would happen without making changes",
    )
    group.add_argument(
        "--execute",
        action="store_true",
        help="Actually create/suspend users in Google",
    )
    args = parser.parse_args()

    print(
        "Error: google-provision.py is unsupported. It needs OpsDeck API endpoints "
        "(onboardings/pending-provisioning, offboardings/pending-suspension, "
        "mark-provisioned, mark-suspended) that OpsDeck does not provide.",
        file=sys.stderr,
    )
    sys.exit(2)

    dry_run = args.dry_run
    need_google = not dry_run  # Google credentials only needed in execute mode
    validate_env(need_google=need_google)

    print("\n══ OpsDeck → Google Workspace Sync ═════════════════════")
    print(f"  OpsDeck: {OPSDECK_URL}")
    if not dry_run:
        print(f"  Google:  delegated as {GOOGLE_DELEGATED_USER}")
    print(f"  Command: {args.command}")
    print(f"  Mode:    {'DRY RUN' if dry_run else 'EXECUTE'}")

    if args.command in ("provision", "all"):
        provision(dry_run=dry_run)

    if args.command in ("suspend", "all"):
        suspend(dry_run=dry_run)

    print("\n══ Done ════════════════════════════════════════════════\n")


if __name__ == "__main__":
    main()
