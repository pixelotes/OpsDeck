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
