"""
Communications Context Factory

Builds context dictionaries for Jinja2 template rendering based on
the target process type.
"""
from datetime import datetime
from ..extensions import db
from ..models.onboarding import OnboardingProcess, OffboardingProcess
from src.utils.timezone_helper import now, today



def get_template_context(scheduled_comm):
    """
    Build context dict for Jinja2 template rendering based on target_type.
    
    Args:
        scheduled_comm: ScheduledCommunication instance
    
    Returns:
        dict: Context variables for Jinja2 template rendering
    """
    context = {
        'today': today(),
    }

    # Event-engine comms: build a generic context from the originating AuditLog row.
    if scheduled_comm.event_rule_id and scheduled_comm.audit_log_id:
        import json
        from ..models.audit_log import AuditLog
        audit = db.session.get(AuditLog, scheduled_comm.audit_log_id)
        if audit:
            try:
                changes = json.loads(audit.changes) if audit.changes else None
            except (ValueError, TypeError):
                changes = None
            context.update({
                'recipient_name': scheduled_comm.recipient_name or 'User',
                'entity_type': audit.entity_type,
                'entity_id': audit.entity_id,
                'entity': audit.entity_repr,
                'action': audit.action,
                'actor': audit.user_email or 'system',
                'changes': changes,
                'timestamp': audit.timestamp,
            })
        return context

    if scheduled_comm.target_type == 'onboarding':
        process = db.session.get(OnboardingProcess, scheduled_comm.target_id)
        if process:
            context.update({
                'new_hire_name': process.new_hire_name,
                'start_date': process.start_date,
                'pack': process.pack,
            })
            
            if process.user:
                context['user'] = {
                    'name': process.user.name,
                    'email': process.user.email,
                    'personal_email': process.user.personal_email or '',
                    'job_title': process.user.job_title or '',
                }
            else:
                context['user'] = {
                    'name': process.new_hire_name,
                    'email': process.target_email or '',
                    'personal_email': process.personal_email or '',
                    'job_title': '',
                }
            
            if process.assigned_manager:
                context['manager'] = {
                    'name': process.assigned_manager.name,
                    'email': process.assigned_manager.email,
                }
            else:
                context['manager'] = None
            
            if process.assigned_buddy:
                context['buddy'] = {
                    'name': process.assigned_buddy.name,
                    'email': process.assigned_buddy.email,
                }
            else:
                context['buddy'] = None
                
    elif scheduled_comm.target_type == 'offboarding':
        process = db.session.get(OffboardingProcess, scheduled_comm.target_id)
        if process:
            context.update({
                'departure_date': process.departure_date,
            })
            
            if process.user:
                context['user'] = {
                    'name': process.user.name,
                    'email': process.user.email,
                    'personal_email': process.user.personal_email or '',
                    'job_title': process.user.job_title or '',
                }
            else:
                context['user'] = None
            
            if process.manager:
                context['manager'] = {
                    'name': process.manager.name,
                    'email': process.manager.email,
                }
            else:
                context['manager'] = None
            
            # Offboarding doesn't have buddy
            context['buddy'] = None
    
    elif scheduled_comm.target_type == 'campaign':
        # For campaigns, use the recipient_user stored in the scheduled communication
        if scheduled_comm.recipient_user:
            user = scheduled_comm.recipient_user
            context['user'] = {
                'name': user.name,
                'email': user.email,
                'job_title': user.job_title or '',
                'department': user.department or '',
            }
            # Also add manager if available
            if user.manager:
                context['manager'] = {
                    'name': user.manager.name,
                    'email': user.manager.email,
                }
            else:
                context['manager'] = None
        else:
            # Fallback to cached recipient info
            context['user'] = {
                'name': scheduled_comm.recipient_name or 'User',
                'email': scheduled_comm.recipient_email or '',
                'job_title': '',
                'department': '',
            }
            context['manager'] = None
    
    elif scheduled_comm.target_type == 'compliance_rule':
        # For compliance breach alerts, load the rule and its evaluation
        from ..models.security import ComplianceRule
        from ..services.compliance_service import get_compliance_evaluator
        
        rule = db.session.get(ComplianceRule, scheduled_comm.target_id)
        if rule:
            evaluator = get_compliance_evaluator()
            result = evaluator.evaluate_rule(rule)
            
            control = rule.control
            framework = control.framework if control else None
            
            # Calculate days overdue
            days_since = result.get('days_since', -1)
            if days_since >= 0 and rule.total_sla_days:
                days_overdue = max(0, days_since - rule.total_sla_days)
            else:
                days_overdue = 'N/A'
            
            # Format evidence date
            evidence_date = result.get('last_evidence_date')
            if evidence_date:
                last_evidence_date = evidence_date.strftime('%Y-%m-%d')
            else:
                last_evidence_date = None
            
            context.update({
                'recipient_name': scheduled_comm.recipient_name or 'Administrator',
                'rule_name': rule.name,
                'target_model': rule.target_model,
                'frequency_days': rule.frequency_days,
                'grace_period_days': rule.grace_period_days,
                'control_id': control.control_id if control else 'Unknown',
                'control_name': control.name if control else 'Unknown Control',
                'framework_name': framework.name if framework else 'Unknown Framework',
                'last_evidence_date': last_evidence_date,
                'days_since': days_since,
                'days_overdue': days_overdue,
                'status': result.get('status', 'unknown'),
                'message': result.get('message', ''),
                'dashboard_url': '/compliance/dashboard'  # Relative URL for now
            })
    
    elif scheduled_comm.target_type == 'license':
        # For license expiry notifications
        from ..models.assets import License
        
        license = db.session.get(License, scheduled_comm.target_id)
        if license:
            days_left = (license.expiry_date - today()).days if license.expiry_date else 0
            context.update({
                'recipient_name': scheduled_comm.recipient_name or 'User',
                'license_name': license.name,
                'expiry_date': license.expiry_date.strftime('%Y-%m-%d') if license.expiry_date else 'N/A',
                'days_left': days_left
            })
    
    elif scheduled_comm.target_type == 'subscription':
        # For subscription renewal notifications
        from ..models.procurement import Subscription
        
        subscription = db.session.get(Subscription, scheduled_comm.target_id)
        if subscription:
            renewal_date = subscription.next_renewal_date
            days_left = (renewal_date - today()).days if renewal_date else 0
            context.update({
                'recipient_name': scheduled_comm.recipient_name or 'Admin',
                'subscription_name': subscription.name,
                'renewal_date': renewal_date.strftime('%Y-%m-%d') if renewal_date else 'N/A',
                'days_left': days_left,
                'cost': f"${subscription.cost:,.2f}" if subscription.cost else 'N/A'
            })
    
    return context


def render_email_template(template_or_campaign, context):
    """
    Render an email template or campaign with the given context.
    
    Args:
        template_or_campaign: EmailTemplate or Campaign instance
        context: dict of context variables
    
    Returns:
        tuple: (subject, body_html) rendered with Jinja2
    """
    from jinja2 import UndefinedError
    from jinja2.sandbox import SandboxedEnvironment
    
    # Use sandboxed environment for security
    env = SandboxedEnvironment()
    
    try:
        # Render subject
        subject_template = env.from_string(template_or_campaign.subject)
        subject = subject_template.render(**context)
        
        # Render body
        body_template = env.from_string(template_or_campaign.body_html)
        body_html = body_template.render(**context)
        
        return subject, body_html
    except UndefinedError:
        # Log undefined variable but still render
        return template_or_campaign.subject, template_or_campaign.body_html
    except Exception as e:
        raise ValueError(f"Template rendering error: {str(e)}")


def validate_template_syntax(template_str):
    """
    Validate Jinja2 template syntax without rendering.
    
    Uses the sandboxed environment's parse() method to check for syntax errors
    before a template is saved to the database, preventing runtime crashes
    in the notification worker.
    
    Args:
        template_str: The Jinja2 template string to validate
        
    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    from jinja2.sandbox import SandboxedEnvironment
    from jinja2 import TemplateSyntaxError
    
    env = SandboxedEnvironment()
    try:
        env.parse(template_str)
        return True, None
    except TemplateSyntaxError as e:
        return False, f"Line {e.lineno}: {e.message}"

