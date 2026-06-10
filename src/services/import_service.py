"""Reusable bulk CSV import service (shared by the admin UI and the CLI).

A small registry declares, per importable type, its columns, a sample row for
the downloadable template, and a per-row handler. `process()` parses CSV text,
classifies every row as create/skip/error and — when ``commit=True`` — persists.

This powers the admin Import workflow (download template -> upload -> preview ->
confirm) and the ``flask data-import`` commands, so the logic lives in one place.
Adding a new importable type = add one entry to ``IMPORTERS``.
"""
import csv
import io

from ..extensions import db
from ..models import User
from ..utils.helpers import generate_secure_password, get_csv_reader

MAX_ROWS = 5000


def _read_rows(csv_text):
    """Parse CSV text into (fieldnames, [row-dict]). Trims keys/values."""
    reader = get_csv_reader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise ValueError('The CSV file has no header row.')
    fieldnames = [(f or '').strip() for f in reader.fieldnames]
    rows = []
    for raw in reader:
        rows.append({(k or '').strip(): (v.strip() if isinstance(v, str) else v)
                     for k, v in raw.items()})
    return fieldnames, rows


# --------------------------------------------------------------------------- #
# Users importer
# --------------------------------------------------------------------------- #
def _users_init(_rows):
    existing = {e.lower() for (e,) in db.session.query(User.email).all() if e}
    return {'existing': existing, 'seen': set()}


def _users_handle(row, ctx, persist):
    name = (row.get('name') or '').strip()
    email = (row.get('email') or '').strip()
    display = {'name': name, 'email': email}
    if not name or not email:
        return 'error', 'Missing name or email', display, None
    key = email.lower()
    if key in ctx['existing'] or key in ctx['seen']:
        return 'skip', 'A user with this email already exists', display, None
    ctx['seen'].add(key)
    note = None
    if persist:
        password = generate_secure_password()
        user = User(name=name, email=email, role='user')  # role forced for safety
        user.set_password(password)
        db.session.add(user)
        note = {'name': name, 'email': email, 'password': password}
    return 'create', 'Created' if persist else 'Will be created', display, note


IMPORTERS = {
    'users': {
        'label': 'Users',
        'description': ('Create user accounts. New users get the "user" role and a '
                        'generated password (shown once, after import).'),
        'required': ['name', 'email'],
        'optional': [],
        'sample': [
            {'name': 'Jane Doe', 'email': 'jane.doe@example.com'},
            {'name': 'John Smith', 'email': 'john.smith@example.com'},
        ],
        'note_label': 'Generated passwords',
        'init': _users_init,
        'handle': _users_handle,
    },
}


def get_importer(type_key):
    cfg = IMPORTERS.get(type_key)
    if not cfg:
        raise ValueError(f'Unknown import type: {type_key}')
    return cfg


def template_csv(type_key):
    """Return CSV text for the downloadable template (header + sample rows)."""
    cfg = get_importer(type_key)
    cols = cfg['required'] + cfg.get('optional', [])
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=cols)
    writer.writeheader()
    for sample in cfg.get('sample', []):
        writer.writerow({c: sample.get(c, '') for c in cols})
    return out.getvalue()


def process(type_key, csv_text, commit=False):
    """Parse + classify (and optionally persist) CSV rows for ``type_key``.

    Returns a dict: columns, results[{index, display, status, message}],
    counts{create,skip,error}, notes[...], note_label.
    Raises ValueError for structural problems (bad header, too many rows).
    """
    cfg = get_importer(type_key)
    fieldnames, rows = _read_rows(csv_text)

    missing = [c for c in cfg['required'] if c not in fieldnames]
    if missing:
        raise ValueError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Found: {', '.join(fieldnames) or '(none)'}."
        )
    if len(rows) > MAX_ROWS:
        raise ValueError(f'Too many rows ({len(rows)}); the maximum is {MAX_ROWS} per import.')

    ctx = cfg['init'](rows) if cfg.get('init') else {}
    results, notes = [], []
    counts = {'create': 0, 'skip': 0, 'error': 0}

    for i, row in enumerate(rows, start=1):
        try:
            status, message, display, note = cfg['handle'](row, ctx, commit)
        except Exception as exc:  # never let one bad row abort the whole import
            status, message = 'error', f'Error: {exc}'
            display = {c: row.get(c, '') for c in (cfg['required'] + cfg.get('optional', []))}
            note = None
        counts[status] += 1
        results.append({'index': i, 'display': display, 'status': status, 'message': message})
        if note:
            notes.append(note)

    if commit:
        db.session.commit()

    return {
        'columns': cfg['required'] + cfg.get('optional', []),
        'results': results,
        'counts': counts,
        'notes': notes,
        'note_label': cfg.get('note_label'),
    }
