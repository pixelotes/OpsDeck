"""API connectors: scheduled syncs that pull data from external services.

A ConnectorTask is one external service (Google Workspace, GitHub, AWS, ...) with its
credentials and polling interval. Each ConnectorSubtask is one endpoint of that service,
and each run of a subtask stores the fetched JSON as a ConnectorReport, so runs can be
diffed against each other and used as a User Access Review source.

These tables used to belong to the opsdeck-enterprise plugin (enterprise_tasks,
enterprise_subtasks, enterprise_reports); migration 025 renames them in place.
"""
import json

from sqlalchemy.orm.attributes import flag_modified

from ..extensions import db
from ..utils import crypto
from src.utils.timezone_helper import now

CONNECTOR_SERVICES = {
    'google': 'Google Workspace',
    'microsoft': 'Microsoft 365',
    'github': 'GitHub',
    'jumpcloud': 'JumpCloud',
    'atlassian': 'Atlassian',
    'aws': 'AWS',
}

# auth_config keys that hold secrets. They are stored encrypted, as
# {"$enc": "<fernet token>"} (plus "$json": true when the value was a dict/list),
# and every other key (tenant id, region, organization...) stays readable so the
# credentials form can show it.
SECRET_FIELDS = frozenset({
    'client_secret', 'aws_secret_key', 'api_token', 'access_token', 'api_key',
    'service_account_json',
})
ENC_MARKER = '$enc'


def _is_encrypted(value):
    return isinstance(value, dict) and ENC_MARKER in value


def encrypt_auth_config(cfg):
    """Return a copy of ``cfg`` with SECRET_FIELDS encrypted (already-encrypted ones kept)."""
    out = {}
    for key, value in (cfg or {}).items():
        if key in SECRET_FIELDS and value not in (None, '') and not _is_encrypted(value):
            is_json = not isinstance(value, str)
            plain = json.dumps(value) if is_json else value
            value = {ENC_MARKER: crypto.encrypt(plain)}
            if is_json:
                value['$json'] = True
        out[key] = value
    return out


def decrypt_auth_config(cfg):
    """Return a copy of ``cfg`` with SECRET_FIELDS decrypted. Plaintext legacy values pass through."""
    out = {}
    for key, value in (cfg or {}).items():
        if _is_encrypted(value):
            plain = crypto.decrypt(value[ENC_MARKER])
            value = json.loads(plain) if value.get('$json') else plain
        out[key] = value
    return out


class ConnectorTask(db.Model):
    """A sync with one external service."""
    __tablename__ = 'connector_tasks'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    service = db.Column(db.String(100), nullable=False)  # key of CONNECTOR_SERVICES
    auth_config = db.Column(db.JSON)
    enabled = db.Column(db.Boolean, default=True)
    polling_interval = db.Column(db.Integer, default=3600)  # seconds
    last_run = db.Column(db.DateTime, nullable=True)
    next_run = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default='idle')  # idle | running | error
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    subtasks = db.relationship('ConnectorSubtask', backref='task', lazy=True,
                               cascade='all, delete-orphan')

    @property
    def service_label(self):
        return CONNECTOR_SERVICES.get(self.service, self.service)

    @property
    def credentials(self):
        """auth_config with secrets decrypted. Never render or log this."""
        return decrypt_auth_config(self.auth_config)

    def set_credentials(self, cfg):
        """Store ``cfg`` (plaintext secrets allowed) with its secrets encrypted."""
        self.auth_config = encrypt_auth_config(cfg)
        flag_modified(self, 'auth_config')

    def __repr__(self):
        return f'<ConnectorTask {self.name}>'


class ConnectorSubtask(db.Model):
    """One endpoint fetched by a task, e.g. "Fetch Users"."""
    __tablename__ = 'connector_subtasks'

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('connector_tasks.id'), nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    endpoint = db.Column(db.String(500), nullable=False)
    method = db.Column(db.String(10), default='GET')
    pagination_type = db.Column(db.String(50))
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: now())

    reports = db.relationship('ConnectorReport', backref='subtask', lazy=True,
                              cascade='all, delete-orphan')

    def __repr__(self):
        return f'<ConnectorSubtask {self.name}>'


class ConnectorReport(db.Model):
    """The JSON fetched by one run of a subtask, kept for history and diffs."""
    __tablename__ = 'connector_reports'

    id = db.Column(db.Integer, primary_key=True)
    subtask_id = db.Column(db.Integer, db.ForeignKey('connector_subtasks.id'), nullable=False, index=True)
    data = db.Column(db.Text, nullable=False)  # serialized JSON
    checksum = db.Column(db.String(64))  # SHA256, for quick change detection
    record_count = db.Column(db.Integer, default=0)
    fetch_duration_ms = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=lambda: now())

    @property
    def name(self):
        """Human label used wherever a report is picked from a list (e.g. UAR sources)."""
        subtask = self.subtask
        if subtask is None:
            return f'Report #{self.id}'
        return f'{subtask.task.name} / {subtask.name}'

    def __repr__(self):
        return f'<ConnectorReport {self.id} for Subtask {self.subtask_id}>'
