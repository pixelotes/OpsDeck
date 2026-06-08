from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
)
import os
from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from markupsafe import Markup
from functools import wraps
from datetime import date, timedelta, datetime
from dateutil.relativedelta import relativedelta
from ..models import db, User, UserKnownIP, Subscription, NotificationSetting, Asset, Supplier, Contact, Purchase, Peripheral, Location, PaymentMethod, License, MaintenanceLog
from ..models.security import SecurityIncident, Risk, Framework, FrameworkControl
from ..models.credentials import Credential, CredentialSecret
from ..models.certificates import Certificate, CertificateVersion
from ..models.audits import ComplianceAudit
from ..services.permissions_service import requires_permission, get_user_modules, user_has_module_access
from ..services.finance_service import renewal_occurrences_in_range
from src import limiter
from src import notifications
import calendar
import random

main_bp = Blueprint('main', __name__)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated_function

def is_break_glass_admin(user):
    """Check if the user is the break-glass admin account."""
    if not user:
        return False
    default_admin_email = current_app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
    return user.email == default_admin_email

from src.utils.logger import log_audit
from src.utils.timezone_helper import now, today


@main_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            # Credentials valid - check if MFA is needed
            return verify_ip_and_login(user)
        else:
            # Log failed login attempt
            log_audit(
                event_type='security.login',
                action='login',
                outcome='failure',
                target_object=email,
                error_message='Invalid email or password'
            )
            flash('Invalid email or password', 'danger')

    return render_template('login.html')


@main_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint for Kubernetes probes.
    Returns 200 OK if the application is running.
    No rate limiting or authentication required.
    """
    return jsonify({'status': 'healthy'}), 200



def verify_ip_and_login(user):
    """Verify user's IP and either login directly or trigger MFA flow."""
    ip = request.remote_addr
    
    # Check if IP is known for this user
    known_ip = UserKnownIP.query.filter_by(
        user_id=user.id,
        ip_address=ip
    ).first()
    
    # If IP is known or MFA is disabled -> direct login
    if known_ip or not current_app.config.get('MFA_ENABLED', False):
        if known_ip:
            known_ip.last_seen = now()
            db.session.commit()
        
        # Log successful login
        log_audit(
            event_type='security.login',
            action='login',
            outcome='success',
            target_object=f"User:{user.id}",
            user_email=user.email # Explicitly passed as session isn't set yet
        )
        session['user_id'] = user.id
        session['user_role'] = user.role
        
        # Populate permissions cache immediately
        get_user_modules(user.id)
        
        flash('Logged in successfully', 'success')
        return redirect(url_for('main.dashboard'))
    
    # --- NEW IP DETECTED: Trigger MFA ---
    
    # Generate 6-digit OTP
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    
    # Store MFA session data (expires in 10 min)
    session['mfa_user_id'] = user.id
    session['mfa_otp'] = otp
    session['mfa_expiry'] = (now() + timedelta(minutes=10)).timestamp()
    
    # Send OTP email
    email_body = f"""
    <h2>Security Verification Code</h2>
    <p>A login attempt from a new location has been detected.</p>
    <p>Your verification code is:</p>
    <h1 style="font-size: 32px; letter-spacing: 5px; font-family: monospace;">{otp}</h1>
    <p>This code expires in 10 minutes.</p>
    <p>If you did not attempt to log in, please ignore this email.</p>
    """
    notifications.send_email(
        current_app._get_current_object(),
        "OpsDeck - Security Verification Code",
        email_body,
        [user.email]
    )
    
    # Log MFA code sent (without revealing the code)
    log_audit(
        event_type='security.mfa',
        action='send_code',
        outcome='success',
        target_object=f"User:{user.id}",
        user_email=user.email
    )
    
    flash('New device detected. Check your email for the verification code.', 'info')
    return redirect(url_for('main.mfa_verify'))


@main_bp.route('/mfa-verify', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def mfa_verify():
    """Handle MFA verification."""
    # Check if MFA session exists
    if 'mfa_user_id' not in session:
        return redirect(url_for('main.login'))
    
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        stored_otp = session.get('mfa_otp')
        expiry = session.get('mfa_expiry')
        user_id = session.get('mfa_user_id')
        
        # Check if session is expired
        if not stored_otp or now().timestamp() > expiry:
            # Clear MFA session
            session.pop('mfa_user_id', None)
            session.pop('mfa_otp', None)
            session.pop('mfa_expiry', None)
            flash('The code has expired. Please log in again.', 'warning')
            return redirect(url_for('main.login'))
        
        if code == stored_otp:
            # SUCCESS - Get user and complete login
            user = db.session.get(User,user_id)
            if user:
                # Save the new IP to whitelist
                new_ip = UserKnownIP(
                    user_id=user.id,
                    ip_address=request.remote_addr
                )
                db.session.add(new_ip)
                db.session.commit()
                
                # Clear MFA session
                session.pop('mfa_user_id', None)
                session.pop('mfa_otp', None)
                session.pop('mfa_expiry', None)
                
                # Log successful MFA verification
                log_audit(
                    event_type='security.mfa',
                    action='verify',
                    outcome='success',
                    target_object=f"User:{user.id}",
                    user_email=user.email
                )
                
                # Complete login
                session['user_id'] = user.id
                session['user_role'] = user.role
                
                # Populate permissions cache immediately
                get_user_modules(user.id)
                
                flash('Device verified. Welcome.', 'success')
                return redirect(url_for('main.dashboard'))
        
        # FAILURE - Wrong code
        log_audit(
            event_type='security.mfa',
            action='verify',
            outcome='failure',
            target_object=f"User:{user_id}",
            error_message="Invalid MFA code"
        )
        flash('Incorrect code. Please try again.', 'danger')
    
    return render_template('mfa.html')

@main_bp.route('/logout')
@login_required
def logout():
    session.pop('user_id', None)
    flash('You have been logged out', 'success')
    return redirect(url_for('main.login'))


@main_bp.route('/impersonate/<int:user_id>', methods=['POST'])
@login_required
def impersonate(user_id):
    """Start impersonating another user (break-glass admin only)."""
    # Get current user
    current_user = db.session.get(User,session['user_id'])
    
    # Verify current user is the break-glass admin
    if not is_break_glass_admin(current_user):
        log_audit(
            event_type='security.impersonation',
            action='attempt',
            outcome='failure',
            target_object=f"User:{user_id}",
            error_message='Unauthorized impersonation attempt - not break-glass admin'
        )
        flash('Unauthorized: Only the break-glass admin can impersonate users.', 'danger')
        return redirect(url_for('users.users'))
    
    # Get target user
    target_user = db.get_or_404(User, user_id)
    
    # Prevent impersonating yourself
    if current_user.id == target_user.id:
        flash('You cannot impersonate yourself.', 'warning')
        return redirect(url_for('users.users'))
    
    # Store original user ID and start impersonation
    session['original_user_id'] = current_user.id
    session['user_id'] = target_user.id
    
    # Populate permissions cache for the target user
    get_user_modules(target_user.id)
    
    # Log the impersonation start
    log_audit(
        event_type='security.impersonation',
        action='start',
        outcome='success',
        target_object=f"User:{target_user.id}",
        user_email=current_user.email,
        details=f"Admin {current_user.email} started impersonating {target_user.email}"
    )
    
    flash(f'Now impersonating: {target_user.name} ({target_user.email})', 'info')
    return redirect(url_for('main.dashboard'))


@main_bp.route('/stop-impersonate', methods=['POST'])
@login_required
def stop_impersonate():
    """Stop impersonating and return to original user."""
    # Check if currently impersonating
    original_user_id = session.get('original_user_id')
    if not original_user_id:
        flash('You are not currently impersonating anyone.', 'warning')
        return redirect(url_for('main.dashboard'))
    
    # Get both users for logging
    impersonated_user = db.session.get(User,session['user_id'])
    original_user = db.session.get(User,original_user_id)
    
    # Restore original user session
    session['user_id'] = original_user_id
    session.pop('original_user_id', None)
    
    # Refresh permissions cache for the original user
    get_user_modules(original_user_id)
    
    # Log the impersonation end
    log_audit(
        event_type='security.impersonation',
        action='stop',
        outcome='success',
        target_object=f"User:{impersonated_user.id if impersonated_user else 'Unknown'}",
        user_email=original_user.email if original_user else 'Unknown',
        details=f"Admin {original_user.email if original_user else 'Unknown'} stopped impersonating"
    )
    
    flash('Impersonation ended. Returned to your account.', 'success')
    return redirect(url_for('users.users'))


@main_bp.route('/google/callback')
def google_callback():
    """Handle Google OAuth callback and authenticate user."""
    from flask_dance.contrib.google import google
    
    if not google.authorized:
        log_audit(
            event_type='security.login_oauth',
            action='login',
            outcome='failure',
            error_message="Google not authorized"
        )
        flash('Error al autorizar con Google', 'danger')
        return redirect(url_for('main.login'))
    
    # Get user info from Google
    try:
        resp = google.get("/oauth2/v2/userinfo")
        if not resp.ok:
            log_audit(
                event_type='security.login_oauth',
                action='login',
                outcome='failure',
                error_message=f"Google API error: {resp.status_code}"
            )
            flash('Error al obtener información de Google', 'danger')
            return redirect(url_for('main.login'))
        
        google_info = resp.json()
        email = google_info.get("email")
    except Exception as e:
        current_app.logger.error(f"Exception during Google OAuth: {str(e)}")
        log_audit(
            event_type='security.login_oauth',
            action='login',
            outcome='failure',
            error_message=str(e)
        )
        flash('Error al procesar la autenticación de Google', 'danger')
        return redirect(url_for('main.login'))
    
    # Find user in database
    user = User.query.filter_by(email=email).first()
    
    if user:
        # Success - log and create session
        log_audit(
            event_type='security.login_oauth',
            action='login',
            outcome='success',
            target_object=f"User:{user.id}",
            user_email=email,
            provider="google"
        )
        session['user_id'] = user.id
        session['user_role'] = user.role
        
        # Populate permissions cache immediately
        get_user_modules(user.id)
        
        flash('Logged in successfully via Google', 'success')
        return redirect(url_for('main.dashboard'))
    else:
        # User not found in database
        log_audit(
            event_type='security.login_oauth',
            action='login',
            outcome='failure',
            target_object=email,
            error_message="User not found in database"
        )
        flash('No existe un usuario registrado con este email.', 'danger')
        return redirect(url_for('main.login'))

def password_change_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if user_id:
            user = db.session.get(User,user_id)
            # Get configured admin credentials from app config
            default_admin_email = current_app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
            default_admin_password = current_app.config.get('DEFAULT_ADMIN_INITIAL_PASSWORD', 'admin123')
            
            # Check if user is using the default admin credentials
            if user and user.email == default_admin_email and user.check_password(default_admin_password):
                if request.endpoint not in ['main.change_password', 'main.logout', 'static']:
                    # Redirect without flash message - the UI will show the forced change alert
                    return redirect(url_for('main.change_password'))
        return f(*args, **kwargs)
    return decorated_function

@main_bp.route('/', endpoint='dashboard')
@login_required
def home():
    """
    Landing page with conditional routing:
    - Users with 'health_dashboard' permission → Organizational Health Dashboard
    - Users without permission → Personal Dashboard
    """
    user_id = session.get('user_id')

    # Check if user has access to organizational dashboard
    if user_has_module_access(user_id, 'health_dashboard', 'READ_ONLY'):
        return organizational_health()
    else:
        return redirect(url_for('main.my_dashboard'))

@main_bp.route('/org-health')
@login_required
@requires_permission('health_dashboard', access_level='READ_ONLY')
def organizational_health():
    """Executive Organizational Health Dashboard."""
    user_id = session.get('user_id')
    user = db.session.get(User, user_id)
    current_date = today()
    ninety_days = current_date + timedelta(days=90)
    
    # ----- HEALTH SCORE CALCULATION -----
    # Based on inverse of critical/high risks (Excluding Closed and Accepted)
    critical_risks = Risk.query.filter(
        Risk.status != 'Closed',
        Risk.treatment_strategy != 'Accept',
        Risk.residual_likelihood >= 4, 
        Risk.residual_impact >= 4
    ).count()
    
    high_risks = Risk.query.filter(
        Risk.status != 'Closed',
        Risk.treatment_strategy != 'Accept',
        Risk.residual_likelihood >= 3, 
        Risk.residual_impact >= 3
    ).count()
    health_score = max(0, 100 - (critical_risks * 15) - (high_risks * 5))
    
    # ----- GLOBAL STATUS -----
    active_incidents = SecurityIncident.query.filter(
        SecurityIncident.status.in_(['Open', 'Investigating', 'Escalated'])
    ).count()
    
    if critical_risks > 0 or active_incidents > 0:
        global_status = 'critical'
    elif high_risks > 2:
        global_status = 'degraded'
    else:
        global_status = 'operational'
    
    # ----- CRITICAL ACTION ITEMS (RED STATE) -----
    critical_items = []
    
    # Active high-severity incidents
    incidents = SecurityIncident.query.filter(
        SecurityIncident.status.in_(['Open', 'Investigating', 'Escalated']),
        SecurityIncident.severity.in_(['SEV-1', 'SEV-2', 'P1', 'P2'])
    ).limit(5).all()
    for inc in incidents:
        critical_items.append({
            'type': 'security',
            'severity': 'critical',
            'title': inc.title,
            'description': f'{inc.severity} - {inc.status}',
            'link': url_for('compliance.incident_detail', id=inc.id)
        })
    
    # Overdue maintenance
    overdue_logs = MaintenanceLog.query.options(
        joinedload(MaintenanceLog.asset)
    ).filter(
        MaintenanceLog.status.in_(['Open', 'In Progress']),
        MaintenanceLog.event_date < today()
    ).limit(5).all()
    for log in overdue_logs:
        critical_items.append({
            'type': 'operational',
            'severity': 'high',
            'title': f'{log.asset.name if log.asset else "Unknown"} - Maintenance Overdue',
            'description': log.description[:50] if log.description else 'Scheduled maintenance delayed',
            'link': url_for('maintenance.log_detail', id=log.id)
        })
    
    # Expired credentials
    expired_secrets = CredentialSecret.query.options(
        joinedload(CredentialSecret.credential)
    ).filter(
        CredentialSecret.is_active == True,
        CredentialSecret.expires_at < now()
    ).limit(5).all()
    for secret in expired_secrets:
        critical_items.append({
            'type': 'security',
            'severity': 'critical',
            'title': f'{secret.credential.name} - Credential Expired',
            'description': f'Type: {secret.credential.type}',
            'link': url_for('credentials.detail_credential', id=secret.credential.id)
        })
    
    # Expired certificates (still active)
    expired_certs = CertificateVersion.query.options(
        joinedload(CertificateVersion.certificate)
    ).filter(
        CertificateVersion.is_active == True,
        CertificateVersion.expires_at < today()
    ).limit(5).all()
    for cv in expired_certs:
        critical_items.append({
            'type': 'security',
            'severity': 'critical',
            'title': f'{cv.certificate.name} - Certificate Expired',
            'description': f'Expired: {cv.expires_at.strftime("%Y-%m-%d")}' if cv.expires_at else 'Expired',
            'link': url_for('certificates.certificate_detail', id=cv.certificate.id)
        })
    
    # ----- EXPIRATION HORIZON (YELLOW STATE) -----
    expirations = {'finance': [], 'identity': [], 'certificates': [], 'legal': []}
    
    # Financial: Payment Methods
    payment_methods = PaymentMethod.query.filter(
        PaymentMethod.is_archived == False,
        PaymentMethod.expiry_date.isnot(None)
    ).all()
    for pm in payment_methods:
        last_day = pm.expiry_date.replace(day=calendar.monthrange(pm.expiry_date.year, pm.expiry_date.month)[1])
        if today() <= last_day <= ninety_days:
            days = (last_day - today()).days
            expirations['finance'].append({
                'name': pm.name,
                'days': days,
                'meta': pm.details or pm.method_type,
                'link': url_for('payment_methods.payment_method_detail', id=pm.id)
            })
    expirations['finance'].sort(key=lambda x: x['days'])
    
    # Identity: Credentials
    expiring_secrets = CredentialSecret.query.options(
        joinedload(CredentialSecret.credential)
    ).filter(
        CredentialSecret.is_active == True,
        CredentialSecret.expires_at.isnot(None),
        CredentialSecret.expires_at > now(),
        CredentialSecret.expires_at <= now() + timedelta(days=90)
    ).all()
    for secret in expiring_secrets:
        days = (secret.expires_at.date() - today()).days
        expirations['identity'].append({
            'name': secret.credential.name,
            'type': secret.credential.type,
            'days': days,
            'link': url_for('credentials.detail_credential', id=secret.credential.id)
        })
    expirations['identity'].sort(key=lambda x: x['days'])
    
    # Certificates
    cert_versions = CertificateVersion.query.options(
        joinedload(CertificateVersion.certificate)
    ).filter(
        CertificateVersion.is_active == True,
        CertificateVersion.expires_at > today(),
        CertificateVersion.expires_at <= ninety_days
    ).all()
    for cv in cert_versions:
        days = (cv.expires_at - today()).days
        expirations['certificates'].append({
            'name': cv.certificate.name,
            'issuer': cv.issuer,
            'days': days,
            'link': url_for('certificates.certificate_detail', id=cv.certificate.id)
        })
    expirations['certificates'].sort(key=lambda x: x['days'])
    
    # Legal: Subscriptions & Licenses
    subscriptions = Subscription.query.filter_by(is_archived=False).all()
    for sub in subscriptions:
        next_renewal = sub.next_renewal_date
        if next_renewal and today() <= next_renewal <= ninety_days:
            days = (next_renewal - today()).days
            expirations['legal'].append({
                'name': sub.name,
                'cost': sub.cost_eur,
                'days': days,
                'link': url_for('subscriptions.subscription_detail', id=sub.id)
            })
    
    licenses = License.query.filter(
        License.expiry_date > today(),
        License.expiry_date <= ninety_days
    ).all()
    for lic in licenses:
        days = (lic.expiry_date - today()).days
        expirations['legal'].append({
            'name': lic.name,
            'cost': None,
            'days': days,
            'link': url_for('licenses.detail', id=lic.id)
        })
    expirations['legal'].sort(key=lambda x: x['days'])
    
    # ----- COUNTS -----
    critical_count = len(critical_items)
    warning_count = sum(1 for v in expirations.values() for item in v if item['days'] <= 30)
    expiring_count = sum(len(v) for v in expirations.values())

    # ----- UNIFIED COMPLIANCE TASK LIST (prioritized) -----
    # Critical/expired items first (already due), then upcoming expirations by soonest.
    compliance_tasks = []
    for item in critical_items:
        compliance_tasks.append({
            'category': item['type'],
            'severity': item['severity'],
            'title': item['title'],
            'meta': item['description'],
            'days': None,
            'link': item['link'],
        })
    for category, items in expirations.items():
        for it in items:
            compliance_tasks.append({
                'category': category,
                'severity': 'warning' if it['days'] <= 30 else 'info',
                'title': it['name'],
                'meta': it.get('meta') or it.get('type') or it.get('issuer')
                        or ('€%.2f' % it['cost'] if it.get('cost') else ''),
                'days': it['days'],
                'link': it['link'],
            })
    # Already-due items (days is None) first, then ascending by days remaining.
    compliance_tasks.sort(key=lambda t: (1, t['days']) if t['days'] is not None else (0, 0))

    # ----- UPCOMING SECURITY ACTIVITIES (due within 30 days, incl. overdue) -----
    from ..models.activities import SecurityActivity
    upcoming_activities = []
    for activity in SecurityActivity.query.all():
        days = activity.days_until_due
        if days is None or days > 30:
            continue
        upcoming_activities.append({
            'name': activity.name,
            'frequency': activity.frequency,
            'days': days,
            'last_execution': activity.last_execution_date,
            'link': url_for('activities.activity_detail', id=activity.id),
        })
    # Soonest first (most overdue at the top), through to +30 days.
    upcoming_activities.sort(key=lambda a: a['days'])
    
    # ----- OPS SUMMARY -----
    unhealthy_statuses = ['In Repair', 'Awaiting Disposal', 'Disposed', 'Sold']
    active_assets = Asset.query.filter(
        Asset.is_archived == False,
        Asset.status != 'Decommissioned'
    ).all()
    total_assets = len(active_assets)
    healthy_assets = sum(1 for a in active_assets if a.status not in unhealthy_statuses)
    assets_under_warranty = sum(
        1 for a in active_assets
        if a.warranty_end_date and a.warranty_end_date >= current_date
    )
    asset_health = int((healthy_assets / total_assets * 100) if total_assets > 0 else 100)

    # Spend projection: subscription renewals landing in the current calendar month.
    # Uses the same helper as the Ops & Finance dashboard so the two figures match.
    month_start = current_date.replace(day=1)
    month_end = month_start + relativedelta(months=1, days=-1)
    month_renewals = renewal_occurrences_in_range(subscriptions, month_start, month_end)
    projected_spend = sum(sub.cost_eur for _, sub in month_renewals)

    ops_summary = {
        'projected_spend': projected_spend,
        'asset_health': asset_health,
        'healthy_assets': healthy_assets,
        'total_assets': total_assets,
        'assets_under_warranty': assets_under_warranty,
        'active_subscriptions': len(subscriptions),
    }
    
    # ----- COMPLIANCE SUMMARY -----
    # Use the same real-time evaluator as the Compliance dashboard so the figures
    # match the page the "View Compliance Dashboard" button links to.
    from src.services.compliance_service import get_compliance_evaluator
    evaluator = get_compliance_evaluator()
    active_frameworks = Framework.query.filter_by(is_active=True).order_by(Framework.name).all()

    agg = {'total': 0, 'compliant': 0, 'warning': 0, 'non_compliant': 0,
           'manual': 0, 'uncovered': 0, 'not_applicable': 0}
    framework_scores = []
    for fw in active_frameworks:
        status = evaluator.get_framework_status(fw.id)
        if not status:
            continue
        stats = status['stats']
        for key in agg:
            agg[key] += stats.get(key, 0)
        applicable = stats['total'] - stats.get('not_applicable', 0)
        # "Covered" = anything with evidence (compliant / warning / non_compliant / manual).
        covered = stats['compliant'] + stats['manual']
        pct = int(round(covered / applicable * 100)) if applicable else 100
        framework_scores.append({
            'name': fw.name,
            'pct': pct,
            'covered': covered,
            'applicable': applicable,
        })

    applicable_controls = agg['total'] - agg['not_applicable']
    covered_controls = agg['compliant'] + agg['manual']
    compliance_score = int(round(covered_controls / applicable_controls * 100)) if applicable_controls else 100
    at_risk_controls = agg['warning'] + agg['non_compliant']
    pending_audits = ComplianceAudit.query.filter(
        ComplianceAudit.status.in_(['Planned', 'Prep', 'Auditor Review'])
    ).count()

    compliance_summary = {
        'score': compliance_score,
        'compliant_controls': covered_controls,
        'total_controls': applicable_controls,
        'at_risk_controls': at_risk_controls,
        'uncovered_controls': agg['uncovered'],
        'pending_audits': pending_audits,
        'frameworks': framework_scores,
    }
    
    # Get user modules and role for template permissions check
    allowed_modules = get_user_modules(user_id)
    current_user_role = user.role if user else None

    return render_template(
        'organizational_health.html',
        today=today(),
        health_score=health_score,
        global_status=global_status,
        critical_risks=critical_risks,
        high_risks=high_risks,
        critical_items=critical_items,
        critical_count=critical_count,
        warning_count=warning_count,
        expiring_count=expiring_count,
        compliance_tasks=compliance_tasks,
        upcoming_activities=upcoming_activities,
        expirations=expirations,
        ops_summary=ops_summary,
        compliance_summary=compliance_summary,
        allowed_modules=allowed_modules,
        current_user_role=current_user_role
    )


def get_action_required_alerts(user):
    """Build the 'Action Required' alert list for a user.

    Shared by the global navbar bell (via context processor) and the personal
    dashboard. Risks are intentionally excluded: they follow a periodic (annual)
    review cadence rather than being immediate-action items.
    """
    from ..models.policy import PolicyVersion
    from ..models.training import CourseAssignment

    alerts = []
    if not user:
        return alerts

    current_date = today()

    # Overdue policy acknowledgements (Active versions the user must acknowledge)
    pending_policies = PolicyVersion.query.filter(
        PolicyVersion.users_to_acknowledge.contains(user),
        PolicyVersion.status == 'Active'
    ).all()
    for policy in pending_policies:
        deadline = getattr(policy, 'acknowledgement_deadline', None)
        if deadline and (deadline - current_date).days <= 0:
            alerts.append({
                'icon': '📋',
                'message': f'Policy "{policy.policy.title}" requires urgent approval',
                'link': url_for('policies.acknowledge_version', id=policy.id),
                'action_text': 'Approve now'
            })

    # Courses due within the next 3 days (and not yet completed)
    for ca in CourseAssignment.query.filter_by(user_id=user.id).all():
        if ca.completion is None and ca.due_date:
            days_left = (ca.due_date - current_date).days
            if 0 <= days_left <= 3:
                alerts.append({
                    'icon': '📚',
                    'message': f'Course "{ca.course.title}" due in {days_left} day(s)',
                    'link': url_for('training.course_detail', id=ca.course_id),
                    'action_text': 'Continue course'
                })

    # Overdue maintenance on the user's assets (single grouped query, no N+1)
    my_assets = Asset.query.filter_by(user_id=user.id, is_archived=False).all()
    if my_assets:
        asset_by_id = {a.id: a for a in my_assets}
        overdue_logs = MaintenanceLog.query.filter(
            MaintenanceLog.asset_id.in_(list(asset_by_id.keys())),
            MaintenanceLog.status.in_(['Open', 'In Progress']),
            MaintenanceLog.event_date < current_date
        ).all()
        counts = {}
        for log in overdue_logs:
            counts[log.asset_id] = counts.get(log.asset_id, 0) + 1
        for asset_id, count in counts.items():
            asset = asset_by_id[asset_id]
            alerts.append({
                'icon': '🔧',
                'message': f'{asset.name} has {count} overdue maintenance(s)',
                'link': url_for('assets.asset_detail', id=asset.id),
                'action_text': 'View details'
            })

    return alerts


@main_bp.route('/my-dashboard')
@login_required
def my_dashboard():
    """Personal Dashboard - Self-service portal for employees."""
    from ..models.policy import PolicyVersion
    from ..models.training import CourseAssignment
    from ..models.services import BusinessService
    from ..models.security import Risk

    user_id = session.get('user_id')
    user = db.session.get(User,user_id)
    current_date = today()
    current_datetime = now()

    # ----- GREETING -----
    hour = now().hour
    if hour < 12:
        greeting_time = "Good morning"
    elif hour < 20:
        greeting_time = "Good afternoon"
    else:
        greeting_time = "Good evening"

    # ----- MY EQUIPMENT -----
    my_assets = Asset.query.filter_by(user_id=user_id, is_archived=False).all()
    my_peripherals = Peripheral.query.filter_by(user_id=user_id, is_archived=False).all()
    my_equipment_count = len(my_assets) + len(my_peripherals)

    # Check for maintenance issues
    maintenance_issues = []
    for asset in my_assets:
        overdue_logs = MaintenanceLog.query.filter(
            MaintenanceLog.asset_id == asset.id,
            MaintenanceLog.status.in_(['Open', 'In Progress']),
            MaintenanceLog.event_date < current_date
        ).all()
        if overdue_logs:
            maintenance_issues.append({
                'asset': asset,
                'count': len(overdue_logs)
            })

    # ----- MY LICENSES -----
    my_licenses = License.query.filter_by(user_id=user_id, is_archived=False).all()
    my_licenses_count = len(my_licenses)

    # Licenses expiring soon (30 days)
    thirty_days = current_date + timedelta(days=30)
    licenses_expiring_soon = sum(1 for lic in my_licenses
                                  if lic.expiry_date and current_date <= lic.expiry_date <= thirty_days)

    # ----- MY COURSES -----
    my_course_assignments = CourseAssignment.query.filter_by(user_id=user_id).all()
    courses_completed = sum(1 for ca in my_course_assignments if ca.completion is not None)
    courses_total = len(my_course_assignments)
    course_completion_pct = int((courses_completed / courses_total * 100) if courses_total > 0 else 0)

    overdue_courses = [
        ca for ca in my_course_assignments
        if ca.completion is None and ca.due_date and ca.due_date < current_date
    ]

    # ----- MY RISKS -----
    my_risks = Risk.query.filter_by(owner_id=user_id).filter(Risk.status != 'Closed').all()
    my_risks_count = len(my_risks)

    critical_risks = sum(1 for risk in my_risks
                        if risk.residual_likelihood >= 4 and risk.residual_impact >= 4)

    # ----- MY SERVICES -----
    my_services = BusinessService.query.filter(
        BusinessService.users.contains(user)
    ).all()
    my_services_count = len(my_services)

    # ----- MY SUBSCRIPTIONS (subscriptions the user has access to) -----
    my_subscriptions = [s for s in user.access_subscriptions if not s.is_archived]
    my_subscriptions_count = len(my_subscriptions)

    # ----- PENDING POLICIES -----
    pending_policies = PolicyVersion.query.filter(
        PolicyVersion.users_to_acknowledge.contains(user),
        PolicyVersion.status == 'Active'
    ).all()

    # ----- PENDING CREDENTIALS (those expiring soon shared with me) -----
    from ..models.credentials import CredentialSecret, Credential
    expiring_credentials = []
    try:
        # Get credentials where user has access
        thirty_days_ahead = current_datetime + timedelta(days=30)
        secrets = CredentialSecret.query.filter(
            CredentialSecret.is_active == True,
            CredentialSecret.expires_at.isnot(None),
            CredentialSecret.expires_at <= thirty_days_ahead
        ).all()

        # Filter those where user has access (simplified - can be enhanced)
        for secret in secrets:
            expiring_credentials.append({
                'credential': secret.credential,
                'expires_at': secret.expires_at,
                'days_left': (secret.expires_at.date() - current_date).days
            })
    except Exception:
        pass  # Credentials module might not be available

    # ----- PERSONAL HEALTH SCORE -----
    personal_health_score = 100

    # Penalize for pending items
    personal_health_score -= len(pending_policies) * 10
    personal_health_score -= len(overdue_courses) * 15
    personal_health_score -= len(expiring_credentials) * 10
    personal_health_score -= critical_risks * 15
    personal_health_score -= len(maintenance_issues) * 5

    personal_health_score = max(0, personal_health_score)

    # ----- CRITICAL ALERTS -----
    # Same data as the global navbar bell — see get_action_required_alerts().
    critical_alerts = get_action_required_alerts(user)

    # ----- PRIORITIZED TASKS -----
    prioritized_tasks = []

    # 1. Pending policies (highest priority)
    for policy in pending_policies:
        days_left = 999
        deadline = getattr(policy, 'acknowledgement_deadline', None)
        if deadline:
            days_left = (deadline - current_date).days

        urgency_class = 'urgent' if days_left <= 1 else ('warning' if days_left <= 7 else 'normal')
        urgency_icon = '🔴' if days_left == 0 else ('🟡' if days_left <= 7 else '🟢')
        urgency_label = 'URGENT' if days_left == 0 else ('Soon' if days_left <= 7 else 'Pending')

        prioritized_tasks.append({
            'priority': 1 if days_left <= 1 else 2,
            'urgency_class': urgency_class,
            'urgency_icon': urgency_icon,
            'urgency_label': urgency_label,
            'due_text': 'Due today' if days_left == 0 else (f'Due in {days_left} days' if days_left < 999 else 'No deadline'),
            'title': f'Approve Policy: {policy.policy.title}',
            'description': policy.policy.description or 'Requires your approval',
            'action_url': url_for('policies.acknowledge_version', id=policy.id),
            'action_text': 'Review & Approve',
            'can_dismiss': False
        })

    # 2. Overdue/expiring courses
    for ca in my_course_assignments:
        if ca.completion is None and ca.due_date:
            days_left = (ca.due_date - current_date).days
            if days_left <= 30:  # Only show if due within 30 days
                urgency_class = 'urgent' if days_left < 0 else ('warning' if days_left <= 7 else 'normal')
                urgency_icon = '🔴' if days_left < 0 else ('🟡' if days_left <= 7 else '🟢')
                urgency_label = 'URGENT' if days_left < 0 else ('Soon' if days_left <= 7 else 'Pending')

                prioritized_tasks.append({
                    'priority': 1 if days_left < 0 else (2 if days_left <= 7 else 3),
                    'urgency_class': urgency_class,
                    'urgency_icon': urgency_icon,
                    'urgency_label': urgency_label,
                    'due_text': f'Overdue by {abs(days_left)} days' if days_left < 0 else f'Due in {days_left} days',
                    'title': f'Complete Course: {ca.course.title}',
                    'description': f'Not completed yet · assigned {ca.assigned_date}',
                    'action_url': url_for('training.course_detail', id=ca.course_id),
                    'action_text': 'Continue course',
                    'can_dismiss': True
                })

    # 3. Expiring credentials
    for cred in expiring_credentials[:3]:  # Top 3 only
        days_left = cred['days_left']
        urgency_class = 'urgent' if days_left <= 7 else 'warning'
        urgency_icon = '🔴' if days_left <= 7 else '🟡'

        prioritized_tasks.append({
            'priority': 2 if days_left <= 7 else 3,
            'urgency_class': urgency_class,
            'urgency_icon': urgency_icon,
            'urgency_label': 'URGENT' if days_left <= 7 else 'Soon',
            'due_text': f'Expires in {days_left} days',
            'title': f'Update credential: {cred["credential"].name}',
            'description': f'Type: {cred["credential"].type}',
            'action_url': url_for('credentials.detail_credential', id=cred["credential"].id),
            'action_text': 'Update',
            'can_dismiss': True
        })

    # Sort by priority
    prioritized_tasks.sort(key=lambda x: (x['priority'], x['due_text']))

    # ----- NOTIFICATION COUNT -----
    notification_count = len(critical_alerts)

    # ----- ACHIEVEMENTS DATA -----
    # Calculate incident-free days (simplified)
    incident_free_days = 90  # Placeholder - would need actual calculation

    return render_template(
        'my_dashboard.html',
        user=user,
        timedelta=timedelta,
        greeting_time=greeting_time,
        current_date=current_date,
        current_date_pretty=current_date.strftime('%d de %B, %Y'),

        # Stats
        my_equipment_count=my_equipment_count,
        my_assets_count=len(my_assets),
        my_peripherals_count=len(my_peripherals),
        my_licenses_count=my_licenses_count,
        licenses_expiring_soon=licenses_expiring_soon,
        courses_completed=courses_completed,
        courses_total=courses_total,
        course_completion_pct=course_completion_pct,
        my_risks_count=my_risks_count,
        critical_risks=critical_risks,
        my_services_count=my_services_count,
        my_subscriptions_count=my_subscriptions_count,
        personal_health_score=personal_health_score,

        # Alerts & Tasks
        critical_alerts=critical_alerts,
        notification_count=notification_count,
        prioritized_tasks=prioritized_tasks,
        total_tasks=len(prioritized_tasks),
        pending_tasks=len([t for t in prioritized_tasks if t['priority'] <= 2]),

        # Tab data
        my_assets=my_assets,
        my_peripherals=my_peripherals,
        my_licenses=my_licenses,
        my_services=my_services,
        my_subscriptions=my_subscriptions,
        my_risks=my_risks,
        maintenance_issues=maintenance_issues,

        # Counts for quick actions
        courses_pending=len([ca for ca in my_course_assignments if ca.completion is None]),

        # Achievements
        incident_free_days=incident_free_days
    )


@main_bp.route('/operations')
@login_required
def ops_finance_dashboard():
    # --- STAT CARD COUNTS ---
    stats = {
        'subscriptions': Subscription.query.filter_by(is_archived=False).count(),
        'assets': Asset.query.filter_by(is_archived=False).count(),
        'peripherals': Peripheral.query.filter_by(is_archived=False).count(),
        'suppliers': Supplier.query.filter_by(is_archived=False).count(),
        'users': User.query.filter_by(is_archived=False).count(),
        'locations': Location.query.filter_by(is_archived=False).count(),
        'contacts': Contact.query.filter_by(is_archived=False).count(),
        'payment_methods': PaymentMethod.query.filter_by(is_archived=False).count(),
    }

    # --- Upcoming Renewals & Filter Logic ---
    period = request.args.get('period', '30', type=str)
    current_date = today()

    if period == '7':
        start_date, end_date = current_date, current_date + timedelta(days=7)
    elif period == '90':
        start_date, end_date = current_date, current_date + timedelta(days=90)
    elif period == 'current_month':
        start_date = current_date.replace(day=1)
        end_date = start_date + relativedelta(months=+1, days=-1)
    elif period == 'next_month':
        start_date = (current_date.replace(day=1) + relativedelta(months=+1))
        end_date = start_date + relativedelta(months=+1, days=-1)
    else:
        period = '30'
        start_date, end_date = current_date, current_date + timedelta(days=30)

    all_active_subscriptions = Subscription.query.filter_by(is_archived=False).all()
    upcoming_renewals = renewal_occurrences_in_range(all_active_subscriptions, start_date, end_date)
    total_cost = sum(subscription.cost_eur for _, subscription in upcoming_renewals)
    upcoming_renewals.sort(key=lambda x: x[0])

    # --- Forecast Chart Logic ---
    forecast_start_date = current_date.replace(day=1)
    end_of_forecast_period = forecast_start_date + relativedelta(months=+13)

    forecast_labels, forecast_keys, forecast_costs = [], [], {}
    for i in range(13):
        month_date = forecast_start_date + relativedelta(months=+i)
        year_month_key = month_date.strftime('%Y-%m')
        forecast_labels.append(month_date.strftime('%b %Y'))
        forecast_keys.append(year_month_key)
        forecast_costs[year_month_key] = 0

    for subscription in all_active_subscriptions:
        if not subscription.auto_renew:
            continue
        renewal = subscription.renewal_date
        # Find first renewal within or after forecast start
        while renewal < forecast_start_date:
            renewal = subscription.get_renewal_date_after(renewal)
        
        while renewal < end_of_forecast_period:
            year_month_key = renewal.strftime('%Y-%m')
            if year_month_key in forecast_costs:
                forecast_costs[year_month_key] += subscription.cost_eur
            renewal = subscription.get_renewal_date_after(renewal)

    forecast_data = [round(cost, 2) for cost in forecast_costs.values()]

    # --- CORRECTED: EXPIRING ITEMS LOGIC ---
    thirty_days_from_now = current_date + timedelta(days=30)
    
    # Query only non-archived items with warranty info
    expiring_assets = Asset.query.filter(
        Asset.is_archived == False,
        Asset.purchase_date.isnot(None), 
        Asset.warranty_length.isnot(None)
    ).all()
    expiring_peripherals = Peripheral.query.filter(
        Peripheral.is_archived == False,
        Peripheral.purchase_date.isnot(None), 
        Peripheral.warranty_length.isnot(None)
    ).all()
    
    all_expiring_items = [
        item for item in expiring_assets + expiring_peripherals 
        if item.warranty_end_date and current_date <= item.warranty_end_date <= thirty_days_from_now
    ]
    all_expiring_items.sort(key=lambda x: x.warranty_end_date)

    # CORRECTED: Payment methods expiring in the next 90 days
    ninety_days_from_now = current_date + timedelta(days=90)
    expiring_payment_methods = []
    all_payment_methods = PaymentMethod.query.filter(
        PaymentMethod.is_archived == False,
        PaymentMethod.expiry_date.isnot(None)
    ).order_by(PaymentMethod.expiry_date).all()

    for method in all_payment_methods:
        # Find the last day of the expiry month
        last_day_of_expiry_month = method.expiry_date.replace(day=calendar.monthrange(method.expiry_date.year, method.expiry_date.month)[1])
        if current_date <= last_day_of_expiry_month <= ninety_days_from_now:
            expiring_payment_methods.append(method)

    return render_template(
        'ops_finance_dashboard.html',
        stats=stats,
        upcoming_renewals=upcoming_renewals,
        total_cost=total_cost,
        selected_period=period,
        current_date=current_date,
        forecast_labels=forecast_labels,
        forecast_keys=forecast_keys,
        forecast_data=forecast_data,
        expiring_items=all_expiring_items,
        expiring_payment_methods=expiring_payment_methods
    )


@main_bp.route('/notifications', methods=['GET', 'POST'])
@login_required
def notification_settings():
    settings = NotificationSetting.query.first()
    if not settings:
        settings = NotificationSetting()
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        settings.email_enabled = 'email_enabled' in request.form
        settings.email_recipient = request.form.get('email_recipient')
        settings.webhook_enabled = 'webhook_enabled' in request.form
        settings.webhook_url = request.form.get('webhook_url')

        days_before = request.form.getlist('days_before')
        settings.notify_days_before = ','.join(days_before)

        db.session.commit()
        flash('Notification settings updated successfully!', 'success')
        return redirect(url_for('main.notification_settings'))

    notify_days_list = [int(day) for day in settings.notify_days_before.split(',') if day]

    return render_template(
        'notifications/settings.html',
        settings=settings,
        notify_days_list=notify_days_list
    )

@main_bp.route('/api/search')
@login_required
def search():
    query = request.args.get('q', '').strip()
    results = []

    if len(query) < 2:
        return jsonify([])

    search_term = f'%{query}%'
    limit = 5

    # Search Subscriptions
    subscriptions = Subscription.query.filter(Subscription.name.ilike(search_term), Subscription.is_archived == False).limit(limit).all()
    for item in subscriptions:
        results.append({
            'name': item.name,
            'type': 'Subscription',
            'url': url_for('subscriptions.subscription_detail', id=item.id)
        })

    # Search Assets
    assets = Asset.query.filter(
        or_(
            Asset.name.ilike(search_term),
            Asset.serial_number.ilike(search_term)
        ), Asset.is_archived == False
    ).limit(limit).all()
    for item in assets:
        results.append({
            'name': item.name,
            'type': 'Asset',
            'url': url_for('assets.asset_detail', id=item.id)
        })

    # Search Suppliers
    suppliers = Supplier.query.filter(Supplier.name.ilike(search_term), Supplier.is_archived == False).limit(limit).all()
    for item in suppliers:
        results.append({
            'name': item.name,
            'type': 'Supplier',
            'url': url_for('suppliers.supplier_detail', id=item.id)
        })

    # Search Contacts
    contacts = Contact.query.options(joinedload(Contact.supplier)).filter(Contact.name.ilike(search_term), Contact.is_archived == False).limit(limit).all()
    for item in contacts:
        results.append({
            'name': f"{item.name} ({item.supplier.name})",
            'type': 'Contact',
            'url': url_for('contacts.contact_detail', id=item.id)
        })
    
    # Search Purchases
    purchases = Purchase.query.filter(Purchase.description.ilike(search_term)).limit(limit).all()
    for item in purchases:
        results.append({
            'name': item.description,
            'type': 'Purchase',
            'url': url_for('purchases.purchase_detail', id=item.id)
        })

    # Search Peripherals
    peripherals = Peripheral.query.filter(
        or_(
            Peripheral.name.ilike(search_term),
            Peripheral.serial_number.ilike(search_term)
        ), Peripheral.is_archived == False
    ).limit(limit).all()
    for item in peripherals:
        results.append({
            'name': item.name,
            'type': 'Peripheral',
            'url': url_for('peripherals.edit_peripheral', id=item.id)
        })

    return jsonify(results)


@main_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    user = db.session.get(User,session['user_id'])
    
    # Detect if this is a forced password change
    default_admin_email = current_app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
    default_admin_password = current_app.config.get('DEFAULT_ADMIN_INITIAL_PASSWORD', 'admin123')
    forced_change = False
    
    if user and user.email == default_admin_email and user.check_password(default_admin_password):
        forced_change = True
    
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not user.check_password(current_password):
            flash('Your current password was incorrect.', 'danger')
        elif new_password != confirm_password:
            flash('The new passwords do not match.', 'danger')
        elif len(new_password) < 8:
            flash('The new password must be at least 8 characters long.', 'danger')
        else:
            user.set_password(new_password)
            db.session.commit()
            
            log_audit(
                event_type='security.password_change',
                action='update',
                target_object=f"User:{user.id}"
            )
            
            flash('Your password has been updated successfully!', 'success')
            return redirect(url_for('main.dashboard'))

    return render_template('change_password.html', forced_change=forced_change)


@main_bp.route('/my-api-key')
@login_required
def my_api_key():
    """Render the API Key management page for the current user."""
    return render_template('api_key.html')


@main_bp.route('/my-api-key/generate', methods=['POST'])
@login_required
def generate_my_token():
    """Generate a new API token for the current user."""
    user = db.session.get(User,session['user_id'])
    user.generate_token()
    db.session.commit()
    
    log_audit(
        event_type='security.token_generated',
        action='create',
        target_object=f"User:{user.id}",
        user_email=user.email,
        description="User generated their own API token"
    )
    
    flash('New API Token generated successfully.', 'success')
    return redirect(url_for('main.my_api_key'))


# --- INTERNAL ROUTES (Localhost Only) ---
# These routes are designed to be called by Flask CLI commands from within the container.
# Access is restricted to localhost to prevent external exposure.

LOCALHOST_ADDRS = {'127.0.0.1', '::1', 'localhost'}

def localhost_only(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.remote_addr not in LOCALHOST_ADDRS:
            abort(403)
        return f(*args, **kwargs)
    return decorated

@main_bp.route('/internal/test-db')
@localhost_only
def internal_test_db():
    """
    Internal route for database connectivity testing.
    Performs a simple query to verify database connection.
    """
    try:
        # Query the User table to verify database connectivity
        user_count = User.query.count()
        
        # Get database information
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')
        # Mask sensitive information in the URI
        if '@' in db_uri:
            # For postgres://user:pass@host/db format
            parts = db_uri.split('@')
            masked_uri = parts[0].split(':')[0] + ':***@' + '@'.join(parts[1:])
        else:
            masked_uri = db_uri
        
        is_postgres = current_app.config.get('IS_POSTGRES', False)
        db_type = 'PostgreSQL' if is_postgres else 'Unknown'

        return jsonify({
            'status': 'success',
            'message': 'Database connection successful',
            'database_type': db_type,
            'database_uri': masked_uri,
            'user_count': user_count,
            'query_executed': 'SELECT COUNT(*) FROM user'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': 'Database connection failed',
            'error': str(e)
        }), 500


@main_bp.route('/internal/app-info')
@localhost_only
def internal_app_info():
    """
    Internal route for retrieving application configuration information.
    Returns non-sensitive configuration details.
    """
    try:
        # Get database information
        db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')
        if '@' in db_uri:
            parts = db_uri.split('@')
            masked_uri = parts[0].split(':')[0] + ':***@' + '@'.join(parts[1:])
        else:
            masked_uri = db_uri
        
        is_postgres = current_app.config.get('IS_POSTGRES', False)
        db_type = 'PostgreSQL' if is_postgres else 'Unknown'

        # Gather application configuration
        app_info = {
            'status': 'success',
            'app_name': current_app.config.get('API_TITLE', 'OpsDeck'),
            'api_version': current_app.config.get('API_VERSION', 'v1'),
            'database': {
                'type': db_type,
                'uri': masked_uri,
                'track_modifications': current_app.config.get('SQLALCHEMY_TRACK_MODIFICATIONS', False)
            },
            'security': {
                'mfa_enabled': current_app.config.get('MFA_ENABLED', False),
                'secret_key_configured': bool(current_app.config.get('SECRET_KEY')),
                'testing_mode': current_app.config.get('TESTING', False)
            },
            'email': {
                'smtp_server': current_app.config.get('SMTP_SERVER', 'Not configured'),
                'smtp_port': current_app.config.get('SMTP_PORT', 'Not configured'),
                'email_configured': bool(current_app.config.get('EMAIL_USERNAME'))
            },
            'oauth': {
                'google_oauth_configured': bool(current_app.config.get('GOOGLE_OAUTH_CLIENT_ID'))
            },
            'paths': {
                'upload_folder': current_app.config.get('UPLOAD_FOLDER', 'Not configured')
            }
        }
        
        return jsonify(app_info), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': 'Failed to retrieve app info',
            'error': str(e)
        }), 500

@main_bp.route('/internal/test-email')
@localhost_only
def internal_test_email():
    """
    Internal route for testing email configuration.
    Sends a test email to verify SMTP settings.
    """
    try:
        recipient = request.args.get('recipient', current_app.config.get('EMAIL_USERNAME'))
        
        if not recipient:
            return jsonify({
                'status': 'error',
                'message': 'No recipient specified and EMAIL_USERNAME not configured'
            }), 400
        
        # Check if email is configured
        smtp_server = current_app.config.get('SMTP_SERVER')
        smtp_port = current_app.config.get('SMTP_PORT')
        email_username = current_app.config.get('EMAIL_USERNAME')
        email_password = current_app.config.get('EMAIL_PASSWORD')
        
        if not all([smtp_server, smtp_port, email_username, email_password]):
            return jsonify({
                'status': 'error',
                'message': 'Email not fully configured',
                'config': {
                    'smtp_server': bool(smtp_server),
                    'smtp_port': bool(smtp_port),
                    'email_username': bool(email_username),
                    'email_password': bool(email_password)
                }
            }), 400
        
        # Send test email
        subject = "OpsDeck - Test Email"
        body = f"""
        <h2>Email Configuration Test</h2>
        <p>This is a test email from OpsDeck to verify SMTP configuration.</p>
        <p><strong>Timestamp:</strong> {now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
        <p><strong>SMTP Server:</strong> {smtp_server}:{smtp_port}</p>
        <p>If you received this email, your email configuration is working correctly.</p>
        """
        
        notifications.send_email(
            current_app._get_current_object(),
            subject,
            body,
            [recipient]
        )
        
        return jsonify({
            'status': 'success',
            'message': 'Test email sent successfully',
            'recipient': recipient,
            'smtp_server': smtp_server,
            'smtp_port': smtp_port
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': 'Failed to send test email',
            'error': str(e)
        }), 500


@main_bp.route('/internal/health-check')
@localhost_only
def internal_health_check():
    """
    Internal route for comprehensive health check.
    Tests database, storage, scheduler, and email configuration.
    """
    health_status = {
        'status': 'healthy',
        'timestamp': now().isoformat(),
        'components': {}
    }
    
    all_healthy = True
    
    # 1. Database Check
    try:
        user_count = User.query.count()
        health_status['components']['database'] = {
            'status': 'healthy',
            'type': 'PostgreSQL' if current_app.config.get('IS_POSTGRES') else 'SQLite',
            'user_count': user_count
        }
    except Exception as e:
        all_healthy = False
        health_status['components']['database'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
    
    # 2. File Storage Check
    try:
        upload_folder = current_app.config.get('UPLOAD_FOLDER')
        if upload_folder and os.path.exists(upload_folder):
            # Test write permissions
            test_file = os.path.join(upload_folder, '.health_check_test')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            
            health_status['components']['storage'] = {
                'status': 'healthy',
                'upload_folder': upload_folder,
                'writable': True
            }
        else:
            all_healthy = False
            health_status['components']['storage'] = {
                'status': 'unhealthy',
                'error': 'Upload folder does not exist',
                'upload_folder': upload_folder
            }
    except Exception as e:
        all_healthy = False
        health_status['components']['storage'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
    
    # 3. Scheduler Check (only if not in testing mode)
    if not current_app.config.get('TESTING'):
        health_status['components']['scheduler'] = {
            'status': 'configured',
            'note': 'Scheduler is enabled (not in testing mode)'
        }
    else:
        health_status['components']['scheduler'] = {
            'status': 'disabled',
            'note': 'Scheduler disabled in testing mode'
        }
    
    # 4. Email Configuration Check
    smtp_server = current_app.config.get('SMTP_SERVER')
    smtp_port = current_app.config.get('SMTP_PORT')
    email_username = current_app.config.get('EMAIL_USERNAME')
    email_password = current_app.config.get('EMAIL_PASSWORD')
    
    if all([smtp_server, smtp_port, email_username, email_password]):
        health_status['components']['email'] = {
            'status': 'configured',
            'smtp_server': smtp_server,
            'smtp_port': smtp_port
        }
    else:
        health_status['components']['email'] = {
            'status': 'not_configured',
            'note': 'Email settings incomplete'
        }
    
    # Set overall status
    if not all_healthy:
        health_status['status'] = 'unhealthy'
        return jsonify(health_status), 503
    
    return jsonify(health_status), 200


@main_bp.route('/internal/test-security')
@localhost_only
def internal_test_security():
    """
    Internal route for security configuration audit.
    Checks security settings and provides recommendations.
    """
    audit_results = {
        'status': 'success',
        'timestamp': now().isoformat(),
        'checks': {},
        'warnings': [],
        'recommendations': []
    }
    
    # 1. Check SECRET_KEY
    secret_key = current_app.config.get('SECRET_KEY', '')
    if secret_key in ['your-secret-key-change-this', 'dev', 'development', '']:
        audit_results['checks']['secret_key'] = {
            'status': 'warning',
            'message': 'Using default or weak SECRET_KEY'
        }
        audit_results['warnings'].append('SECRET_KEY is using a default or weak value')
        audit_results['recommendations'].append('Set a strong SECRET_KEY in environment variables')
    elif len(secret_key) < 32:
        audit_results['checks']['secret_key'] = {
            'status': 'warning',
            'message': 'SECRET_KEY is too short (< 32 characters)'
        }
        audit_results['warnings'].append('SECRET_KEY should be at least 32 characters')
    else:
        audit_results['checks']['secret_key'] = {
            'status': 'ok',
            'message': 'SECRET_KEY is configured properly'
        }
    
    # 2. Check MFA
    mfa_enabled = current_app.config.get('MFA_ENABLED', False)
    audit_results['checks']['mfa'] = {
        'status': 'info',
        'enabled': mfa_enabled,
        'message': 'MFA is enabled' if mfa_enabled else 'MFA is disabled'
    }
    if not mfa_enabled:
        audit_results['recommendations'].append('Consider enabling MFA for enhanced security')
    
    # 3. Check HTTPS/Talisman
    is_development = current_app.debug or os.environ.get('FLASK_ENV') == 'development'
    audit_results['checks']['https'] = {
        'status': 'info',
        'force_https': not is_development,
        'message': 'HTTPS enforced' if not is_development else 'HTTPS not enforced (development mode)'
    }
    
    # 4. Check CSRF Protection
    csrf_enabled = 'csrf' in current_app.extensions
    audit_results['checks']['csrf'] = {
        'status': 'ok' if csrf_enabled else 'warning',
        'enabled': csrf_enabled,
        'message': 'CSRF protection enabled' if csrf_enabled else 'CSRF protection not found'
    }
    if not csrf_enabled:
        audit_results['warnings'].append('CSRF protection is not enabled')
    
    # 5. Check for default admin password
    default_admin_email = current_app.config.get('DEFAULT_ADMIN_EMAIL', 'admin@example.com')
    default_admin_password = current_app.config.get('DEFAULT_ADMIN_INITIAL_PASSWORD', 'admin123')
    
    try:
        admin_user = User.query.filter_by(email=default_admin_email).first()
        if admin_user and admin_user.check_password(default_admin_password):
            audit_results['checks']['default_admin'] = {
                'status': 'critical',
                'message': 'Default admin password is still in use'
            }
            audit_results['warnings'].append('CRITICAL: Default admin password has not been changed')
            audit_results['recommendations'].append('Change the default admin password immediately')
        else:
            audit_results['checks']['default_admin'] = {
                'status': 'ok',
                'message': 'Default admin password has been changed or admin user not found'
            }
    except Exception as e:
        audit_results['checks']['default_admin'] = {
            'status': 'error',
            'message': f'Could not check admin password: {str(e)}'
        }
    
    # 6. Check database type
    is_postgres = current_app.config.get('IS_POSTGRES', False)
    audit_results['checks']['database'] = {
        'status': 'ok' if is_postgres else 'warning',
        'type': 'PostgreSQL' if is_postgres else 'Unknown',
        'message': 'Using PostgreSQL' if is_postgres else 'PostgreSQL is required for production'
    }
    if not is_postgres and not is_development:
        audit_results['recommendations'].append('PostgreSQL is required for production deployments')
    
    # Calculate security score
    critical_issues = len([w for w in audit_results['warnings'] if 'CRITICAL' in w])
    warnings = len(audit_results['warnings']) - critical_issues
    
    audit_results['summary'] = {
        'critical_issues': critical_issues,
        'warnings': warnings,
        'recommendations': len(audit_results['recommendations'])
    }
    
    return jsonify(audit_results), 200
