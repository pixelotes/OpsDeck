"""
Compliance Drift Detection Service

Monitors compliance status changes over time, detects regressions,
and provides drift analysis for compliance frameworks.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import desc
from flask import current_app, url_for
from ..extensions import db
from ..models.security import Framework
from ..models.audits import ComplianceAudit
from ..models.communications import EmailTemplate, ScheduledCommunication
from ..models.auth import User
from ..services.compliance_service import get_compliance_evaluator
from src.utils.timezone_helper import now



class ComplianceDrift:
    """Represents a detected compliance drift/regression."""

    def __init__(
        self,
        control_id: int,
        control_name: str,
        framework_name: str,
        old_status: str,
        new_status: str,
        timestamp: datetime,
        changes: Dict[str, Any]
    ):
        self.control_id = control_id
        self.control_name = control_name
        self.framework_name = framework_name
        self.old_status = old_status
        self.new_status = new_status
        self.timestamp = timestamp
        self.changes = changes

    @property
    def is_regression(self) -> bool:
        """Check if this drift represents a regression (worse compliance)."""
        status_severity = {
            'compliant': 0,
            'manual': 1,
            'warning': 2,
            'non_compliant': 3,
            'uncovered': 4
        }

        old_severity = status_severity.get(self.old_status, 99)
        new_severity = status_severity.get(self.new_status, 99)

        return new_severity > old_severity

    @property
    def severity(self) -> str:
        """Get drift severity level."""
        if self.is_regression:
            if self.new_status == 'non_compliant':
                return 'critical'
            elif self.new_status == 'warning':
                return 'high'
            else:
                return 'medium'
        else:
            return 'low'  # Improvement

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            'control_id': self.control_id,
            'control_name': self.control_name,
            'framework_name': self.framework_name,
            'old_status': self.old_status,
            'new_status': self.new_status,
            'is_regression': self.is_regression,
            'severity': self.severity,
            'timestamp': self.timestamp.isoformat(),
            'changes': self.changes
        }


class ComplianceDriftDetector:
    """
    Detects and analyzes compliance drift by comparing compliance snapshots over time.
    """

    def __init__(self):
        self.evaluator = get_compliance_evaluator()

    def capture_snapshot(self, framework_id: Optional[int] = None) -> ComplianceAudit:
        """
        Capture a compliance snapshot for all frameworks or a specific framework.

        Args:
            framework_id: Optional framework ID to snapshot (None = all frameworks)

        Returns:
            ComplianceAudit instance
        """
        if framework_id:
            frameworks = [db.session.get(Framework, framework_id)]
            if not frameworks[0]:
                raise ValueError(f"Framework {framework_id} not found")
        else:
            frameworks = Framework.query.filter_by(is_active=True).all()

        # Build snapshot data
        snapshot_data = {
            'timestamp': now().isoformat(),
            'frameworks': {}
        }

        for framework in frameworks:
            framework_status = self.evaluator.get_framework_status(framework.id)
            if framework_status:
                snapshot_data['frameworks'][framework.id] = {
                    'name': framework.name,
                    'stats': framework_status['stats'],
                    'controls': {}
                }

                # Store individual control statuses
                for control in framework_status['controls']:
                    snapshot_data['frameworks'][framework.id]['controls'][control['id']] = {
                        'control_id': control['control_id'],
                        'name': control['name'],
                        'status': control['status'],
                        'rules_count': control['rules_count'],
                        'oldest_evidence_date': control['oldest_evidence_date'].isoformat()
                        if control['oldest_evidence_date'] else None
                    }

        # Create ComplianceAudit record
        audit = ComplianceAudit(
            audit_type='drift_snapshot',
            snapshot_data=snapshot_data,
            created_at=now()
        )

        db.session.add(audit)
        db.session.commit()

        current_app.logger.info(
            f"[Drift] Captured compliance snapshot: "
            f"{len(snapshot_data['frameworks'])} frameworks, audit ID {audit.id}"
        )

        return audit

    def detect_drift(
        self,
        framework_id: Optional[int] = None,
        lookback_hours: int = 24
    ) -> List[ComplianceDrift]:
        """
        Detect compliance drift by comparing current state with previous snapshot.

        Args:
            framework_id: Optional framework ID to check (None = all frameworks)
            lookback_hours: Hours to look back for previous snapshot

        Returns:
            List of detected drifts
        """
        # Get current snapshot
        current_snapshot = self.capture_snapshot(framework_id)

        # Get previous snapshot
        threshold_date = now() - timedelta(hours=lookback_hours)
        previous_audit = ComplianceAudit.query.filter(
            ComplianceAudit.audit_type == 'drift_snapshot',
            ComplianceAudit.created_at >= threshold_date,
            ComplianceAudit.id != current_snapshot.id
        ).order_by(desc(ComplianceAudit.created_at)).first()

        if not previous_audit:
            current_app.logger.info(
                "[Drift] No previous snapshot found for comparison"
            )
            return []

        # Compare snapshots
        drifts = self._compare_snapshots(
            previous_audit.snapshot_data,
            current_snapshot.snapshot_data
        )

        current_app.logger.info(
            f"[Drift] Detected {len(drifts)} changes "
            f"({sum(1 for d in drifts if d.is_regression)} regressions)"
        )

        return drifts

    def _compare_snapshots(
        self,
        old_snapshot: Dict[str, Any],
        new_snapshot: Dict[str, Any]
    ) -> List[ComplianceDrift]:
        """
        Compare two compliance snapshots and identify drifts.

        Args:
            old_snapshot: Previous snapshot data
            new_snapshot: Current snapshot data

        Returns:
            List of ComplianceDrift objects
        """
        drifts = []
        timestamp = now()

        # Compare each framework
        for framework_id_str, new_framework_data in new_snapshot['frameworks'].items():

            # Check if framework existed in old snapshot
            old_framework_data = old_snapshot['frameworks'].get(framework_id_str)
            if not old_framework_data:
                continue  # New framework, skip

            framework_name = new_framework_data['name']

            # Compare each control
            for control_id_str, new_control in new_framework_data['controls'].items():
                control_id = int(control_id_str)

                old_control = old_framework_data['controls'].get(control_id_str)
                if not old_control:
                    continue  # New control, skip

                # Check for status change
                old_status = old_control['status']
                new_status = new_control['status']

                if old_status != new_status:
                    # Drift detected!
                    changes = {
                        'status_change': f"{old_status} → {new_status}",
                        'rules_count': new_control['rules_count'],
                        'old_evidence_date': old_control.get('oldest_evidence_date'),
                        'new_evidence_date': new_control.get('oldest_evidence_date')
                    }

                    drift = ComplianceDrift(
                        control_id=control_id,
                        control_name=new_control['name'],
                        framework_name=framework_name,
                        old_status=old_status,
                        new_status=new_status,
                        timestamp=timestamp,
                        changes=changes
                    )

                    drifts.append(drift)

        return drifts

    def get_drift_timeline(
        self,
        framework_id: int,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get compliance drift timeline for a framework.

        Args:
            framework_id: Framework ID
            days: Number of days to look back

        Returns:
            Timeline data with drift events
        """
        threshold_date = now() - timedelta(days=days)

        # Get all snapshots for the period
        snapshots = ComplianceAudit.query.filter(
            ComplianceAudit.audit_type == 'drift_snapshot',
            ComplianceAudit.created_at >= threshold_date
        ).order_by(ComplianceAudit.created_at).all()

        if len(snapshots) < 2:
            return {
                'framework_id': framework_id,
                'timeline': [],
                'message': 'Not enough snapshots for drift analysis'
            }

        # Build timeline by comparing consecutive snapshots
        timeline = []
        for i in range(1, len(snapshots)):
            previous = snapshots[i - 1]
            current = snapshots[i]

            drifts = self._compare_snapshots(
                previous.snapshot_data,
                current.snapshot_data
            )

            # Filter for this framework
            framework_drifts = [
                d for d in drifts
                if self._is_framework_drift(d, framework_id, current.snapshot_data)
            ]

            if framework_drifts:
                timeline.append({
                    'timestamp': current.created_at.isoformat(),
                    'snapshot_id': current.id,
                    'drifts': [d.to_dict() for d in framework_drifts],
                    'regression_count': sum(1 for d in framework_drifts if d.is_regression),
                    'improvement_count': sum(1 for d in framework_drifts if not d.is_regression)
                })

        # Calculate statistics
        total_regressions = sum(event['regression_count'] for event in timeline)
        total_improvements = sum(event['improvement_count'] for event in timeline)

        return {
            'framework_id': framework_id,
            'period_days': days,
            'snapshot_count': len(snapshots),
            'timeline': timeline,
            'statistics': {
                'total_regressions': total_regressions,
                'total_improvements': total_improvements,
                'net_change': total_improvements - total_regressions
            }
        }

    def _is_framework_drift(
        self,
        drift: ComplianceDrift,
        framework_id: int,
        snapshot_data: Dict[str, Any]
    ) -> bool:
        """Check if drift belongs to specified framework."""
        framework_id_str = str(framework_id)
        if framework_id_str not in snapshot_data['frameworks']:
            return False

        framework_data = snapshot_data['frameworks'][framework_id_str]
        return drift.framework_name == framework_data['name']

    def generate_drift_alert(self, drifts: List[ComplianceDrift]) -> Dict[str, Any]:
        """
        Generate alert data for detected drifts.

        Args:
            drifts: List of detected drifts

        Returns:
            Alert data dictionary
        """
        regressions = [d for d in drifts if d.is_regression]

        if not regressions:
            return None

        # Group by severity
        critical = [d for d in regressions if d.severity == 'critical']
        high = [d for d in regressions if d.severity == 'high']
        medium = [d for d in regressions if d.severity == 'medium']

        alert = {
            'timestamp': now().isoformat(),
            'total_regressions': len(regressions),
            'by_severity': {
                'critical': len(critical),
                'high': len(high),
                'medium': len(medium)
            },
            'critical_drifts': [d.to_dict() for d in critical[:5]],  # Top 5
            'high_drifts': [d.to_dict() for d in high[:5]],
            'summary': self._generate_alert_summary(regressions)
        }

        return alert

    def _generate_alert_summary(self, regressions: List[ComplianceDrift]) -> str:
        """Generate human-readable alert summary."""
        if not regressions:
            return "No compliance regressions detected"

        critical_count = sum(1 for d in regressions if d.severity == 'critical')

        if critical_count > 0:
            return (
                f"CRITICAL: {critical_count} compliance control(s) regressed to non-compliant status. "
                f"Total regressions: {len(regressions)}. Immediate attention required."
            )
        else:
            return (
                f"WARNING: {len(regressions)} compliance control(s) show degradation. "
                "Review required to prevent non-compliance."
            )

    def send_drift_notifications(self, alert: Dict[str, Any]) -> None:
        """
        Send email notifications for detected compliance drift.

        Args:
            alert: Alert data dictionary from generate_drift_alert
        """
        template = EmailTemplate.query.filter_by(
            name='Compliance Drift Alert - Regressions Detected'
        ).first()

        if not template:
            current_app.logger.warning(
                "[Drift] Email template 'Compliance Drift Alert - Regressions Detected' not found"
            )
            return

        # Get all admin users to notify
        admin_users = User.query.filter_by(role='admin').all()

        if not admin_users:
            current_app.logger.warning("[Drift] No admin users found to notify")
            return

        # Calculate next scan time (daily at 9:00 AM UTC)
        current_time = now()
        next_scan = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
        if next_scan <= current_time:
            next_scan += timedelta(days=1)

        # Prepare context for email template
        context = {
            'regression_count': alert['total_regressions'],
            'total_changes': alert['total_regressions'] + len(alert.get('improvements', [])),
            'improvement_count': len(alert.get('improvements', [])),
            'detection_time': now().strftime('%Y-%m-%d %H:%M UTC'),
            'critical_drifts': alert.get('critical_drifts', []),
            'high_drifts': alert.get('high_drifts', []),
            'dashboard_url': url_for('compliance.drift_dashboard', _external=True),
            'next_scan_time': next_scan.strftime('%Y-%m-%d %H:%M UTC')
        }

        # Send notification to each admin
        for admin in admin_users:
            comm = ScheduledCommunication(
                template_id=template.id,
                recipient_type='email',
                recipient_value=admin.email,
                context=context,
                status='pending',
                send_at=now()  # Send immediately
            )
            db.session.add(comm)

        db.session.commit()

        current_app.logger.info(
            f"[Drift] Queued {len(admin_users)} drift alert notification(s)"
        )


# Singleton instance
_drift_detector = None


def get_drift_detector() -> ComplianceDriftDetector:
    """Get singleton instance of ComplianceDriftDetector."""
    global _drift_detector
    if _drift_detector is None:
        _drift_detector = ComplianceDriftDetector()
    return _drift_detector


def run_drift_detection(app):
    """
    Scheduled job to detect compliance drift.

    This function is called by APScheduler daily.

    Args:
        app: Flask application instance
    """
    with app.app_context():
        detector = get_drift_detector()

        try:
            current_app.logger.info("[Drift] Starting daily drift detection")

            # Detect drift for all frameworks
            drifts = detector.detect_drift(lookback_hours=24)

            if drifts:
                # Generate alert if regressions found
                alert = detector.generate_drift_alert(drifts)

                if alert:
                    current_app.logger.warning(
                        f"[Drift] {alert['summary']}"
                    )

                    # Send email notifications to admins
                    try:
                        detector.send_drift_notifications(alert)
                        current_app.logger.info("[Drift] Drift alert notifications sent")
                    except Exception as e:
                        current_app.logger.error(
                            f"[Drift] Failed to send notifications: {e}",
                            exc_info=True
                        )

            current_app.logger.info("[Drift] Daily drift detection completed")

        except Exception as e:
            current_app.logger.error(f"[Drift] Detection failed: {e}", exc_info=True)
