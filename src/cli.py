import os
import click


def register_commands(app):

    @app.cli.group()
    def data_import():
        """Bulk import data from CSV files (same engine as the admin Import screen)."""
        pass

    def _run(type_key, filename):
        """Import a CSV via the shared import service and print a report.

        Uses the exact same logic and rules as Administration > Import Data.
        """
        from .services.import_service import process, get_importer

        if not os.path.exists(filename):
            print(f"❌ Error: File '{filename}' not found.")
            return
        with open(filename, 'r', encoding='utf-8-sig') as f:
            csv_text = f.read()

        try:
            result = process(type_key, csv_text, commit=True)
        except ValueError as exc:
            print(f"❌ Error: {exc}")
            return

        # Per-row feedback for anything not created (skipped/errored).
        for row in result['results']:
            if row['status'] != 'create':
                print(f"  [{row['status']}] row {row['index']}: {row['message']}")

        # Generated secrets (e.g. user passwords) — shown once.
        if result['notes']:
            print(f"{'NAME':<30} | {'EMAIL':<30} | {'GENERATED PASSWORD'}")
            print("-" * 85)
            for note in result['notes']:
                print(f"{note.get('name', ''):<30} | {note.get('email', ''):<30} | {note.get('password', '')}")
            print("-" * 85)

        counts = result['counts']
        label = get_importer(type_key)['label']
        print(f"✅ {label}: created {counts['create']}, skipped {counts['skip']}, errors {counts['error']}.")

    # Register one CLI command per importable type, mirroring the admin UI.
    from .services.import_service import IMPORTERS, get_importer

    def _make_command(type_key):
        cfg = get_importer(type_key)
        optional = cfg.get('optional', [])
        cols = ', '.join(cfg['required'])
        if optional:
            cols += f" [, {', '.join(optional)}]"

        @data_import.command(type_key)
        @click.argument('filename')
        def _command(filename):
            _run(type_key, filename)

        _command.__doc__ = f"Import {cfg['label']}. Columns: {cols}"
        return _command

    for _key in IMPORTERS:
        _make_command(_key)

    @app.cli.command('entra-sync')
    @click.option('--dry-run', is_flag=True, help='Show what would change without writing anything.')
    @click.option('--force', is_flag=True,
                  help='Apply even if the run would archive more users than the safety threshold.')
    def entra_sync(dry_run, force):
        """Sync users from the configured Microsoft Entra ID groups."""
        from .services.entra_sync_service import run_sync, EntraSyncError

        try:
            run = run_sync('cli', dry_run=dry_run, enforce_brake=not force)
        except EntraSyncError as exc:
            print(f"❌ {exc}")
            raise SystemExit(1)

        for change in run.changes['changes']:
            fields = ', '.join(sorted(change['fields'])) if change['fields'] else ''
            print(f"  [{change['action']}] {change['upn']} {fields}")
        for err in run.changes['errors']:
            print(f"  [error] {err['upn']}: {err['error']}")

        prefix = 'Dry run' if dry_run else 'Sync'
        summary = (f"{run.created_count} to create, {run.updated_count} to update, "
                   f"{run.archived_count} to archive, {run.unarchived_count} to unarchive")
        if run.status == 'success':
            print(f"✅ {prefix} finished: {summary}.")
        else:
            print(f"❌ {prefix} {run.status}: {run.error}")
            raise SystemExit(1)

    @app.cli.command('jira-assets-sync')
    @click.option('--profile', 'profile_ref', help='Profile id or name. Default: every enabled profile.')
    @click.option('--dry-run', is_flag=True, help='Show what would change without writing anything.')
    @click.option('--force', is_flag=True,
                  help='Apply even if the run would archive more records than the safety threshold.')
    def jira_assets_sync(profile_ref, dry_run, force):
        """Sync assets and suppliers from Jira Service Management Assets."""
        from .models.jira_assets import JiraAssetsProfile
        from .services.jira_assets_service import run_sync, JiraAssetsSyncError

        if profile_ref:
            query = JiraAssetsProfile.query
            profile = (query.filter_by(id=int(profile_ref)).first() if profile_ref.isdigit()
                       else query.filter_by(name=profile_ref).first())
            if profile is None:
                print(f"❌ No profile '{profile_ref}'.")
                raise SystemExit(1)
            profiles = [profile]
        else:
            profiles = JiraAssetsProfile.query.filter_by(enabled=True).order_by(JiraAssetsProfile.id).all()
            if not profiles:
                print("Nothing to do: no enabled profile (use --profile to run a disabled one).")
                return

        failed = False
        for profile in profiles:
            try:
                run = run_sync(profile, 'cli', dry_run=dry_run, enforce_brake=not force)
            except JiraAssetsSyncError as exc:
                print(f"❌ {profile.name}: {exc}")
                failed = True
                continue
            for change in run.changes['changes']:
                fields = ', '.join(sorted(k for k in change['fields'] if k != 'jira_object_id'))
                print(f"  [{change['action']}] {change['jira_key'] or change['jira_id']} {change['label']} {fields}")
            for warning in run.changes['warnings']:
                print(f"  [warning] {warning}")
            summary = (f"{run.fetched_count} fetched, {run.created_count} created, {run.linked_count} linked, "
                       f"{run.updated_count} updated, {run.archived_count} archived, "
                       f"{run.unarchived_count} unarchived")
            if run.status == 'success':
                print(f"✅ {profile.name} ({'dry run' if dry_run else 'applied'}): {summary}.")
            else:
                print(f"❌ {profile.name} {run.status}: {run.error}")
                failed = True
        if failed:
            raise SystemExit(1)

    @app.cli.command('rotate-data-encryption-key')
    def rotate_data_encryption_key():
        """Re-encrypt stored secrets under the first DATA_ENCRYPTION_KEY.

        To rotate: prepend the new key to DATA_ENCRYPTION_KEY (new,old), run this, then
        remove the old key. Run it too after first setting DATA_ENCRYPTION_KEY: values
        encrypted with the SECRET_KEY-derived key are moved to the new key.
        """
        from sqlalchemy.orm.attributes import flag_modified
        from .extensions import db
        from .models.connectors import ConnectorTask, ENC_MARKER
        from .utils import crypto

        rotated = 0
        try:
            for task in ConnectorTask.query.all():
                cfg = dict(task.auth_config or {})
                changed = False
                for key, value in cfg.items():
                    if isinstance(value, dict) and ENC_MARKER in value:
                        cfg[key] = {**value, ENC_MARKER: crypto.rotate(value[ENC_MARKER])}
                        changed = True
                if changed:
                    task.auth_config = cfg
                    flag_modified(task, 'auth_config')
                    rotated += 1
            db.session.commit()
        except crypto.DecryptionError as exc:
            db.session.rollback()
            print(f"❌ {exc} Nothing was changed.")
            raise SystemExit(1)
        print(f"✅ Re-encrypted the secrets of {rotated} connector task(s).")
