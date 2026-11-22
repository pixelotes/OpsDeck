"""One-way sync from Jira Service Management Assets into OpsDeck.

Each profile selects Jira objects (an object type plus an optional AQL filter) and says
what they become in OpsDeck. New objects are imported once with a few descriptive
fields; after that only their state is kept in sync (status and active/archived, and
the critical flag for suppliers). Everything else is owned by OpsDeck.

Credentials come from the Atlassian API connector (site URL, email, API token).
"""
import json

from ..extensions import db
from src.utils.timezone_helper import now

TARGET_ASSET = 'asset'
TARGET_SUPPLIER = 'supplier'
TARGET_LABELS = {TARGET_ASSET: 'Hardware asset', TARGET_SUPPLIER: 'Supplier'}
TARGETS = tuple(TARGET_LABELS)

# Actions a Jira status value can map to.
ACTION_ARCHIVE = 'archive'
ACTION_ACTIVE = 'active'
ASSET_STATUSES = ('In Use', 'Stored', 'In Repair', 'Awaiting Disposal')
TARGET_ACTIONS = {
    TARGET_ASSET: ASSET_STATUSES + (ACTION_ARCHIVE,),
    TARGET_SUPPLIER: (ACTION_ACTIVE, ACTION_ARCHIVE),
}

# Jira attribute names read when an object is first imported. A profile can override
# any of them in its field map; an empty name skips the field.
DEFAULT_FIELDS = {
    TARGET_ASSET: {
        'name': 'Name',
        'serial_number': 'Serial Number',
        'brand': 'Brand',
        'model': 'Model',
        'assignee': 'Assignee',
        'purchase_date': 'Order date',
    },
    TARGET_SUPPLIER: {
        'name': 'Name',
        'website': 'Website',
        'email': 'Email',
        'phone': 'Phone Number',
        'owner': 'SRM',
        'critical': 'Critical supplier',
    },
}
DEFAULT_STATUS_ATTRIBUTE = {TARGET_ASSET: 'Status', TARGET_SUPPLIER: 'Active contract'}
CRITICAL_YES = ('yes', 'true', 'y', '1')


class JiraAssetsProfile(db.Model):
    """What to import from Jira Assets and how to map its state."""
    __tablename__ = 'jira_assets_profile'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    target = db.Column(db.String(20), nullable=False)
    # Jira object type: its numeric id (e.g. 260) or its exact name (e.g. Laptop).
    object_type = db.Column(db.String(120), nullable=False)
    aql_filter = db.Column(db.Text)                 # optional, ANDed with the type
    status_attribute = db.Column(db.String(120), nullable=False)
    status_map_json = db.Column(db.Text, default='{}', nullable=False)
    field_map_json = db.Column(db.Text, default='{}', nullable=False)
    create_missing = db.Column(db.Boolean, default=True, nullable=False)
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    interval_hours = db.Column(db.Integer, default=0, nullable=False)   # 0 = manual only
    next_run_at = db.Column(db.DateTime)
    archive_threshold_percent = db.Column(db.Integer, default=10, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    runs = db.relationship('JiraAssetsRun', backref='profile', lazy='dynamic',
                           cascade='all, delete-orphan')

    @property
    def target_label(self):
        return TARGET_LABELS.get(self.target, self.target)

    @property
    def status_map(self):
        """{jira value: action}. Keys keep the case they were saved with."""
        return _load(self.status_map_json)

    @status_map.setter
    def status_map(self, value):
        self.status_map_json = json.dumps(value or {}, sort_keys=True)

    @property
    def field_map(self):
        """Creation fields -> Jira attribute names, defaults merged with overrides."""
        fields = dict(DEFAULT_FIELDS.get(self.target, {}))
        fields.update(_load(self.field_map_json))
        return fields

    @property
    def field_overrides(self):
        return _load(self.field_map_json)

    @field_overrides.setter
    def field_overrides(self, value):
        self.field_map_json = json.dumps(value or {}, sort_keys=True)

    @property
    def last_run(self):
        return self.runs.order_by(JiraAssetsRun.started_at.desc()).first()


class JiraAssetsRun(db.Model):
    """One execution (or dry run) of a profile."""
    __tablename__ = 'jira_assets_run'

    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('jira_assets_profile.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    trigger = db.Column(db.String(20), nullable=False)      # manual | scheduled | cli
    triggered_by = db.Column(db.String(120))
    dry_run = db.Column(db.Boolean, default=False, nullable=False)
    status = db.Column(db.String(20), default='running', nullable=False)  # running | success | aborted | error
    started_at = db.Column(db.DateTime, default=lambda: now(), nullable=False, index=True)
    finished_at = db.Column(db.DateTime)
    fetched_count = db.Column(db.Integer, default=0, nullable=False)
    created_count = db.Column(db.Integer, default=0, nullable=False)
    linked_count = db.Column(db.Integer, default=0, nullable=False)
    updated_count = db.Column(db.Integer, default=0, nullable=False)
    archived_count = db.Column(db.Integer, default=0, nullable=False)
    unarchived_count = db.Column(db.Integer, default=0, nullable=False)
    changes_json = db.Column(db.Text)
    error = db.Column(db.Text)

    @property
    def changes(self):
        """{'changes': [...], 'warnings': [...]} as recorded by the run."""
        data = _load(self.changes_json)
        return {'changes': data.get('changes', []), 'warnings': data.get('warnings', [])}


def _load(raw):
    try:
        value = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
