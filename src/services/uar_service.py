"""
UAR Automation Service

Handles execution of automated User Access Review comparisons,
alert processing, and incident creation.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from flask import current_app, url_for, Flask
from ..extensions import db
from ..models.uar import UARComparison, UARExecution, UARFinding
from ..models.auth import User
from ..models.security import SecurityIncident
from ..models.procurement import Subscription
from ..models.services import BusinessService
from ..models.communications import ScheduledCommunication, EmailTemplate
from ..utils.uar_engine import AccessReviewEngine
from src.utils.timezone_helper import now



class UARAutomationService:
    """
    Service class for executing automated User Access Reviews.
    """

    def execute_comparison(self, comparison: UARComparison) -> UARExecution:
        """
        Execute a UAR comparison and return the execution record.

        Args:
            comparison: UARComparison instance to execute

        Returns:
            UARExecution instance with results

        Raises:
            Exception: If execution fails
        """
        # Create execution record
        execution = UARExecution(
            comparison_id=comparison.id,
            status='running',
            started_at=now()
        )
        db.session.add(execution)
        db.session.flush()  # Get execution.id

        try:
            current_app.logger.info(f"[UAR] Starting execution {execution.id} for comparison '{comparison.name}'")

            # Initialize UAR engine
            engine = AccessReviewEngine()

            # Load Dataset A
            current_app.logger.info(f"[UAR] Loading dataset A: {comparison.source_a_type}")
            data_a = self._load_dataset(
                engine, 'dataset_a',
                comparison.source_a_type,
                comparison.source_a_config or {}
            )

            # Load Dataset B
            current_app.logger.info(f"[UAR] Loading dataset B: {comparison.source_b_type}")
            data_b = self._load_dataset(
                engine, 'dataset_b',
                comparison.source_b_type,
                comparison.source_b_config or {}
            )

            # Capture snapshots
            execution.source_a_snapshot = self._create_snapshot(data_a, 'Dataset A')
            execution.source_b_snapshot = self._create_snapshot(data_b, 'Dataset B')

            current_app.logger.info(
                f"[UAR] Loaded {execution.source_a_snapshot['row_count']} rows in A, "
                f"{execution.source_b_snapshot['row_count']} rows in B"
            )

            # Execute comparison
            current_app.logger.info(f"[UAR] Performing comparison with key fields: {comparison.key_field_a} <=> {comparison.key_field_b}")
            results = engine.perform_structured_comparison(
                key_field_a=comparison.key_field_a,
                key_field_b=comparison.key_field_b,
                field_mappings=comparison.field_mappings or []
            )

            current_app.logger.info(f"[UAR] Comparison completed: {len(results)} findings")

            # Create findings
            self._create_findings(execution, results, comparison)

            # Update execution summary
            execution.findings_count = len(results)
            execution.left_only_count = len([r for r in results if r['finding_type'] == 'Left Only (A)'])
            execution.right_only_count = len([r for r in results if r['finding_type'] == 'Right Only (B)'])
            execution.mismatch_count = len([r for r in results if r['finding_type'] == 'Mismatch'])
            execution.status = 'completed'
            execution.completed_at = now()

            # Handle alerts
            self._handle_alerts(comparison, execution)

            # Update comparison metadata
            comparison.last_run_at = now()
            if comparison.schedule_type != 'manual':
                comparison.next_run_at = self._calculate_next_run(comparison)

            db.session.commit()

            current_app.logger.info(
                f"[UAR] Execution {execution.id} completed successfully: "
                f"{execution.findings_count} findings "
                f"(Left: {execution.left_only_count}, Right: {execution.right_only_count}, Mismatch: {execution.mismatch_count})"
            )

            # Cleanup engine
            engine.cleanup()

            return execution

        except Exception as e:
            execution.status = 'failed'
            execution.error_message = str(e)
            execution.completed_at = now()
            db.session.commit()
            current_app.logger.error(f"[UAR] Execution {execution.id} failed: {e}", exc_info=True)
            raise

    def _load_dataset(
        self,
        engine: AccessReviewEngine,
        table_name: str,
        source_type: str,
        source_config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Load data from various sources into the UAR engine.

        Args:
            engine: AccessReviewEngine instance
            table_name: Target table name ('dataset_a' or 'dataset_b')
            source_type: Type of data source
            source_config: Configuration dict for the source

        Returns:
            list: Loaded data rows
        """
        if source_type == 'Active Users':
            data = self._load_active_users()

        elif source_type == 'Subscription':
            subscription_id = source_config.get('subscription_id')
            if not subscription_id:
                raise ValueError("subscription_id is required for Subscription source")
            subscription = db.session.get(Subscription, subscription_id)
            if not subscription:
                raise ValueError(f"Subscription {subscription_id} not found")

            data = []
            for user in subscription.users:
                for license in [l for l in subscription.licenses if l.user_id == user.id]:
                    data.append({
                        'user_id': user.id,
                        'email': user.email,
                        'name': user.name,
                        'subscription_name': subscription.name,
                        'license_key': license.license_key
                    })

        elif source_type == 'Business Service':
            service_id = source_config.get('service_id')
            if not service_id:
                raise ValueError("service_id is required for Business Service source")
            service = db.session.get(BusinessService, service_id)
            if not service:
                raise ValueError(f"Business Service {service_id} not found")

            # get_effective_users() returns dicts: {'user': User, 'source': str, 'ref': object}
            access_list = service.get_effective_users()
            data = [{
                'user_id': access['user'].id,
                'email': access['user'].email,
                'name': access['user'].name,
                'source': access['source'],
                'service_name': service.name
            } for access in access_list]

        elif source_type == 'Database Query':
            query = source_config.get('query')
            if not query:
                raise ValueError("query is required for Database Query source")
            data = self._validate_and_execute_query(query)

        elif source_type == 'JSON':
            json_data = source_config.get('json_data')
            if not json_data:
                raise ValueError("json_data is required for JSON source")
            data = json_data if isinstance(json_data, list) else []

        elif source_type == 'Enterprise Report':
            report_id = source_config.get('report_id')
            if not report_id:
                raise ValueError("report_id is required for Enterprise Report source")

            # load_from_report resolves the report, raises if it does not exist, and
            # loads it into the engine itself, so there is nothing to fetch here. This
            # used to look up the Report and pass the object as the table name, one
            # argument short — a TypeError, which is to say this source never once ran.
            try:
                return engine.load_from_report(table_name, report_id)
            except ImportError:
                raise ValueError("OpsDeck Enterprise plugin not available")

        else:
            raise ValueError(f"Unknown source type: {source_type}")

        # Load data into engine
        engine.load_dataset(table_name, data)
        return data

    def _load_active_users(self) -> List[Dict[str, Any]]:
        """Load active users from database (similar to compliance.py)."""
        users = User.query.filter_by(is_archived=False).all()
        data = []
        for user in users:
            row = {
                'id': user.id,
                'name': user.name,
                'email': user.email,
                'role': user.role
            }

            # Add custom properties if exists
            if hasattr(user, '_custom_properties'):
                for key, value in (user._custom_properties or {}).items():
                    row[f'custom_field_{key}'] = value

            data.append(row)

        return data

    def _validate_and_execute_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Validate and execute a SQL query.

        Args:
            query: SQL query string

        Returns:
            list: Query results as list of dicts

        Raises:
            ValueError: If query is invalid or forbidden
        """
        query_normalized = query.strip().upper()

        # Security validation
        if not query_normalized.startswith('SELECT'):
            raise ValueError("Only SELECT queries are allowed")

        dangerous_keywords = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE',
            'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE'
        ]
        for keyword in dangerous_keywords:
            if keyword in query_normalized:
                raise ValueError(f"Query contains forbidden keyword: {keyword}")

        # Execute query
        result = db.session.execute(db.text(query))
        rows = result.fetchall()

        if rows:
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]

        return []

    def _create_snapshot(self, data: List[Dict[str, Any]], label: str) -> Dict[str, Any]:
        """Create a snapshot of loaded data for audit trail."""
        if not data:
            return {"columns": [], "row_count": 0, "sample": []}

        columns = list(data[0].keys()) if data else []
        return {
            "columns": columns,
            "row_count": len(data),
            "sample": data[:10]  # First 10 rows
        }

    def _create_findings(
        self,
        execution: UARExecution,
        results: List[Dict[str, Any]],
        comparison: UARComparison
    ) -> None:
        """
        Convert comparison results to UARFinding records with deduplication.

        Deduplication logic:
        - Checks for existing open/acknowledged findings with same comparison, key, and type
        - If found, updates the existing finding and links it to the new execution
        - If not found, creates a new finding
        - Auto-resolves findings from previous execution that are no longer present

        Args:
            execution: UARExecution instance
            results: List of comparison result dicts
            comparison: UARComparison instance
        """
        # Get the previous execution for this comparison
        previous_execution = UARExecution.query.filter(
            UARExecution.comparison_id == comparison.id,
            UARExecution.id != execution.id,
            UARExecution.status == 'completed'
        ).order_by(UARExecution.completed_at.desc()).first()

        # Track which findings are still present in current execution
        current_finding_keys = set()

        for result in results:
            severity = self._calculate_severity(result['finding_type'], comparison)
            key_value = result['key']
            finding_type = result['finding_type']

            current_finding_keys.add((key_value, finding_type))

            # Check if this finding already exists in previous executions
            existing_finding = self._find_existing_finding(
                comparison.id,
                key_value,
                finding_type
            )

            if existing_finding:
                # Update existing finding
                current_app.logger.debug(
                    f"[UAR] Updating existing finding {existing_finding.id}: {key_value}"
                )
                existing_finding.execution_id = execution.id  # Link to new execution
                existing_finding.severity = severity
                existing_finding.description = result['status']
                existing_finding.raw_data_a = self._extract_row_data(result, 'a_')
                existing_finding.raw_data_b = self._extract_row_data(result, 'b_')
                existing_finding.differences = self._extract_differences(result) if finding_type == 'Mismatch' else None
                existing_finding.last_seen_at = now()
                # Keep status unless it was resolved/false_positive
                if existing_finding.status in ['resolved', 'false_positive']:
                    existing_finding.status = 'open'  # Reopen if issue returned
            else:
                # Create new finding
                current_app.logger.debug(
                    f"[UAR] Creating new finding: {key_value}"
                )
                finding = UARFinding(
                    execution_id=execution.id,
                    finding_type=finding_type,
                    severity=severity,
                    key_value=key_value,
                    description=result['status'],
                    raw_data_a=self._extract_row_data(result, 'a_'),
                    raw_data_b=self._extract_row_data(result, 'b_'),
                    differences=self._extract_differences(result) if finding_type == 'Mismatch' else None,
                    status='open',
                    first_seen_at=now(),
                    last_seen_at=now()
                )

                # Try to link to affected user
                if comparison.key_field_a == 'email' or comparison.key_field_b == 'email':
                    user = User.query.filter_by(email=result['key']).first()
                    if user:
                        finding.affected_entity_type = 'user'
                        finding.affected_entity_id = user.id

                db.session.add(finding)

        # Auto-resolve findings from previous execution that are no longer present
        if previous_execution:
            self._auto_resolve_missing_findings(
                previous_execution,
                current_finding_keys,
                execution
            )

    def _find_existing_finding(
        self,
        comparison_id: int,
        key_value: str,
        finding_type: str
    ) -> Optional[UARFinding]:
        """
        Find an existing open/acknowledged finding for deduplication.

        Args:
            comparison_id: UARComparison ID
            key_value: The key value to match
            finding_type: The finding type to match

        Returns:
            UARFinding or None
        """
        # Find the most recent finding with matching key and type
        # that is still open or acknowledged (not resolved/false_positive)
        return UARFinding.query.join(UARExecution).filter(
            UARExecution.comparison_id == comparison_id,
            UARFinding.key_value == key_value,
            UARFinding.finding_type == finding_type,
            UARFinding.status.in_(['open', 'acknowledged'])
        ).order_by(UARFinding.last_seen_at.desc()).first()

    def _auto_resolve_missing_findings(
        self,
        previous_execution: UARExecution,
        current_finding_keys: set,
        current_execution: UARExecution
    ) -> None:
        """
        Auto-resolve findings from previous execution that are no longer present.

        Args:
            previous_execution: Previous UARExecution instance
            current_finding_keys: Set of (key_value, finding_type) tuples from current execution
            current_execution: Current UARExecution instance
        """
        previous_findings = UARFinding.query.filter_by(
            execution_id=previous_execution.id,
            status='open'
        ).all()

        resolved_count = 0
        for finding in previous_findings:
            finding_key = (finding.key_value, finding.finding_type)
            if finding_key not in current_finding_keys:
                # Finding no longer present, auto-resolve
                finding.status = 'resolved'
                finding.resolution_notes = (
                    f"Auto-resolved: No longer detected in execution {current_execution.id} "
                    f"on {current_execution.started_at.strftime('%Y-%m-%d %H:%M UTC')}"
                )
                finding.resolved_at = now()
                resolved_count += 1

        if resolved_count > 0:
            current_app.logger.info(
                f"[UAR] Auto-resolved {resolved_count} findings that are no longer present"
            )

    def _extract_row_data(self, result: Dict[str, Any], prefix: str) -> Optional[Dict[str, Any]]:
        """Extract row data from result dict based on prefix."""
        row_data = {}
        for key, value in result.items():
            if key.startswith(prefix):
                clean_key = key[len(prefix):]  # Remove prefix
                row_data[clean_key] = value
        return row_data if row_data else None

    def _extract_differences(self, result: Dict[str, Any]) -> Optional[List[Dict[str, str]]]:
        """Extract field differences for mismatch findings."""
        # Parse the status message to extract differences
        # Example status: "A.role='user' ≠ B.role='admin', A.department='IT' ≠ B.department='Sales'"
        differences = []
        status = result.get('status', '')

        # This is a simplified extraction; in production, the status format
        # should be more structured or differences should be passed separately
        # For now, we'll just return the status as a single difference
        if '≠' in status or '!=' in status:
            differences.append({
                "description": status
            })

        return differences if differences else None

    def _calculate_severity(self, finding_type: str, comparison: UARComparison) -> str:
        """
        Assign severity based on finding type.

        Args:
            finding_type: Type of finding
            comparison: UARComparison instance

        Returns:
            str: Severity level
        """
        if finding_type == 'Right Only (B)':
            return 'critical'  # Unauthorized user in target system
        elif finding_type == 'Left Only (A)':
            return 'high'  # Missing access provisioning
        elif finding_type == 'Mismatch':
            return 'medium'  # Attribute differences
        else:
            return 'low'

    def _calculate_next_run(self, comparison: UARComparison) -> Optional[datetime]:
        """
        Calculate next scheduled execution time.

        Args:
            comparison: UARComparison instance

        Returns:
            datetime: Next run time or None for manual
        """
        current_time = now()
        schedule_type = comparison.schedule_type
        schedule_config = comparison.schedule_config or {}

        if schedule_type == 'daily':
            hour = schedule_config.get('hour', 8)
            next_run = current_time.replace(hour=hour, minute=0, second=0, microsecond=0)
            if next_run <= current_time:
                next_run += timedelta(days=1)
            return next_run

        elif schedule_type == 'weekly':
            hour = schedule_config.get('hour', 8)
            day_of_week = schedule_config.get('day_of_week', 1)  # Monday=1

            # Calculate days until next occurrence
            days_ahead = day_of_week - current_time.isoweekday()
            if days_ahead <= 0:  # Target day already happened this week or today
                days_ahead += 7

            next_run = current_time + timedelta(days=days_ahead)
            next_run = next_run.replace(hour=hour, minute=0, second=0, microsecond=0)
            return next_run

        elif schedule_type == 'monthly':
            hour = schedule_config.get('hour', 8)
            day_of_month = schedule_config.get('day_of_month', 1)

            # Start with the first of next month
            if current_time.month == 12:
                next_run = current_time.replace(year=current_time.year + 1, month=1, day=day_of_month, hour=hour, minute=0, second=0, microsecond=0)
            else:
                next_run = current_time.replace(month=current_time.month + 1, day=day_of_month, hour=hour, minute=0, second=0, microsecond=0)

            # If the target day already passed this month, use next month
            if current_time.day >= day_of_month:
                return next_run
            else:
                # Use this month
                return current_time.replace(day=day_of_month, hour=hour, minute=0, second=0, microsecond=0)

        return None  # Manual only

    def _handle_alerts(self, comparison: UARComparison, execution: UARExecution) -> None:
        """
        Send notifications and create incidents based on configuration.

        Args:
            comparison: UARComparison instance
            execution: UARExecution instance
        """
        # Check threshold
        if execution.findings_count < comparison.min_findings_threshold:
            current_app.logger.info(f"[UAR] No alerts: findings ({execution.findings_count}) below threshold ({comparison.min_findings_threshold})")
            return

        # Send notifications
        if comparison.notification_channels and comparison.notification_recipients:
            try:
                self._send_notifications(comparison, execution)
                execution.alerts_sent = True
                execution.alerts_sent_at = now()
                current_app.logger.info(f"[UAR] Alerts sent for execution {execution.id}")
            except Exception as e:
                current_app.logger.error(f"[UAR] Failed to send notifications: {e}", exc_info=True)

        # Auto-create incidents if enabled
        if comparison.auto_create_incidents:
            try:
                incidents_created = self._create_security_incidents(comparison, execution)
                execution.incidents_created = incidents_created
                current_app.logger.info(f"[UAR] Created {incidents_created} security incidents for execution {execution.id}")
            except Exception as e:
                current_app.logger.error(f"[UAR] Failed to create incidents: {e}", exc_info=True)

    def _send_notifications(self, comparison: UARComparison, execution: UARExecution) -> None:
        """
        Queue ScheduledCommunication records for alert notifications.

        Args:
            comparison: UARComparison instance
            execution: UARExecution instance
        """
        template = EmailTemplate.query.filter_by(name='UAR Alert - Findings Detected').first()
        if not template:
            current_app.logger.warning("[UAR] Email template 'UAR Alert - Findings Detected' not found")
            return

        for recipient_config in comparison.notification_recipients:
            context = {
                'comparison_name': comparison.name,
                'findings_count': execution.findings_count,
                'left_only_count': execution.left_only_count,
                'right_only_count': execution.right_only_count,
                'mismatch_count': execution.mismatch_count,
                'execution_url': url_for('compliance.uar_execution_detail', execution_id=execution.id, _external=True),
                'execution_date': execution.started_at.strftime('%Y-%m-%d %H:%M UTC')
            }

            comm = ScheduledCommunication(
                template_id=template.id,
                recipient_type=recipient_config.get('type', 'email'),
                recipient_value=recipient_config.get('value'),
                context=context,
                status='pending',
                send_at=now()  # Send immediately
            )
            db.session.add(comm)

    def _create_security_incidents(self, comparison: UARComparison, execution: UARExecution) -> int:
        """
        Auto-promote critical/high findings to SecurityIncidents.

        Args:
            comparison: UARComparison instance
            execution: UARExecution instance

        Returns:
            int: Number of incidents created
        """
        # Only create incidents for critical/high findings
        findings = UARFinding.query.filter(
            UARFinding.execution_id == execution.id,
            UARFinding.severity.in_(['critical', 'high'])
        ).all()

        incidents_created = 0
        for finding in findings:
            incident = SecurityIncident(
                title=f"Access Violation: {finding.key_value}",
                description=(
                    f"Generated from automated User Access Review: {comparison.name}\n\n"
                    f"Finding Type: {finding.finding_type}\n"
                    f"Severity: {finding.severity}\n"
                    f"Details: {finding.description}\n\n"
                    f"Execution Date: {execution.started_at}\n"
                    f"Comparison Config: {comparison.name}"
                ),
                status='Investigating',
                severity=comparison.auto_incident_severity,
                impact='Moderate',
                source='User Access Review'
            )
            db.session.add(incident)
            db.session.flush()  # Get incident.id
            finding.security_incident_id = incident.id
            incidents_created += 1

        return incidents_created


def run_scheduled_uar_comparisons(app: Flask) -> None:
    """
    Execute all enabled UAR comparisons that are due.

    This function is called by APScheduler.

    Args:
        app: Flask application instance
    """
    with app.app_context():
        current_time = now()

        # Find all enabled comparisons that are due
        comparisons = UARComparison.query.filter(
            UARComparison.is_enabled == True,
            UARComparison.next_run_at <= current_time
        ).all()

        current_app.logger.info(f"[UAR] Found {len(comparisons)} comparisons to execute")

        service = UARAutomationService()

        for comparison in comparisons:
            try:
                current_app.logger.info(f"[UAR] Executing comparison: {comparison.name} (ID: {comparison.id})")
                execution = service.execute_comparison(comparison)
                current_app.logger.info(f"[UAR] Completed execution {execution.id}: {execution.findings_count} findings")

            except Exception as e:
                current_app.logger.error(f"[UAR] Failed to execute comparison {comparison.id}: {e}", exc_info=True)

        db.session.commit()
        current_app.logger.info("[UAR] Scheduled UAR comparisons completed")
