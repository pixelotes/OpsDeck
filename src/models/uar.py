from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC


class UARComparison(db.Model):
    """
    User Access Review Comparison Configuration.

    Defines an automated comparison between two datasets
    with scheduling, alerting, and incident escalation rules.
    """
    __tablename__ = 'uar_comparison'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)

    # Data Source A Configuration
    source_a_type = db.Column(db.String(50), nullable=False)  # 'Active Users', 'Subscription', etc.
    source_a_config = db.Column(db.JSON)  # {"subscription_id": 5, "query": "SELECT...", etc}

    # Data Source B Configuration
    source_b_type = db.Column(db.String(50), nullable=False)
    source_b_config = db.Column(db.JSON)

    # Comparison Configuration
    key_field_a = db.Column(db.String(50), nullable=False)  # Column to match on in dataset A
    key_field_b = db.Column(db.String(50), nullable=False)  # Column to match on in dataset B
    field_mappings = db.Column(db.JSON)  # [{"field_a": "role", "field_b": "permission_level"}]

    # Scheduling Configuration
    schedule_type = db.Column(db.String(20), default='manual')  # 'manual', 'daily', 'weekly', 'monthly'
    schedule_config = db.Column(db.JSON)  # {"hour": 9, "day_of_week": 1}
    last_run_at = db.Column(db.DateTime)
    next_run_at = db.Column(db.DateTime)

    # Alert Configuration
    alert_on_left_only = db.Column(db.Boolean, default=True)
    alert_on_right_only = db.Column(db.Boolean, default=True)
    alert_on_mismatches = db.Column(db.Boolean, default=True)
    min_findings_threshold = db.Column(db.Integer, default=1)
    notification_channels = db.Column(db.JSON)  # ['email', 'slack']
    notification_recipients = db.Column(db.JSON)  # [{"type": "email", "value": "security@company.com"}]

    # Auto-Escalation Configuration
    auto_create_incidents = db.Column(db.Boolean, default=False)
    auto_incident_severity = db.Column(db.String(10), default='SEV-2')

    # Status
    is_enabled = db.Column(db.Boolean, default=True)
    is_archived = db.Column(db.Boolean, default=False)

    # Future AI Integration
    enable_ai_analysis = db.Column(db.Boolean, default=False)
    ai_task_id = db.Column(db.Integer, nullable=True)  # Will be FK to ai_task when implemented

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    # Relationships
    executions = db.relationship('UARExecution', backref='comparison', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)

    def __repr__(self):
        return f'<UARComparison {self.name}>'


class UARExecution(db.Model):
    """
    User Access Review Execution Record.

    Immutable audit trail of each comparison execution with
    results summary and data snapshots.
    """
    __tablename__ = 'uar_execution'

    id = db.Column(db.Integer, primary_key=True)
    comparison_id = db.Column(db.Integer, db.ForeignKey('uar_comparison.id'), nullable=False, index=True)

    # Execution Status
    status = db.Column(db.String(20), default='running')  # 'running', 'completed', 'failed'
    started_at = db.Column(db.DateTime, default=lambda: now())
    completed_at = db.Column(db.DateTime)

    # Data Snapshots (for audit trail)
    source_a_snapshot = db.Column(db.JSON)  # {"columns": [...], "row_count": 1500, "sample": [...]}
    source_b_snapshot = db.Column(db.JSON)

    # Results Summary
    findings_count = db.Column(db.Integer, default=0)
    left_only_count = db.Column(db.Integer, default=0)  # In A but not in B
    right_only_count = db.Column(db.Integer, default=0)  # In B but not in A
    mismatch_count = db.Column(db.Integer, default=0)  # In both but different

    # Notification Status
    alerts_sent = db.Column(db.Boolean, default=False)
    alerts_sent_at = db.Column(db.DateTime)
    incidents_created = db.Column(db.Integer, default=0)

    # Error Handling
    error_message = db.Column(db.Text)

    # Future AI Integration
    enterprise_report_id = db.Column(db.Integer, nullable=True)  # Link to OpsDeck Enterprise Report

    # Relationships
    findings = db.relationship('UARFinding', backref='execution', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)

    def __repr__(self):
        return f'<UARExecution {self.id} - {self.status}>'


class UARFinding(db.Model):
    """
    Individual User Access Review Finding.

    Represents a single discrepancy detected during comparison
    with resolution tracking and incident linking.
    """
    __tablename__ = 'uar_finding'

    id = db.Column(db.Integer, primary_key=True)
    execution_id = db.Column(db.Integer, db.ForeignKey('uar_execution.id'), nullable=False, index=True)

    # Finding Details
    finding_type = db.Column(db.String(20), nullable=False)  # 'Left Only (A)', 'Right Only (B)', 'Mismatch'
    severity = db.Column(db.String(10), default='medium')  # 'critical', 'high', 'medium', 'low', 'info'
    key_value = db.Column(db.String(255))  # The matched key (e.g., 'alice@company.com')
    description = db.Column(db.Text)

    # Raw Data
    raw_data_a = db.Column(db.JSON)  # Full row from dataset A
    raw_data_b = db.Column(db.JSON)  # Full row from dataset B
    differences = db.Column(db.JSON)  # For mismatches: [{"field": "role", "value_a": "user", "value_b": "admin"}]

    # Affected Entity (for linking)
    affected_entity_type = db.Column(db.String(50))  # 'user', 'subscription', 'service'
    affected_entity_id = db.Column(db.Integer)

    # Status & Resolution
    status = db.Column(db.String(20), default='open')  # 'open', 'acknowledged', 'resolved', 'false_positive'
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    resolved_at = db.Column(db.DateTime)
    resolution_notes = db.Column(db.Text)
    security_incident_id = db.Column(db.Integer, db.ForeignKey('security_incident.id'), nullable=True, index=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=lambda: now())
    first_seen_at = db.Column(db.DateTime)  # When this finding first appeared
    last_seen_at = db.Column(db.DateTime)   # When this finding was last detected

    # Relationships
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], backref='assigned_uar_findings')
    security_incident = db.relationship('SecurityIncident', foreign_keys=[security_incident_id])

    def __repr__(self):
        return f'<UARFinding {self.id} - {self.finding_type} - {self.severity}>'
