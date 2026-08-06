"""
Tests for Compliance Drift Detection Service
"""
import pytest
from datetime import timedelta
from unittest.mock import patch, MagicMock
from src.utils.timezone_helper import now
from src.extensions import db
from src.models.security import Framework
from src.models.audits import ComplianceAudit
from src.models.communications import EmailTemplate
from src.models.auth import User
from src.services.compliance_drift_service import (
    ComplianceDrift,
    ComplianceDriftDetector,
    get_drift_detector,
    run_drift_detection
)


@pytest.fixture
def drift_detector(app, init_database):
    """Create drift detector instance with mocked evaluator."""
    with app.app_context():
        with patch('src.services.compliance_drift_service.get_compliance_evaluator') as mock_evaluator:
            mock_eval = MagicMock()
            mock_evaluator.return_value = mock_eval
            detector = ComplianceDriftDetector()
            detector.evaluator = mock_eval
            yield detector, mock_eval


@pytest.fixture
def sample_framework(app, init_database):
    """Create a sample framework for testing."""
    with app.app_context():
        framework = Framework(
            name='ISO 27001',
            description='Information Security Management',
            is_active=True
        )
        db.session.add(framework)
        db.session.commit()
        framework_id = framework.id
    return framework_id


@pytest.fixture
def email_template(app, init_database):
    """Create drift alert email template."""
    with app.app_context():
        template = EmailTemplate(
            name='Compliance Drift Alert - Regressions Detected',
            subject='Compliance Drift: {{regression_count}} Regressions',
            body_html='Found {{regression_count}} compliance regressions',
            category='security',
            is_system=True
        )
        db.session.add(template)
        db.session.commit()
        return template


@pytest.fixture
def admin_user(app, init_database):
    """Create admin user for notifications."""
    with app.app_context():
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()
        return admin


def test_compliance_drift_initialization():
    """Test ComplianceDrift object initialization."""
    drift = ComplianceDrift(
        control_id=1,
        control_name='Access Control',
        framework_name='ISO 27001',
        old_status='compliant',
        new_status='non_compliant',
        timestamp=now(),
        changes={'test': 'value'}
    )

    assert drift.control_id == 1
    assert drift.control_name == 'Access Control'
    assert drift.old_status == 'compliant'
    assert drift.new_status == 'non_compliant'


def test_drift_is_regression():
    """Test regression detection logic."""
    # Regression: compliant -> non_compliant
    drift = ComplianceDrift(
        control_id=1,
        control_name='Test',
        framework_name='Test FW',
        old_status='compliant',
        new_status='non_compliant',
        timestamp=now(),
        changes={}
    )
    assert drift.is_regression is True

    # Improvement: non_compliant -> compliant
    drift2 = ComplianceDrift(
        control_id=2,
        control_name='Test',
        framework_name='Test FW',
        old_status='non_compliant',
        new_status='compliant',
        timestamp=now(),
        changes={}
    )
    assert drift2.is_regression is False

    # No change
    drift3 = ComplianceDrift(
        control_id=3,
        control_name='Test',
        framework_name='Test FW',
        old_status='compliant',
        new_status='compliant',
        timestamp=now(),
        changes={}
    )
    assert drift3.is_regression is False


def test_drift_severity_critical():
    """Test severity calculation for critical drift."""
    drift = ComplianceDrift(
        control_id=1,
        control_name='Test',
        framework_name='Test FW',
        old_status='compliant',
        new_status='non_compliant',
        timestamp=now(),
        changes={}
    )
    assert drift.severity == 'critical'


def test_drift_severity_high():
    """Test severity calculation for high drift."""
    drift = ComplianceDrift(
        control_id=1,
        control_name='Test',
        framework_name='Test FW',
        old_status='compliant',
        new_status='warning',
        timestamp=now(),
        changes={}
    )
    assert drift.severity == 'high'


def test_drift_severity_improvement():
    """Test severity for improvement (not regression)."""
    drift = ComplianceDrift(
        control_id=1,
        control_name='Test',
        framework_name='Test FW',
        old_status='non_compliant',
        new_status='compliant',
        timestamp=now(),
        changes={}
    )
    assert drift.severity == 'low'  # Improvements are low severity


def test_drift_to_dict():
    """Test converting drift to dictionary."""
    timestamp = now()
    drift = ComplianceDrift(
        control_id=1,
        control_name='Access Control',
        framework_name='ISO 27001',
        old_status='compliant',
        new_status='warning',
        timestamp=timestamp,
        changes={'test': 'data'}
    )

    result = drift.to_dict()

    assert result['control_id'] == 1
    assert result['control_name'] == 'Access Control'
    assert result['framework_name'] == 'ISO 27001'
    assert result['old_status'] == 'compliant'
    assert result['new_status'] == 'warning'
    assert result['is_regression'] is True
    assert result['severity'] == 'high'
    assert 'timestamp' in result


def test_capture_snapshot(app, drift_detector, sample_framework):
    """Test capturing a compliance snapshot."""
    detector, mock_evaluator = drift_detector
    framework_id = sample_framework

    with app.app_context():
        # Mock framework status
        mock_evaluator.get_framework_status.return_value = {
            'stats': {'compliant': 5, 'non_compliant': 2},
            'controls': [
                {
                    'id': 1,
                    'control_id': 'AC-1',
                    'name': 'Access Control Policy',
                    'status': 'compliant',
                    'rules_count': 3,
                    'oldest_evidence_date': now()
                }
            ]
        }

        # Capture snapshot
        audit = detector.capture_snapshot(framework_id)

        # Verify audit was created
        assert audit is not None
        assert audit.audit_type == 'drift_snapshot'
        assert audit.snapshot_data is not None
        assert 'frameworks' in audit.snapshot_data
        assert str(framework_id) in audit.snapshot_data['frameworks']


def test_capture_snapshot_all_frameworks(app, drift_detector, sample_framework):
    """Test capturing snapshot for all frameworks."""
    detector, mock_evaluator = drift_detector

    with app.app_context():
        mock_evaluator.get_framework_status.return_value = {
            'stats': {'compliant': 5},
            'controls': []
        }

        # Capture snapshot for all frameworks
        audit = detector.capture_snapshot()

        assert audit is not None
        assert audit.audit_type == 'drift_snapshot'


def test_detect_drift_no_previous_snapshot(app, drift_detector, sample_framework):
    """Test drift detection when no previous snapshot exists."""
    detector, mock_evaluator = drift_detector
    framework_id = sample_framework

    with app.app_context():
        mock_evaluator.get_framework_status.return_value = {
            'stats': {'compliant': 5},
            'controls': []
        }

        drifts = detector.detect_drift(framework_id)

        # Should return empty list when no previous snapshot
        assert drifts == []


def test_detect_drift_with_changes(app, drift_detector, sample_framework):
    """Test drift detection with actual status changes."""
    detector, mock_evaluator = drift_detector
    framework_id = sample_framework

    with app.app_context():
        # Create previous snapshot manually
        old_snapshot_data = {
            'timestamp': (now() - timedelta(hours=2)).isoformat(),
            'frameworks': {
                str(framework_id): {
                    'name': 'ISO 27001',
                    'stats': {'compliant': 5},
                    'controls': {
                        '1': {
                            'control_id': 'AC-1',
                            'name': 'Access Control',
                            'status': 'compliant',
                            'rules_count': 3,
                            'oldest_evidence_date': None
                        }
                    }
                }
            }
        }

        old_audit = ComplianceAudit(
            audit_type='drift_snapshot',
            snapshot_data=old_snapshot_data,
            created_at=now() - timedelta(hours=2)
        )
        db.session.add(old_audit)
        db.session.commit()

        # Mock current status (changed)
        mock_evaluator.get_framework_status.return_value = {
            'stats': {'compliant': 4, 'non_compliant': 1},
            'controls': [
                {
                    'id': 1,
                    'control_id': 'AC-1',
                    'name': 'Access Control',
                    'status': 'non_compliant',  # Changed from compliant
                    'rules_count': 3,
                    'oldest_evidence_date': None
                }
            ]
        }

        # Detect drift
        drifts = detector.detect_drift(framework_id)

        # Verify drift was detected
        assert len(drifts) > 0
        assert drifts[0].control_id == 1
        assert drifts[0].old_status == 'compliant'
        assert drifts[0].new_status == 'non_compliant'
        assert drifts[0].is_regression is True


def test_compare_snapshots(app, drift_detector):
    """Test comparing two snapshots."""
    detector, _ = drift_detector

    with app.app_context():
        old_snapshot = {
            'frameworks': {
                '1': {
                    'name': 'Test FW',
                    'controls': {
                        '1': {
                            'name': 'Control 1',
                            'status': 'compliant',
                            'rules_count': 3,
                            'oldest_evidence_date': None
                        },
                        '2': {
                            'name': 'Control 2',
                            'status': 'warning',
                            'rules_count': 2,
                            'oldest_evidence_date': None
                        }
                    }
                }
            }
        }

        new_snapshot = {
            'frameworks': {
                '1': {
                    'name': 'Test FW',
                    'controls': {
                        '1': {
                            'name': 'Control 1',
                            'status': 'non_compliant',  # Changed
                            'rules_count': 3,
                            'oldest_evidence_date': None
                        },
                        '2': {
                            'name': 'Control 2',
                            'status': 'warning',  # Unchanged
                            'rules_count': 2,
                            'oldest_evidence_date': None
                        }
                    }
                }
            }
        }

        drifts = detector._compare_snapshots(old_snapshot, new_snapshot)

        # Should only detect the changed control
        assert len(drifts) == 1
        assert drifts[0].control_id == 1
        assert drifts[0].old_status == 'compliant'
        assert drifts[0].new_status == 'non_compliant'


def test_get_drift_timeline_insufficient_snapshots(app, drift_detector, sample_framework):
    """Test drift timeline when not enough snapshots exist."""
    detector, _ = drift_detector
    framework_id = sample_framework

    with app.app_context():
        timeline = detector.get_drift_timeline(framework_id, days=30)

        assert 'message' in timeline
        assert 'Not enough snapshots' in timeline['message']


def test_get_drift_timeline_with_snapshots(app, drift_detector, sample_framework):
    """Test drift timeline with multiple snapshots."""
    detector, _ = drift_detector
    framework_id = sample_framework

    with app.app_context():
        # Create multiple snapshots
        for i in range(3):
            snapshot = ComplianceAudit(
                audit_type='drift_snapshot',
                snapshot_data={
                    'frameworks': {
                        str(framework_id): {
                            'name': 'Test FW',
                            'controls': {
                                '1': {
                                    'name': 'Control 1',
                                    'status': 'compliant',
                                    'rules_count': 3,
                                    'oldest_evidence_date': None
                                }
                            }
                        }
                    }
                },
                created_at=now() - timedelta(days=i)
            )
            db.session.add(snapshot)
        db.session.commit()

        timeline = detector.get_drift_timeline(framework_id, days=30)

        assert 'timeline' in timeline
        assert timeline['snapshot_count'] == 3


def test_generate_drift_alert_no_regressions(app, drift_detector):
    """Test alert generation with no regressions."""
    detector, _ = drift_detector

    with app.app_context():
        # Only improvements
        drifts = [
            ComplianceDrift(
                control_id=1,
                control_name='Test',
                framework_name='Test FW',
                old_status='non_compliant',
                new_status='compliant',
                timestamp=now(),
                changes={}
            )
        ]

        alert = detector.generate_drift_alert(drifts)

        # Should return None when no regressions
        assert alert is None


def test_generate_drift_alert_with_regressions(app, drift_detector):
    """Test alert generation with regressions."""
    detector, _ = drift_detector

    with app.app_context():
        drifts = [
            ComplianceDrift(
                control_id=1,
                control_name='Critical Control',
                framework_name='ISO 27001',
                old_status='compliant',
                new_status='non_compliant',
                timestamp=now(),
                changes={}
            ),
            ComplianceDrift(
                control_id=2,
                control_name='Warning Control',
                framework_name='ISO 27001',
                old_status='compliant',
                new_status='warning',
                timestamp=now(),
                changes={}
            )
        ]

        alert = detector.generate_drift_alert(drifts)

        assert alert is not None
        assert alert['total_regressions'] == 2
        assert alert['by_severity']['critical'] == 1
        assert alert['by_severity']['high'] == 1
        assert 'summary' in alert


def test_send_drift_notifications_no_template(app, drift_detector, admin_user):
    """Test notification sending when template doesn't exist."""
    detector, _ = drift_detector

    with app.app_context():
        alert = {
            'total_regressions': 5,
            'critical_drifts': [],
            'high_drifts': []
        }

        # Should not raise error, just log warning
        detector.send_drift_notifications(alert)


def test_send_drift_notifications_no_admins(app, drift_detector, email_template):
    """Test notification sending when no admin users exist."""
    detector, _ = drift_detector

    with app.app_context():
        alert = {
            'total_regressions': 5,
            'critical_drifts': [],
            'high_drifts': []
        }

        # Should not raise error, just log warning
        detector.send_drift_notifications(alert)


def test_get_drift_detector_singleton(app, init_database):
    """Test that get_drift_detector returns singleton instance."""
    with app.app_context():
        with patch('src.services.compliance_drift_service.get_compliance_evaluator'):
            detector1 = get_drift_detector()
            detector2 = get_drift_detector()

            assert detector1 is detector2


def test_run_drift_detection_scheduled(app, init_database, sample_framework, email_template, admin_user):
    """Test scheduled drift detection execution."""
    with app.app_context():
        with patch('src.services.compliance_drift_service.get_drift_detector') as mock_get_detector:
            mock_detector = MagicMock()
            mock_detector.detect_drift.return_value = []
            mock_get_detector.return_value = mock_detector

            # Run the scheduled job
            run_drift_detection(app)

            # Verify detector methods were called
            mock_detector.detect_drift.assert_called_once()
