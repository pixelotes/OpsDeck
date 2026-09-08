"""The figures behind the Organizational Health dashboard.

The view used to compute all of this inline — 330 lines that were one function only
because they rendered one page. Each block here answers a single question the page
asks ("how healthy is the register?", "what is expiring in the next ninety days?") and
returns plain dicts and lists the template can render. Nothing here knows about the
request beyond ``url_for``, so every block can be tested on its own with a handful of
rows, and My Dashboard can reuse the risk posture instead of carrying its own copy.

Risk severity comes from ``Risk.criticality_level``, which reads the matrix the risk
was scored on and the appetite in force right now. The view used to hard-code
``residual_likelihood >= 4 and residual_impact >= 4`` for "critical" — the 5×5 matrix's
red corner — which stopped being true the day the matrix and the appetite became
configurable.
"""
import calendar
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from flask import url_for
from sqlalchemy.orm import joinedload

from ..models import Asset, License, MaintenanceLog, PaymentMethod, Subscription
from ..models.activities import SecurityActivity
from ..models.audits import ComplianceAudit
from ..models.certificates import CertificateVersion
from ..models.credentials import CredentialSecret
from ..models.security import Framework, Risk, SecurityIncident
from ..utils.timezone_helper import now, today
from .finance_service import renewal_occurrences_in_range

#: Risks that still count against the organisation: open, and not deliberately accepted.
OPEN_RISK_FILTERS = (Risk.status != 'Closed', Risk.treatment_strategy != 'Accept')

ACTIVE_INCIDENT_STATUSES = ('Open', 'Investigating', 'Escalated')
HIGH_INCIDENT_SEVERITIES = ('SEV-1', 'SEV-2', 'P1', 'P2')
UNHEALTHY_ASSET_STATUSES = ('In Repair', 'Awaiting Disposal', 'Disposed', 'Sold')
PENDING_AUDIT_STATUSES = ('Planned', 'Prep', 'Auditor Review')

#: Points taken off the health score per open risk at each severity.
CRITICAL_RISK_PENALTY = 15
HIGH_RISK_PENALTY = 5


def count_risks_by_level(risks):
    """{'Critical': n, 'High': n, ...} for an iterable of risks, on the current appetite."""
    counts = {'Critical': 0, 'High': 0, 'Medium': 0, 'Low': 0}
    for risk in risks:
        counts[risk.criticality_level] = counts.get(risk.criticality_level, 0) + 1
    return counts


def risk_posture():
    """Open, non-accepted risks by severity, plus the derived health score.

    ``high`` counts High *and* Critical, as the page always has: the score's 5-point
    band applies to everything at or above High, and the 15-point band adds to it.
    """
    counts = count_risks_by_level(Risk.query.filter(*OPEN_RISK_FILTERS).all())
    critical = counts['Critical']
    high = counts['High'] + critical
    return {
        'critical_risks': critical,
        'high_risks': high,
        'health_score': health_score(critical, high),
    }


def health_score(critical_risks, high_risks):
    return max(0, 100 - critical_risks * CRITICAL_RISK_PENALTY - high_risks * HIGH_RISK_PENALTY)


def active_incident_count():
    return SecurityIncident.query.filter(SecurityIncident.status.in_(ACTIVE_INCIDENT_STATUSES)).count()


def global_status(critical_risks, high_risks, active_incidents):
    """'critical' | 'degraded' | 'operational', the banner colour."""
    if critical_risks > 0 or active_incidents > 0:
        return 'critical'
    if high_risks > 2:
        return 'degraded'
    return 'operational'


def critical_action_items(limit_per_source=5):
    """Things that are already wrong: live incidents, overdue work, expired secrets and certs."""
    items = []

    incidents = SecurityIncident.query.filter(
        SecurityIncident.status.in_(ACTIVE_INCIDENT_STATUSES),
        SecurityIncident.severity.in_(HIGH_INCIDENT_SEVERITIES),
    ).limit(limit_per_source).all()
    for inc in incidents:
        items.append({
            'type': 'security', 'severity': 'critical',
            'title': inc.title,
            'description': f'{inc.severity} - {inc.status}',
            'link': url_for('compliance.incident_detail', id=inc.id),
        })

    overdue_logs = MaintenanceLog.query.options(joinedload(MaintenanceLog.asset)).filter(
        MaintenanceLog.status.in_(['Open', 'In Progress']),
        MaintenanceLog.event_date < today(),
    ).limit(limit_per_source).all()
    for log in overdue_logs:
        items.append({
            'type': 'operational', 'severity': 'high',
            'title': f'{log.asset.name if log.asset else "Unknown"} - Maintenance Overdue',
            'description': log.description[:50] if log.description else 'Scheduled maintenance delayed',
            'link': url_for('maintenance.log_detail', id=log.id),
        })

    expired_secrets = CredentialSecret.query.options(joinedload(CredentialSecret.credential)).filter(
        CredentialSecret.is_active == True,  # noqa: E712  (SQLAlchemy expression)
        CredentialSecret.expires_at < now(),
    ).limit(limit_per_source).all()
    for secret in expired_secrets:
        items.append({
            'type': 'security', 'severity': 'critical',
            'title': f'{secret.credential.name} - Credential Expired',
            'description': f'Type: {secret.credential.type}',
            'link': url_for('credentials.detail_credential', id=secret.credential.id),
        })

    expired_certs = CertificateVersion.query.options(joinedload(CertificateVersion.certificate)).filter(
        CertificateVersion.is_active == True,  # noqa: E712
        CertificateVersion.expires_at < today(),
    ).limit(limit_per_source).all()
    for cv in expired_certs:
        items.append({
            'type': 'security', 'severity': 'critical',
            'title': f'{cv.certificate.name} - Certificate Expired',
            'description': f'Expired: {cv.expires_at.strftime("%Y-%m-%d")}' if cv.expires_at else 'Expired',
            'link': url_for('certificates.certificate_detail', id=cv.certificate.id),
        })

    return items


def expiration_horizon(days=90):
    """What runs out within `days`, grouped as the page groups it, soonest first in each group.

    Returns the grouped dict and the active subscriptions it looked at, because the ops
    summary needs the same list and should not query it twice.
    """
    current = today()
    horizon = current + timedelta(days=days)
    expirations = {'finance': [], 'identity': [], 'certificates': [], 'legal': []}

    payment_methods = PaymentMethod.query.filter(
        PaymentMethod.is_archived == False,  # noqa: E712
        PaymentMethod.expiry_date.isnot(None),
    ).all()
    for pm in payment_methods:
        # A card expires at the end of its month, not on the first.
        last_day = pm.expiry_date.replace(day=calendar.monthrange(pm.expiry_date.year, pm.expiry_date.month)[1])
        if current <= last_day <= horizon:
            expirations['finance'].append({
                'name': pm.name,
                'days': (last_day - current).days,
                'meta': pm.details or pm.method_type,
                'link': url_for('payment_methods.payment_method_detail', id=pm.id),
            })

    expiring_secrets = CredentialSecret.query.options(joinedload(CredentialSecret.credential)).filter(
        CredentialSecret.is_active == True,  # noqa: E712
        CredentialSecret.expires_at.isnot(None),
        CredentialSecret.expires_at > now(),
        CredentialSecret.expires_at <= now() + timedelta(days=days),
    ).all()
    for secret in expiring_secrets:
        expirations['identity'].append({
            'name': secret.credential.name,
            'type': secret.credential.type,
            'days': (secret.expires_at.date() - current).days,
            'link': url_for('credentials.detail_credential', id=secret.credential.id),
        })

    cert_versions = CertificateVersion.query.options(joinedload(CertificateVersion.certificate)).filter(
        CertificateVersion.is_active == True,  # noqa: E712
        CertificateVersion.expires_at > current,
        CertificateVersion.expires_at <= horizon,
    ).all()
    for cv in cert_versions:
        expirations['certificates'].append({
            'name': cv.certificate.name,
            'issuer': cv.issuer,
            'days': (cv.expires_at - current).days,
            'link': url_for('certificates.certificate_detail', id=cv.certificate.id),
        })

    subscriptions = Subscription.query.filter_by(is_archived=False).all()
    for sub in subscriptions:
        next_renewal = sub.next_renewal_date
        if next_renewal and current <= next_renewal <= horizon:
            expirations['legal'].append({
                'name': sub.name,
                'cost': sub.cost_eur,
                'days': (next_renewal - current).days,
                'link': url_for('subscriptions.subscription_detail', id=sub.id),
            })

    licenses = License.query.filter(License.expiry_date > current, License.expiry_date <= horizon).all()
    for lic in licenses:
        expirations['legal'].append({
            'name': lic.name,
            'cost': None,
            'days': (lic.expiry_date - current).days,
            'link': url_for('licenses.detail', id=lic.id),
        })

    for group in expirations.values():
        group.sort(key=lambda item: item['days'])
    return expirations, subscriptions


def compliance_tasks(critical_items, expirations, warning_within_days=30):
    """One prioritised list: what is already due first, then upcoming by days remaining."""
    tasks = [{
        'category': item['type'],
        'severity': item['severity'],
        'title': item['title'],
        'meta': item['description'],
        'days': None,
        'link': item['link'],
    } for item in critical_items]
    for category, items in expirations.items():
        for it in items:
            tasks.append({
                'category': category,
                'severity': 'warning' if it['days'] <= warning_within_days else 'info',
                'title': it['name'],
                'meta': (it.get('meta') or it.get('type') or it.get('issuer')
                         or ('€%.2f' % it['cost'] if it.get('cost') else '')),
                'days': it['days'],
                'link': it['link'],
            })
    tasks.sort(key=lambda t: (1, t['days']) if t['days'] is not None else (0, 0))
    return tasks


def upcoming_activities(within_days=30):
    """Security activities due within `within_days`, including overdue ones, soonest first."""
    upcoming = []
    for activity in SecurityActivity.query.all():
        days = activity.days_until_due
        if days is None or days > within_days:
            continue
        upcoming.append({
            'name': activity.name,
            'frequency': activity.frequency,
            'days': days,
            'last_execution': activity.last_execution_date,
            'link': url_for('activities.activity_detail', id=activity.id),
        })
    upcoming.sort(key=lambda a: a['days'])
    return upcoming


def ops_summary(subscriptions):
    """Fleet health and this month's subscription spend."""
    current = today()
    active_assets = Asset.query.filter(
        Asset.is_archived == False,  # noqa: E712
        Asset.status != 'Decommissioned',
    ).all()
    total = len(active_assets)
    healthy = sum(1 for a in active_assets if a.status not in UNHEALTHY_ASSET_STATUSES)
    under_warranty = sum(1 for a in active_assets if a.warranty_end_date and a.warranty_end_date >= current)

    # Same helper as the Ops & Finance dashboard, so the two figures agree.
    month_start = current.replace(day=1)
    month_end = month_start + relativedelta(months=1, days=-1)
    projected_spend = sum(sub.cost_eur for _, sub in renewal_occurrences_in_range(subscriptions, month_start, month_end))

    return {
        'projected_spend': projected_spend,
        'asset_health': int(healthy / total * 100) if total else 100,
        'healthy_assets': healthy,
        'total_assets': total,
        'assets_under_warranty': under_warranty,
        'active_subscriptions': len(subscriptions),
    }


def compliance_summary():
    """Control coverage across active frameworks, from the same evaluator as the Compliance page."""
    from .compliance_service import get_compliance_evaluator
    evaluator = get_compliance_evaluator()

    agg = {'total': 0, 'compliant': 0, 'warning': 0, 'non_compliant': 0,
           'manual': 0, 'uncovered': 0, 'not_applicable': 0}
    framework_scores = []
    for fw in Framework.query.filter_by(is_active=True).order_by(Framework.name).all():
        status = evaluator.get_framework_status(fw.id)
        if not status:
            continue
        stats = status['stats']
        for key in agg:
            agg[key] += stats.get(key, 0)
        applicable = stats['total'] - stats.get('not_applicable', 0)
        # "Covered" is anything with evidence behind it: compliant or manually attested.
        covered = stats['compliant'] + stats['manual']
        framework_scores.append({
            'name': fw.name,
            'pct': int(round(covered / applicable * 100)) if applicable else 100,
            'covered': covered,
            'applicable': applicable,
        })

    applicable_controls = agg['total'] - agg['not_applicable']
    covered_controls = agg['compliant'] + agg['manual']
    return {
        'score': int(round(covered_controls / applicable_controls * 100)) if applicable_controls else 100,
        'compliant_controls': covered_controls,
        'total_controls': applicable_controls,
        'at_risk_controls': agg['warning'] + agg['non_compliant'],
        'uncovered_controls': agg['uncovered'],
        'pending_audits': ComplianceAudit.query.filter(ComplianceAudit.status.in_(PENDING_AUDIT_STATUSES)).count(),
        'frameworks': framework_scores,
    }
