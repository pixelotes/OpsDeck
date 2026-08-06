"""
Compliance Service - Evaluation Engine

Provides automated compliance checking by evaluating ComplianceRules
against target models (ActivityExecution, Campaign, MaintenanceLog,
BCDRTestLog, OnboardingProcess, OffboardingProcess, SecurityAssessment,
RiskAssessment, UARExecution) and calculating SLA-based traffic-light status.
"""
from typing import Dict, List, Any, Optional, Tuple
from datetime import date, datetime, timedelta
from src.utils.timezone_helper import now, naive_to_aware
from src.extensions import db



class ComplianceEvaluator:
    """
    Evaluates ComplianceRule instances against their target models
    to determine compliance status (Green/Yellow/Red).
    """
    
    def evaluate_rule(self, rule: Any) -> Dict[str, Any]:
        """
        Evaluate a single ComplianceRule.

        Args:
            rule: ComplianceRule instance

        Returns:
            dict with keys:
                - status: "compliant" | "warning" | "non_compliant" | "unknown"
                - last_evidence_date: datetime | None
                - days_since: int (days since last evidence, -1 if none)
                - evidence: object (the evidence instance) | None
                - next_due_date: datetime (calculated deadline)
        """
        if not rule or not rule.enabled:
            return self._unknown_result("Rule is disabled or invalid")
        
        try:
            # Dispatch based on target_model
            target_model = rule.target_model
            
            if target_model == 'ActivityExecution':
                evidence, evidence_date = self._evaluate_activity_execution(rule)
            elif target_model == 'Campaign':
                evidence, evidence_date = self._evaluate_campaign(rule)
            elif target_model == 'MaintenanceLog':
                evidence, evidence_date = self._evaluate_maintenance(rule)
            elif target_model == 'BCDRTestLog':
                evidence, evidence_date = self._evaluate_bcdr_test(rule)
            elif target_model == 'OnboardingProcess':
                evidence, evidence_date = self._evaluate_onboarding(rule)
            elif target_model == 'OffboardingProcess':
                evidence, evidence_date = self._evaluate_offboarding(rule)
            elif target_model == 'SecurityAssessment':
                evidence, evidence_date = self._evaluate_supplier_assessment(rule)
            elif target_model == 'RiskAssessment':
                evidence, evidence_date = self._evaluate_risk_assessment(rule)
            elif target_model == 'UARExecution':
                evidence, evidence_date = self._evaluate_uar_execution(rule)
            else:
                return self._unknown_result(f"Unknown target_model: {target_model}")
            
            # Calculate status based on evidence
            return self._calculate_status(rule, evidence, evidence_date)
            
        except Exception as e:
            return self._unknown_result(f"Evaluation error: {str(e)}")
    
    def collect_evidence(
        self,
        rule: Any,
        months_lookback: int,
        sample_size: Optional[int] = None
    ) -> List[Any]:
        """
        Collect historical evidence for a rule over a time period.

        Args:
            rule: ComplianceRule instance
            months_lookback: Number of months to look back for evidence
            sample_size: Optional limit on number of items to return (random sample)

        Returns:
            List of evidence objects found within the time period
        """
        if not rule or not rule.enabled:
            return []
        
        try:
            # Calculate threshold date
            from dateutil.relativedelta import relativedelta
            threshold_date = now() - relativedelta(months=months_lookback)
            
            # Dispatch based on target_model
            target_model = rule.target_model
            
            if target_model == 'ActivityExecution':
                results = self._collect_activity_execution(rule, threshold_date)
            elif target_model == 'Campaign':
                results = self._collect_campaign(rule, threshold_date)
            elif target_model == 'MaintenanceLog':
                results = self._collect_maintenance(rule, threshold_date)
            elif target_model == 'BCDRTestLog':
                results = self._collect_bcdr_test(rule, threshold_date)
            elif target_model == 'SecurityAssessment':
                results = self._collect_supplier_assessment(rule, threshold_date)
            elif target_model == 'RiskAssessment':
                results = self._collect_risk_assessment(rule, threshold_date)
            elif target_model == 'UARExecution':
                results = self._collect_uar_execution(rule, threshold_date)
            else:
                return []
            
            # Apply random sampling if requested
            if sample_size and len(results) > sample_size:
                import random
                results = random.sample(results, sample_size)
            
            return results
            
        except Exception as e:
            import logging
            logging.warning(f"Error collecting evidence for rule {rule.id}: {e}")
            return []
    
    def evaluate_all_rules(self) -> List[Dict[str, Any]]:
        """
        Evaluate all enabled ComplianceRules.

        Returns:
            list of dicts, each containing rule info and evaluation result
        """
        from src.models.security import ComplianceRule
        
        results = []
        rules = ComplianceRule.query.filter_by(enabled=True).all()
        
        for rule in rules:
            evaluation = self.evaluate_rule(rule)
            results.append({
                'rule': rule,
                'rule_id': rule.id,
                'rule_name': rule.name,
                'control_id': rule.control.control_id if rule.control else None,
                'control_name': rule.control.name if rule.control else None,
                'framework_name': rule.control.framework.name if rule.control and rule.control.framework else None,
                **evaluation
            })
        
        return results
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """
        Get a summary of compliance status for dashboard display.

        Returns:
            dict with counts by status and overall health percentage
        """
        results = self.evaluate_all_rules()
        
        summary = {
            'total': len(results),
            'compliant': 0,
            'warning': 0,
            'non_compliant': 0,
            'unknown': 0,
            'results': results
        }
        
        for r in results:
            status = r.get('status', 'unknown')
            if status in summary:
                summary[status] += 1
        
        # Calculate health percentage (compliant / total * 100)
        if summary['total'] > 0:
            summary['health_percentage'] = round(
                (summary['compliant'] / summary['total']) * 100, 1
            )
        else:
            summary['health_percentage'] = 100.0
        
        return summary
    
    def get_framework_status(self, framework_id: int) -> Optional[Dict[str, Any]]:
        """
        Get aggregated compliance status for a single framework.

        Evaluates all controls and their rules, determining status using
        worst-case scenario logic.

        Args:
            framework_id: ID of the Framework to evaluate

        Returns:
            dict with:
                - framework: Framework object
                - stats: {total, compliant, warning, non_compliant, manual, uncovered, not_applicable}
                - controls: list of control data with status
        """
        from src.models.security import Framework
        
        framework = db.session.get(Framework, framework_id)
        if not framework:
            return None
        
        stats = {
            'total': 0,
            'compliant': 0,
            'warning': 0,
            'non_compliant': 0,
            'manual': 0,
            'uncovered': 0,
            'not_applicable': 0
        }

        controls_data = []

        for control in framework.framework_controls:
            stats['total'] += 1

            # SOA: Skip non-applicable controls
            if not control.is_applicable:
                stats['not_applicable'] += 1
                controls_data.append({
                    'id': control.id,
                    'control_id': control.control_id,
                    'name': control.name,
                    'description': control.description,
                    'status': 'not_applicable',
                    'rules_count': 0,
                    'manual_links_count': 0,
                    'linked_items_count': 0,
                    'oldest_evidence_date': None,
                    'rule_evaluations': [],
                    'coverage_type': 'not_applicable',
                    'soa_justification': control.soa_justification
                })
                continue

            rules = list(control.rules)
            manual_links_count = control.compliance_links.count()
            
            control_status = 'uncovered'
            oldest_evidence_date = None
            rule_evaluations = []
            has_non_compliant = False
            has_warning = False
            all_compliant = True
            
            if rules:
                # Evaluate each rule and apply worst-case logic
                for rule in rules:
                    if not rule.enabled:
                        continue
                        
                    evaluation = self.evaluate_rule(rule)
                    rule_evaluations.append({
                        'rule': rule,
                        'evaluation': evaluation
                    })
                    
                    status = evaluation.get('status', 'unknown')
                    evidence_date = evaluation.get('last_evidence_date')
                    
                    # Track oldest evidence for display
                    if evidence_date:
                        if oldest_evidence_date is None or evidence_date < oldest_evidence_date:
                            oldest_evidence_date = evidence_date
                    
                    # Worst-case status determination
                    if status == 'non_compliant':
                        has_non_compliant = True
                        all_compliant = False
                    elif status == 'warning':
                        has_warning = True
                        all_compliant = False
                    elif status != 'compliant':
                        all_compliant = False
                
                # Determine final control status
                if has_non_compliant:
                    control_status = 'non_compliant'
                elif has_warning:
                    control_status = 'warning'
                elif all_compliant and rule_evaluations:
                    control_status = 'compliant'
                elif not rule_evaluations:
                    # All rules disabled
                    if manual_links_count > 0:
                        control_status = 'manual'
                    else:
                        control_status = 'uncovered'
            
            elif manual_links_count > 0:
                # No rules, but has manual evidence links
                control_status = 'manual'
            
            else:
                # No rules and no manual links
                control_status = 'uncovered'
            
            # Increment stats counter
            stats[control_status] += 1
            
            controls_data.append({
                'id': control.id,
                'control_id': control.control_id,
                'name': control.name,
                'description': control.description,
                'status': control_status,
                'rules_count': len(rules),
                'manual_links_count': manual_links_count,
                'linked_items_count': len(rules) + manual_links_count,
                'oldest_evidence_date': oldest_evidence_date,
                'rule_evaluations': rule_evaluations,
                'coverage_type': 'automated' if rules else ('manual' if manual_links_count > 0 else 'none')
            })
        
        return {
            'framework': framework,
            'stats': stats,
            'controls': controls_data
        }
    
    # -------------------------------------------------------------------------
    # Private: Evaluation Methods per Target Model
    # -------------------------------------------------------------------------
    
    def _evaluate_activity_execution(self, rule: Any) -> Tuple[Optional[Any], Optional[datetime]]:
        """
        Evaluate rule against ActivityExecution model.

        Criteria format:
            {"method": "parent_match", "value": <activity_id>}

        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.activities import ActivityExecution, SecurityActivity
        
        criteria = rule.get_criteria()
        method = criteria.get('method', 'parent_match')
        
        if method == 'parent_match':
            activity_id = criteria.get('value')
            if not activity_id:
                # Try to find by activity name
                activity_name = criteria.get('activity_name')
                if activity_name:
                    activity = SecurityActivity.query.filter_by(name=activity_name).first()
                    if activity:
                        activity_id = activity.id
            
            if not activity_id:
                return None, None
            
            # Get the most recent execution for this activity
            execution = ActivityExecution.query.filter_by(
                activity_id=activity_id
            ).order_by(ActivityExecution.execution_date.desc()).first()
            
            if execution:
                # execution_date is a Date field, convert to datetime for consistency
                evidence_date = naive_to_aware(datetime.combine(execution.execution_date, datetime.min.time()))
                return execution, evidence_date
        
        return None, None
    
    def _evaluate_campaign(self, rule: Any) -> Tuple[Optional[Any], Optional[datetime]]:
        """
        Evaluate rule against Campaign model.

        Criteria format:
            {"method": "tag_match", "tags": ["Phishing", "Security"]}

        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.communications import Campaign
        
        criteria = rule.get_criteria()
        method = criteria.get('method', 'tag_match')
        
        if method == 'tag_match':
            tag_names = criteria.get('tags', [])
            if not tag_names:
                return None, None
            
            # Find campaigns with matching tags that are finished or ongoing
            campaigns = Campaign.query.filter(
                Campaign.status.in_(['finished', 'ongoing'])
            ).order_by(Campaign.processed_at.desc(), Campaign.created_at.desc()).all()
            
            for campaign in campaigns:
                campaign_tag_names = [t.name for t in campaign.tags]
                if any(tag in campaign_tag_names for tag in tag_names):
                    # Found a matching campaign
                    evidence_date = campaign.processed_at or campaign.created_at
                    return campaign, evidence_date
        
        elif method == 'title_match':
            # Match by campaign title pattern
            title_pattern = criteria.get('title_pattern', '')
            if not title_pattern:
                return None, None
            
            campaign = Campaign.query.filter(
                Campaign.status.in_(['finished', 'ongoing']),
                Campaign.title.ilike(f'%{title_pattern}%')
            ).order_by(Campaign.processed_at.desc(), Campaign.created_at.desc()).first()
            
            if campaign:
                evidence_date = campaign.processed_at or campaign.created_at
                return campaign, evidence_date
        
        return None, None
    
    def _evaluate_maintenance(self, rule):
        """
        Evaluate rule against MaintenanceLog model.
        
        Criteria format:
            {"method": "event_type_match", "event_type": "Backup Test"}
        
        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.assets import MaintenanceLog
        
        criteria = rule.get_criteria()
        method = criteria.get('method', 'event_type_match')
        
        if method == 'event_type_match':
            event_type = criteria.get('event_type')
            if not event_type:
                return None, None
            
            log = MaintenanceLog.query.filter_by(
                event_type=event_type,
                status='Completed'
            ).order_by(MaintenanceLog.created_at.desc()).first()
            
            if log:
                return log, log.created_at
        
        elif method == 'any_completed':
            # Just find the most recent completed maintenance
            log = MaintenanceLog.query.filter_by(
                status='Completed'
            ).order_by(MaintenanceLog.created_at.desc()).first()
            
            if log:
                return log, log.created_at
        
        return None, None
    
    def _evaluate_bcdr_test(self, rule):
        """
        Evaluate rule against BCDRTestLog model.
        
        Criteria format:
            {"method": "plan_match", "plan_id": 1}
            or {"method": "any_passed"}
        
        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.bcdr import BCDRTestLog
        
        criteria = rule.get_criteria()
        method = criteria.get('method', 'any_passed')
        
        if method == 'plan_match':
            plan_id = criteria.get('plan_id')
            if not plan_id:
                return None, None
            
            test_log = BCDRTestLog.query.filter_by(
                plan_id=plan_id,
                status='Passed'
            ).order_by(BCDRTestLog.test_date.desc()).first()
            
            if test_log:
                # test_date is a Date field
                evidence_date = naive_to_aware(datetime.combine(test_log.test_date, datetime.min.time()))
                return test_log, evidence_date

        elif method == 'any_passed':
            # Find any passed BCDR test
            test_log = BCDRTestLog.query.filter_by(
                status='Passed'
            ).order_by(BCDRTestLog.test_date.desc()).first()
            
            if test_log:
                evidence_date = naive_to_aware(datetime.combine(test_log.test_date, datetime.min.time()))
                return test_log, evidence_date

        return None, None

    def _evaluate_onboarding(self, rule):
        """
        Evaluate rule against OnboardingProcess model.
        
        Criteria format:
            {"tag": "Developers"} (optional - filter by user tag)
        
        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.onboarding import OnboardingProcess
        from src.models.auth import User
        
        criteria = rule.get_criteria()
        tag_name = criteria.get('tag')
        
        query = OnboardingProcess.query
        
        # Filter by user tag if specified
        if tag_name:
            query = query.join(User, OnboardingProcess.user_id == User.id)
            query = query.filter(User.tags.any(name=tag_name))
        
        # Get the most recent onboarding process
        latest_process = query.order_by(OnboardingProcess.created_at.desc()).first()
        
        if latest_process:
            return latest_process, latest_process.created_at
        
        return None, None
    
    def _evaluate_offboarding(self, rule):
        """
        Evaluate rule against OffboardingProcess model.
        
        Criteria format:
            {"tag": "Sales"} (optional - filter by user tag)
        
        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.onboarding import OffboardingProcess
        from src.models.auth import User
        
        criteria = rule.get_criteria()
        tag_name = criteria.get('tag')
        
        query = OffboardingProcess.query
        
        # Filter by user tag if specified
        if tag_name:
            query = query.join(User, OffboardingProcess.user_id == User.id)
            query = query.filter(User.tags.any(name=tag_name))
        
        # Get the most recent offboarding process
        latest_process = query.order_by(OffboardingProcess.created_at.desc()).first()
        
        if latest_process:
            return latest_process, latest_process.created_at
        
        return None, None
    
    def _evaluate_supplier_assessment(self, rule):
        """
        Evaluate rule against SecurityAssessment model.
        
        Criteria format:
            {"supplier_id": 123} (optional - filter by specific supplier)
        
        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.security import SecurityAssessment
        from src.models.procurement import Supplier
        
        criteria = rule.get_criteria()
        supplier_id = criteria.get('supplier_id')
        
        query = SecurityAssessment.query.join(Supplier)
        
        # Filter by specific supplier if provided
        if supplier_id:
            query = query.filter(SecurityAssessment.supplier_id == supplier_id)
        
        # Get the most recent assessment
        latest = query.order_by(SecurityAssessment.assessment_date.desc()).first()
        
        if latest:
            # assessment_date is a Date field, convert to datetime for consistency
            evidence_date = naive_to_aware(datetime.combine(latest.assessment_date, datetime.min.time()))
            return latest, evidence_date
        
        return None, None
    
    def _evaluate_risk_assessment(self, rule):
        """
        Evaluate rule against RiskAssessment model.

        Criteria format:
            {} (no specific criteria - just finds most recent)

        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.risk_assessment import RiskAssessment

        query = RiskAssessment.query

        # Get the most recent risk assessment
        latest = query.order_by(RiskAssessment.created_at.desc()).first()

        if latest:
            return latest, latest.created_at

        return None, None

    def _evaluate_uar_execution(self, rule):
        """
        Evaluate rule against UARExecution model.

        Criteria format:
            {"method": "any_completed"} (default - any completed UAR execution)
            {"method": "comparison_match", "comparison_id": 123} (specific comparison)
            {"method": "comparison_name_match", "comparison_name": "Active Users Review"}

        Returns:
            tuple: (evidence_object, evidence_date) or (None, None)
        """
        from src.models.uar import UARExecution, UARComparison

        criteria = rule.get_criteria()
        method = criteria.get('method', 'any_completed')

        if method == 'comparison_match':
            comparison_id = criteria.get('comparison_id')
            if not comparison_id:
                return None, None

            # Get the most recent completed execution for this comparison
            execution = UARExecution.query.filter_by(
                comparison_id=comparison_id,
                status='completed'
            ).order_by(UARExecution.started_at.desc()).first()

            if execution:
                return execution, execution.started_at

        elif method == 'comparison_name_match':
            comparison_name = criteria.get('comparison_name')
            if not comparison_name:
                return None, None

            # Find comparison by name
            comparison = UARComparison.query.filter_by(name=comparison_name).first()
            if not comparison:
                return None, None

            # Get the most recent completed execution
            execution = UARExecution.query.filter_by(
                comparison_id=comparison.id,
                status='completed'
            ).order_by(UARExecution.started_at.desc()).first()

            if execution:
                return execution, execution.started_at

        elif method == 'any_completed':
            # Find any completed UAR execution
            execution = UARExecution.query.filter_by(
                status='completed'
            ).order_by(UARExecution.started_at.desc()).first()

            if execution:
                return execution, execution.started_at

        return None, None
    
    # -------------------------------------------------------------------------
    # Private: Collection Methods for Historical Evidence
    # -------------------------------------------------------------------------
    
    def _collect_activity_execution(self, rule, threshold_date):
        """Collect ActivityExecution records within the time period."""
        from src.models.activities import ActivityExecution, SecurityActivity
        
        criteria = rule.get_criteria()
        method = criteria.get('method', 'parent_match')
        
        if method == 'parent_match':
            activity_id = criteria.get('value')
            if not activity_id:
                activity_name = criteria.get('activity_name')
                if activity_name:
                    activity = SecurityActivity.query.filter_by(name=activity_name).first()
                    if activity:
                        activity_id = activity.id
            
            if not activity_id:
                return []
            
            # Get all executions for this activity within the time period
            executions = ActivityExecution.query.filter(
                ActivityExecution.activity_id == activity_id,
                ActivityExecution.execution_date >= threshold_date.date()
            ).order_by(ActivityExecution.execution_date.desc()).all()
            
            return executions
        
        return []
    
    def _collect_campaign(self, rule, threshold_date):
        """Collect Campaign records within the time period."""
        from src.models.communications import Campaign
        
        criteria = rule.get_criteria()
        method = criteria.get('method', 'tag_match')
        
        if method == 'tag_match':
            tag_names = criteria.get('tags', [])
            if not tag_names:
                return []
            
            # Find campaigns with matching tags that are finished or ongoing
            campaigns = Campaign.query.filter(
                Campaign.status.in_(['finished', 'ongoing'])
            ).order_by(Campaign.processed_at.desc(), Campaign.created_at.desc()).all()
            
            # Filter by date and tags
            results = []
            for campaign in campaigns:
                campaign_date = campaign.processed_at or campaign.created_at
                if campaign_date and campaign_date >= threshold_date:
                    campaign_tag_names = [t.name for t in campaign.tags]
                    if any(tag in campaign_tag_names for tag in tag_names):
                        results.append(campaign)
            
            return results
        
        elif method == 'title_match':
            title_pattern = criteria.get('title_pattern', '')
            if not title_pattern:
                return []
            
            campaigns = Campaign.query.filter(
                Campaign.status.in_(['finished', 'ongoing']),
                Campaign.title.ilike(f'%{title_pattern}%')
            ).order_by(Campaign.processed_at.desc(), Campaign.created_at.desc()).all()
            
            # Filter by date
            results = []
            for campaign in campaigns:
                campaign_date = campaign.processed_at or campaign.created_at
                if campaign_date and campaign_date >= threshold_date:
                    results.append(campaign)
            
            return results
        
        return []
    
    def _collect_maintenance(self, rule, threshold_date):
        """Collect MaintenanceLog records within the time period."""
        from src.models.assets import MaintenanceLog
        
        criteria = rule.get_criteria()
        method = criteria.get('method', 'event_type_match')
        
        if method == 'event_type_match':
            event_type = criteria.get('event_type')
            if not event_type:
                return []
            
            logs = MaintenanceLog.query.filter(
                MaintenanceLog.event_type == event_type,
                MaintenanceLog.status == 'Completed',
                MaintenanceLog.created_at >= threshold_date
            ).order_by(MaintenanceLog.created_at.desc()).all()
            
            return logs
        
        elif method == 'any_completed':
            logs = MaintenanceLog.query.filter(
                MaintenanceLog.status == 'Completed',
                MaintenanceLog.created_at >= threshold_date
            ).order_by(MaintenanceLog.created_at.desc()).all()
            
            return logs
        
        return []
    
    def _collect_bcdr_test(self, rule, threshold_date):
        """Collect BCDRTestLog records within the time period."""
        from src.models.bcdr import BCDRTestLog
        
        criteria = rule.get_criteria()
        method = criteria.get('method', 'any_passed')
        
        if method == 'plan_match':
            plan_id = criteria.get('plan_id')
            if not plan_id:
                return []
            
            test_logs = BCDRTestLog.query.filter(
                BCDRTestLog.plan_id == plan_id,
                BCDRTestLog.status == 'Passed',
                BCDRTestLog.test_date >= threshold_date.date()
            ).order_by(BCDRTestLog.test_date.desc()).all()
            
            return test_logs
        
        elif method == 'any_passed':
            test_logs = BCDRTestLog.query.filter(
                BCDRTestLog.status == 'Passed',
                BCDRTestLog.test_date >= threshold_date.date()
            ).order_by(BCDRTestLog.test_date.desc()).all()
            
            return test_logs
        
        return []
    
    def _collect_supplier_assessment(self, rule, threshold_date):
        """Collect SecurityAssessment records within the time period."""
        from src.models.security import SecurityAssessment
        from src.models.procurement import Supplier
        
        criteria = rule.get_criteria()
        supplier_id = criteria.get('supplier_id')
        
        query = SecurityAssessment.query.join(Supplier)
        
        if supplier_id:
            query = query.filter(SecurityAssessment.supplier_id == supplier_id)
        
        # Filter by date
        assessments = query.filter(
            SecurityAssessment.assessment_date >= threshold_date.date()
        ).order_by(SecurityAssessment.assessment_date.desc()).all()
        
        return assessments
    
    def _collect_risk_assessment(self, rule, threshold_date):
        """Collect RiskAssessment records within the time period."""
        from src.models.risk_assessment import RiskAssessment

        assessments = RiskAssessment.query.filter(
            RiskAssessment.created_at >= threshold_date
        ).order_by(RiskAssessment.created_at.desc()).all()

        return assessments

    def _collect_uar_execution(self, rule, threshold_date):
        """Collect UARExecution records within the time period."""
        from src.models.uar import UARExecution, UARComparison

        criteria = rule.get_criteria()
        method = criteria.get('method', 'any_completed')

        if method == 'comparison_match':
            comparison_id = criteria.get('comparison_id')
            if not comparison_id:
                return []

            # Get all completed executions for this comparison within the time period
            executions = UARExecution.query.filter(
                UARExecution.comparison_id == comparison_id,
                UARExecution.status == 'completed',
                UARExecution.started_at >= threshold_date
            ).order_by(UARExecution.started_at.desc()).all()

            return executions

        elif method == 'comparison_name_match':
            comparison_name = criteria.get('comparison_name')
            if not comparison_name:
                return []

            # Find comparison by name
            comparison = UARComparison.query.filter_by(name=comparison_name).first()
            if not comparison:
                return []

            # Get all completed executions within the time period
            executions = UARExecution.query.filter(
                UARExecution.comparison_id == comparison.id,
                UARExecution.status == 'completed',
                UARExecution.started_at >= threshold_date
            ).order_by(UARExecution.started_at.desc()).all()

            return executions

        elif method == 'any_completed':
            # Find all completed UAR executions within the time period
            executions = UARExecution.query.filter(
                UARExecution.status == 'completed',
                UARExecution.started_at >= threshold_date
            ).order_by(UARExecution.started_at.desc()).all()

            return executions

        return []
    
    # -------------------------------------------------------------------------
    # Private: Status Calculation
    # -------------------------------------------------------------------------
    
    def _calculate_status(
        self,
        rule: Any,
        evidence: Optional[Any],
        evidence_date: Optional[datetime]
    ) -> Dict[str, Any]:
        """
        Calculate compliance status based on evidence date and rule SLA.

        Traffic Light Logic:
            - Green (compliant): days_since <= frequency_days
            - Yellow (warning): frequency_days < days_since <= (frequency + grace)
            - Red (non_compliant): days_since > (frequency + grace) OR no evidence
        """
        today = now()
        
        if not evidence or not evidence_date:
            # No evidence found = non-compliant
            return {
                'status': 'non_compliant',
                'last_evidence_date': None,
                'days_since': -1,
                'evidence': None,
                'next_due_date': today,  # Overdue now
                'message': 'No evidence found'
            }
        
        # Calculate days since last evidence
        if isinstance(evidence_date, date) and not isinstance(evidence_date, datetime):
            evidence_date = naive_to_aware(datetime.combine(evidence_date, datetime.min.time()))
        elif isinstance(evidence_date, datetime) and evidence_date.tzinfo is None:
            evidence_date = naive_to_aware(evidence_date)
        
        days_since = (today - evidence_date).days
        next_due_date = evidence_date + timedelta(days=rule.frequency_days)
        
        # Determine status
        if days_since <= rule.frequency_days:
            status = 'compliant'
            message = f'Last executed {days_since} days ago, within {rule.frequency_days}-day SLA'
        elif days_since <= rule.total_sla_days:
            status = 'warning'
            grace_remaining = rule.total_sla_days - days_since
            message = f'Grace period: {grace_remaining} days remaining before non-compliance'
        else:
            status = 'non_compliant'
            overdue_days = days_since - rule.total_sla_days
            message = f'Overdue by {overdue_days} days'
        
        return {
            'status': status,
            'last_evidence_date': evidence_date,
            'days_since': days_since,
            'evidence': evidence,
            'next_due_date': next_due_date,
            'message': message
        }
    
    def _unknown_result(self, message: str = "Unknown error") -> Dict[str, Any]:
        """Return a result dict for unknown/error states."""
        return {
            'status': 'unknown',
            'last_evidence_date': None,
            'days_since': -1,
            'evidence': None,
            'next_due_date': None,
            'message': message
        }


# Singleton instance for convenience
_evaluator_instance = None

def get_compliance_evaluator() -> ComplianceEvaluator:
    """Get singleton instance of ComplianceEvaluator."""
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = ComplianceEvaluator()
    return _evaluator_instance
