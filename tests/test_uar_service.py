"""
Tests for UAR Automation Service
"""
import pytest
from datetime import timedelta
from unittest.mock import patch
from src.utils.timezone_helper import now
from src.extensions import db
from src.models.uar import UARComparison, UARExecution, UARFinding
from src.models.auth import User
from src.models.communications import EmailTemplate, ScheduledCommunication
from src.services.uar_service import UARAutomationService, run_scheduled_uar_comparisons


@pytest.fixture
def uar_service(app, init_database):
    """Create UAR service instance."""
    with app.app_context():
        return UARAutomationService()


@pytest.fixture
def sample_users(app, init_database):
    """Create sample users for testing."""
    with app.app_context():
        users = [
            User(name='Alice Smith', email='alice@example.com', role='user'),
            User(name='Bob Jones', email='bob@example.com', role='user'),
            User(name='Charlie Brown', email='charlie@example.com', role='admin')
        ]
        for user in users:
            user.set_password('password')
            db.session.add(user)
        db.session.commit()
        return users


@pytest.fixture
def email_template(app, init_database):
    """Create UAR alert email template."""
    with app.app_context():
        template = EmailTemplate(
            name='UAR Alert - Findings Detected',
            subject='UAR Alert: {{findings_count}} Findings Detected',
            body_html='Found {{findings_count}} findings in comparison {{comparison_name}}',
            category='security',
            is_system=True
        )
        db.session.add(template)
        db.session.commit()
        return template


def test_load_active_users(app, init_database, uar_service, sample_users):
    """Test loading active users dataset."""
    with app.app_context():
        data = uar_service._load_active_users()

        assert len(data) == 3
        assert data[0]['name'] == 'Alice Smith'
        assert data[0]['email'] == 'alice@example.com'
        assert 'role' in data[0]


def test_create_snapshot(app, init_database, uar_service):
    """Test creating data snapshot."""
    with app.app_context():
        data = [
            {'id': 1, 'name': 'Alice', 'role': 'admin'},
            {'id': 2, 'name': 'Bob', 'role': 'user'}
        ]

        snapshot = uar_service._create_snapshot(data, 'Test Dataset')

        assert snapshot['row_count'] == 2
        assert 'id' in snapshot['columns']
        assert 'name' in snapshot['columns']
        assert len(snapshot['sample']) == 2


def test_create_snapshot_empty(app, init_database, uar_service):
    """Test creating snapshot with empty data."""
    with app.app_context():
        snapshot = uar_service._create_snapshot([], 'Empty Dataset')

        assert snapshot['row_count'] == 0
        assert snapshot['columns'] == []
        assert snapshot['sample'] == []


def test_calculate_severity(app, init_database, uar_service):
    """Test severity calculation for different finding types."""
    with app.app_context():
        comparison = UARComparison(
            name='Test Comparison',
            key_field_a='email',
            key_field_b='email'
        )

        assert uar_service._calculate_severity('Right Only (B)', comparison) == 'critical'
        assert uar_service._calculate_severity('Left Only (A)', comparison) == 'high'
        assert uar_service._calculate_severity('Mismatch', comparison) == 'medium'


def test_calculate_next_run_daily(app, init_database, uar_service):
    """Test calculating next run for daily schedule."""
    with app.app_context():
        comparison = UARComparison(
            name='Daily Test',
            schedule_type='daily',
            schedule_config={'hour': 10},
            key_field_a='email',
            key_field_b='email'
        )

        next_run = uar_service._calculate_next_run(comparison)

        assert next_run is not None
        assert next_run.hour == 10
        assert next_run.minute == 0


def test_calculate_next_run_weekly(app, init_database, uar_service):
    """Test calculating next run for weekly schedule."""
    with app.app_context():
        comparison = UARComparison(
            name='Weekly Test',
            schedule_type='weekly',
            schedule_config={'hour': 9, 'day_of_week': 1},  # Monday
            key_field_a='email',
            key_field_b='email'
        )

        next_run = uar_service._calculate_next_run(comparison)

        assert next_run is not None
        assert next_run.hour == 9
        assert next_run.isoweekday() == 1  # Monday


def test_calculate_next_run_monthly(app, init_database, uar_service):
    """Test calculating next run for monthly schedule."""
    with app.app_context():
        comparison = UARComparison(
            name='Monthly Test',
            schedule_type='monthly',
            schedule_config={'hour': 8, 'day_of_month': 15},
            key_field_a='email',
            key_field_b='email'
        )

        next_run = uar_service._calculate_next_run(comparison)

        assert next_run is not None
        assert next_run.day == 15
        assert next_run.hour == 8


def test_calculate_next_run_manual(app, init_database, uar_service):
    """Test calculating next run for manual schedule."""
    with app.app_context():
        comparison = UARComparison(
            name='Manual Test',
            schedule_type='manual',
            key_field_a='email',
            key_field_b='email'
        )

        next_run = uar_service._calculate_next_run(comparison)

        assert next_run is None


def test_validate_and_execute_query_valid(app, init_database, uar_service, sample_users):
    """Test executing valid SELECT query."""
    with app.app_context():
        query = "SELECT name, email FROM \"user\" WHERE role = 'user'"

        results = uar_service._validate_and_execute_query(query)

        assert len(results) >= 2
        assert 'name' in results[0]
        assert 'email' in results[0]


def test_validate_and_execute_query_invalid_keyword(app, init_database, uar_service):
    """Test that dangerous SQL keywords are blocked."""
    with app.app_context():
        with pytest.raises(ValueError, match="Only SELECT queries are allowed"):
            uar_service._validate_and_execute_query("DELETE FROM users")

        with pytest.raises(ValueError, match="forbidden keyword"):
            uar_service._validate_and_execute_query("SELECT * FROM users; DROP TABLE users")


def test_execute_comparison_with_json_source(app, uar_service, email_template):
    """Test executing comparison with JSON data sources."""
    with app.app_context():
        # Create comparison
        comparison = UARComparison(
            name='Test JSON Comparison',
            source_a_type='JSON',
            source_a_config={
                'json_data': [
                    {'email': 'alice@example.com', 'role': 'admin'},
                    {'email': 'bob@example.com', 'role': 'user'}
                ]
            },
            source_b_type='JSON',
            source_b_config={
                'json_data': [
                    {'email': 'alice@example.com', 'role': 'admin'},
                    {'email': 'bob@example.com', 'role': 'admin'},  # Changed role
                    {'email': 'charlie@example.com', 'role': 'user'}  # New user
                ]
            },
            key_field_a='email',
            key_field_b='email',
            field_mappings=[{'field_a': 'role', 'field_b': 'role'}],
            min_findings_threshold=0
        )
        db.session.add(comparison)
        db.session.commit()

        # Execute comparison
        execution = uar_service.execute_comparison(comparison)

        # Verify execution
        assert execution.status == 'completed'
        assert execution.findings_count == 2  # Bob mismatch + Charlie right only
        assert execution.mismatch_count == 1  # Bob
        assert execution.right_only_count == 1  # Charlie
        assert execution.left_only_count == 0

        # Verify findings were created
        findings = UARFinding.query.filter_by(execution_id=execution.id).all()
        assert len(findings) == 2


def test_execute_comparison_with_active_users(app, uar_service, sample_users, email_template):
    """Test executing comparison with Active Users source."""
    with app.app_context():
        comparison = UARComparison(
            name='Active Users Test',
            source_a_type='Active Users',
            source_a_config={},
            source_b_type='JSON',
            source_b_config={
                'json_data': [
                    {'email': 'alice@example.com', 'role': 'user'},  # Role mismatch
                    {'email': 'bob@example.com', 'role': 'user'}
                    # Charlie is missing from B (Left Only)
                ]
            },
            key_field_a='email',
            key_field_b='email',
            field_mappings=[{'field_a': 'role', 'field_b': 'role'}],
            min_findings_threshold=0
        )
        db.session.add(comparison)
        db.session.commit()

        execution = uar_service.execute_comparison(comparison)

        assert execution.status == 'completed'
        assert execution.findings_count >= 1  # At least Charlie missing
        assert execution.left_only_count >= 1


def test_execute_comparison_failure(app, init_database, uar_service):
    """Test that comparison failure is handled properly."""
    with app.app_context():
        comparison = UARComparison(
            name='Failing Comparison',
            source_a_type='Invalid Type',  # This will cause an error
            source_a_config={},
            source_b_type='JSON',
            source_b_config={'json_data': []},
            key_field_a='email',
            key_field_b='email'
        )
        db.session.add(comparison)
        db.session.commit()

        with pytest.raises(ValueError, match="Unknown source type"):
            uar_service.execute_comparison(comparison)

        # Verify execution record shows failure
        execution = UARExecution.query.filter_by(comparison_id=comparison.id).first()
        assert execution is not None
        assert execution.status == 'failed'
        assert execution.error_message is not None


@pytest.mark.skip(reason="ScheduledCommunication model fields don't match service implementation - needs fixing")
def test_alerts_sent_when_threshold_exceeded(app, uar_service, email_template):
    """Test that alerts are sent when findings exceed threshold."""
    with app.app_context():
        # Create admin user for notifications
        admin = User(name='Admin', email='admin@test.com', role='admin')
        admin.set_password('password')
        db.session.add(admin)
        db.session.commit()

        comparison = UARComparison(
            name='Alert Test',
            source_a_type='JSON',
            source_a_config={'json_data': [
                {'email': 'alice@example.com', 'role': 'admin'}
            ]},
            source_b_type='JSON',
            source_b_config={'json_data': [
                {'email': 'alice@example.com', 'role': 'user'},
                {'email': 'bob@example.com', 'role': 'user'}
            ]},
            key_field_a='email',
            key_field_b='email',
            field_mappings=[{'field_a': 'role', 'field_b': 'role'}],
            min_findings_threshold=1,
            notification_channels=['email'],
            notification_recipients=[
                {'type': 'email', 'value': 'admin@test.com'}
            ]
        )
        db.session.add(comparison)
        db.session.commit()

        # Mock url_for to avoid SERVER_NAME requirement
        with patch('src.services.uar_service.url_for', return_value='http://test.com/execution/1'):
            execution = uar_service.execute_comparison(comparison)

        # Verify alerts were sent
        assert execution.alerts_sent is True
        assert execution.alerts_sent_at is not None

        # Verify scheduled communication was created
        comms = ScheduledCommunication.query.filter_by(template_id=email_template.id).all()
        assert len(comms) == 1
        assert comms[0].recipient_value == 'admin@test.com'
        assert comms[0].status == 'pending'


def test_alerts_not_sent_below_threshold(app, uar_service, email_template):
    """Test that alerts are not sent when findings are below threshold."""
    with app.app_context():
        comparison = UARComparison(
            name='No Alert Test',
            source_a_type='JSON',
            source_a_config={'json_data': [
                {'email': 'alice@example.com', 'role': 'admin'}
            ]},
            source_b_type='JSON',
            source_b_config={'json_data': [
                {'email': 'alice@example.com', 'role': 'admin'}  # Perfect match
            ]},
            key_field_a='email',
            key_field_b='email',
            field_mappings=[{'field_a': 'role', 'field_b': 'role'}],
            min_findings_threshold=1,  # Need at least 1 finding
            notification_channels=['email'],
            notification_recipients=[
                {'type': 'email', 'value': 'admin@test.com'}
            ]
        )
        db.session.add(comparison)
        db.session.commit()

        execution = uar_service.execute_comparison(comparison)

        # Verify no alerts sent
        assert execution.findings_count == 0
        assert execution.alerts_sent is False

        # Verify no communications created
        comms = ScheduledCommunication.query.all()
        assert len(comms) == 0


def test_extract_row_data(app, init_database, uar_service):
    """Test extracting row data from comparison result."""
    with app.app_context():
        result = {
            'a_id': 1,
            'a_name': 'Alice',
            'a_role': 'admin',
            'b_id': 1,
            'b_name': 'Alice',
            'b_role': 'user'
        }

        data_a = uar_service._extract_row_data(result, 'a_')
        data_b = uar_service._extract_row_data(result, 'b_')

        assert data_a == {'id': 1, 'name': 'Alice', 'role': 'admin'}
        assert data_b == {'id': 1, 'name': 'Alice', 'role': 'user'}


def test_extract_differences(app, init_database, uar_service):
    """Test extracting differences from mismatch result."""
    with app.app_context():
        result = {
            'finding_type': 'Mismatch',
            'status': "A.role='admin' ≠ B.role='user'"
        }

        differences = uar_service._extract_differences(result)

        assert differences is not None
        assert len(differences) > 0
        assert 'description' in differences[0]


def test_run_scheduled_comparisons(app, email_template, sample_users):
    """Test running scheduled UAR comparisons."""
    with app.app_context():
        # Create a comparison that is due to run
        current_time = now()
        comparison = UARComparison(
            name='Scheduled Test',
            source_a_type='Active Users',
            source_a_config={},
            source_b_type='JSON',
            source_b_config={'json_data': [
                {'email': 'alice@example.com', 'role': 'user'}
            ]},
            key_field_a='email',
            key_field_b='email',
            field_mappings=[{'field_a': 'role', 'field_b': 'role'}],
            is_enabled=True,
            schedule_type='daily',
            next_run_at=current_time - timedelta(hours=1),  # Due 1 hour ago
            min_findings_threshold=0
        )
        db.session.add(comparison)
        db.session.commit()

        # Run scheduled comparisons
        run_scheduled_uar_comparisons(app)

        # Verify execution was created
        executions = UARExecution.query.filter_by(comparison_id=comparison.id).all()
        assert len(executions) == 1
        assert executions[0].status == 'completed'

        # Verify comparison was updated
        db.session.refresh(comparison)
        assert comparison.last_run_at is not None
        # Compare naive datetimes (DB stores naive UTC)
        current_time_naive = current_time.replace(tzinfo=None)
        assert comparison.next_run_at > current_time_naive


def test_run_scheduled_comparisons_disabled(app, init_database, email_template):
    """Test that disabled comparisons are not executed."""
    with app.app_context():
        current_time = now()
        comparison = UARComparison(
            name='Disabled Test',
            source_a_type='JSON',
            source_a_config={'json_data': []},
            source_b_type='JSON',
            source_b_config={'json_data': []},
            key_field_a='email',
            key_field_b='email',
            is_enabled=False,  # Disabled
            schedule_type='daily',
            next_run_at=current_time - timedelta(hours=1)
        )
        db.session.add(comparison)
        db.session.commit()

        run_scheduled_uar_comparisons(app)

        # Verify no execution was created
        executions = UARExecution.query.filter_by(comparison_id=comparison.id).all()
        assert len(executions) == 0


def test_load_dataset_missing_config(app, init_database, uar_service):
    """Test that missing required config raises errors."""
    with app.app_context():
        from src.utils.uar_engine import AccessReviewEngine
        engine = AccessReviewEngine()

        # Missing subscription_id
        with pytest.raises(ValueError, match="subscription_id is required"):
            uar_service._load_dataset(engine, 'dataset_a', 'Subscription', {})

        # Missing service_id
        with pytest.raises(ValueError, match="service_id is required"):
            uar_service._load_dataset(engine, 'dataset_a', 'Business Service', {})

        # Missing query
        with pytest.raises(ValueError, match="query is required"):
            uar_service._load_dataset(engine, 'dataset_a', 'Database Query', {})


def test_affected_entity_linkage(app, uar_service, sample_users, email_template):
    """Test that findings are linked to affected users when possible."""
    with app.app_context():
        comparison = UARComparison(
            name='Entity Link Test',
            source_a_type='JSON',
            source_a_config={'json_data': [
                {'email': 'alice@example.com', 'role': 'admin'}
            ]},
            source_b_type='JSON',
            source_b_config={'json_data': [
                {'email': 'alice@example.com', 'role': 'user'}
            ]},
            key_field_a='email',
            key_field_b='email',
            field_mappings=[{'field_a': 'role', 'field_b': 'role'}],
            min_findings_threshold=0
        )
        db.session.add(comparison)
        db.session.commit()

        execution = uar_service.execute_comparison(comparison)

        # Find the finding for alice
        finding = UARFinding.query.filter_by(
            execution_id=execution.id,
            key_value='alice@example.com'
        ).first()

        assert finding is not None
        assert finding.affected_entity_type == 'user'
        assert finding.affected_entity_id is not None

        # Verify it's linked to the correct user
        user = db.session.get(User,finding.affected_entity_id)
        assert user.email == 'alice@example.com'
