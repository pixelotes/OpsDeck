"""Microsoft Entra ID user sync configuration and run history.

The sync credentials (client id/secret, tenant) are never stored here: they come from
the AZURE_OAUTH_* environment variables shared with "Sign in with Microsoft".
"""
import json

from ..extensions import db
from src.utils.timezone_helper import now

SCHEDULE_OFF = 'off'
SCHEDULE_DAILY = 'daily'
SCHEDULE_INTERVAL = 'interval'
SCHEDULE_MODES = (SCHEDULE_OFF, SCHEDULE_DAILY, SCHEDULE_INTERVAL)


class EntraSyncSettings(db.Model):
    """Singleton holding the Entra ID user sync configuration."""
    __tablename__ = 'entra_sync_settings'

    id = db.Column(db.Integer, primary_key=True)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    # Entra group object ids, one per line (or comma separated).
    group_ids = db.Column(db.Text, default='')
    default_role = db.Column(db.String(50), default='user', nullable=False)
    schedule_mode = db.Column(db.String(20), default=SCHEDULE_OFF, nullable=False)
    daily_time = db.Column(db.String(5), default='03:00')       # HH:MM, local time
    interval_hours = db.Column(db.Integer, default=24)
    # Scheduled runs abort when they would archive more than this share of synced users.
    archive_threshold_percent = db.Column(db.Integer, default=10, nullable=False)
    # Whether users the sync creates may sign in. Off: they are "directory only"
    # (linkable to assets, refused at login). Ignored when access groups are set.
    new_user_login = db.Column(db.Boolean, default=False, server_default=db.false(), nullable=False)
    # Optional Entra group ids whose members may sign in. When set, sign-in access of
    # every synced user follows membership, and these members are synced too.
    access_group_ids = db.Column(db.Text, default='')
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    @staticmethod
    def _split_ids(raw):
        raw = (raw or '').replace(',', '\n')
        return [g.strip() for g in raw.splitlines() if g.strip()]

    @property
    def group_id_list(self):
        return self._split_ids(self.group_ids)

    @property
    def access_group_id_list(self):
        return self._split_ids(self.access_group_ids)

    @classmethod
    def get(cls):
        """Return the settings row, creating the default (disabled) one if missing."""
        settings = db.session.get(cls, 1)
        if settings is None:
            settings = cls(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings


class EntraSyncRun(db.Model):
    """One execution (or dry run) of the Entra ID user sync."""
    __tablename__ = 'entra_sync_run'

    id = db.Column(db.Integer, primary_key=True)
    trigger = db.Column(db.String(20), nullable=False)      # manual | scheduled | cli
    triggered_by = db.Column(db.String(120))                 # user email, or None
    dry_run = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default='running', nullable=False)  # running | success | aborted | error
    started_at = db.Column(db.DateTime, default=lambda: now(), nullable=False, index=True)
    finished_at = db.Column(db.DateTime)
    created_count = db.Column(db.Integer, default=0, nullable=False)
    updated_count = db.Column(db.Integer, default=0, nullable=False)
    archived_count = db.Column(db.Integer, default=0, nullable=False)
    unarchived_count = db.Column(db.Integer, default=0, nullable=False)
    changes_json = db.Column(db.Text)
    error = db.Column(db.Text)

    @property
    def changes(self):
        """{'changes': [...], 'errors': [...]} as recorded by the run."""
        try:
            data = json.loads(self.changes_json) if self.changes_json else {}
        except ValueError:
            data = {}
        return {'changes': data.get('changes', []), 'errors': data.get('errors', [])}
