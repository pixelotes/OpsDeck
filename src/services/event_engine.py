"""
Event engine evaluator.

Treats AuditLog as the event journal: reads committed changes that have not yet
been processed, matches them against enabled EventRules (by entity_type + action),
and enqueues ScheduledCommunication rows through the existing delivery queue
(``notifications.process_communications_queue``). Each AuditLog row is marked
``event_processed=true`` so notifications are never repeated.

Registered as a periodic scheduler job; intentionally decoupled from the request
path (no synchronous work in the user's transaction).
"""
from src.utils.timezone_helper import today

BATCH_SIZE = 200


def _resolve_recipients(rule):
    """Return a list of (email, name) tuples for a rule's static recipients."""
    from ..models.auth import User

    if rule.recipient_mode == 'emails':
        emails = [e.strip() for e in (rule.recipient_emails or '').split(',') if e.strip()]
        return [(e, e) for e in emails]

    if rule.recipient_mode == 'role':
        if not rule.recipient_role:
            return []
        users = User.query.filter_by(role=rule.recipient_role).all()
        return [(u.email, u.name) for u in users if u.email]

    # 'admins' (default)
    admins = User.query.filter_by(role='admin').all()
    return [(u.email, u.name) for u in admins if u.email]


def _enqueue_for_rule(db, rule, audit, recipients):
    """Create one ScheduledCommunication per recipient × channel for a matched rule."""
    from ..models.communications import ScheduledCommunication

    channels = rule.channels or ['email']
    created = 0

    for email, name in recipients:
        for channel in channels:
            comm = ScheduledCommunication(
                template_id=rule.template_id,
                status='pending',
                scheduled_date=today(),
                target_type=audit.entity_type,
                target_id=audit.entity_id or 0,
                recipient_email=email,
                recipient_name=name,
                recipient_type='event_rule',
                channel=channel,
                slack_target_channel=rule.slack_target_channel if channel == 'slack' else None,
                event_rule_id=rule.id,
                audit_log_id=audit.id,
            )
            db.session.add(comm)
            created += 1

    return created


def process_event_rules(app):
    """Match unprocessed AuditLog rows against EventRules and enqueue notifications."""
    from ..extensions import db
    from ..models.audit_log import AuditLog
    from ..models.event_rules import EventRule

    with app.app_context():
        rules = EventRule.query.filter_by(enabled=True).all()

        # Index enabled rules by entity_type so we only touch audit rows that matter.
        rules_by_entity = {}
        for rule in rules:
            rules_by_entity.setdefault(rule.entity_type, []).append(rule)

        # Always drain the queue (mark rows processed) even with no rules, so the
        # backlog of "unprocessed" rows does not grow unbounded once enabled.
        pending = (
            AuditLog.query
            .filter_by(event_processed=False)
            .order_by(AuditLog.id)
            .limit(BATCH_SIZE)
            .all()
        )

        if not pending:
            app.logger.info("Event engine: no unprocessed audit rows.")
            return

        enqueued = 0
        for audit in pending:
            for rule in rules_by_entity.get(audit.entity_type, []):
                if not rule.matches(audit.entity_type, audit.action):
                    continue
                if not rule.template_id:
                    app.logger.warning(
                        f"Event engine: rule '{rule.name}' has no template, skipping audit {audit.id}."
                    )
                    continue
                recipients = _resolve_recipients(rule)
                if not recipients:
                    app.logger.warning(
                        f"Event engine: rule '{rule.name}' resolved no recipients, skipping audit {audit.id}."
                    )
                    continue
                enqueued += _enqueue_for_rule(db, rule, audit, recipients)

            audit.event_processed = True

        db.session.commit()
        app.logger.info(
            f"Event engine: processed {len(pending)} audit row(s), enqueued {enqueued} notification(s)."
        )
