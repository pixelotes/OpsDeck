"""Pull-based user sync from Microsoft Entra ID (Microsoft Graph).

OpsDeck reads the transitive members of one or more Entra groups and reconciles its
own users against them:

* users are matched by Entra object id (``User.entra_oid``) and, the first time, by
  ``userPrincipalName`` against ``User.email`` (``mail`` is never used, for the same
  reason as in the SSO callback: it is admin-editable and unverified);
* missing users are created with the configured default role and no password;
* name, department, job title and manager are kept up to date;
* Entra-linked users that left the scope (or were disabled) are archived, never
  deleted, and unarchived if they come back. Users that were never linked to Entra
  (local accounts such as the break-glass admin) are never touched.

Everything goes through :func:`build_plan`, which only reads, and :func:`apply_plan`,
which writes. Dry runs stop after the first. A run that cannot read every configured
group aborts before planning, so a Graph outage can never look like "everyone left".

Credentials come from the AZURE_OAUTH_* environment variables (the same app
registration as "Sign in with Microsoft") and need the *application* permissions
``User.Read.All`` and ``GroupMember.Read.All`` with admin consent.
"""
import hashlib
import json
import logging
from contextlib import contextmanager

import requests
from flask import current_app
from sqlalchemy import func, text

from ..extensions import db
from ..models import User
from ..models.entra import EntraSyncRun, EntraSyncSettings, SCHEDULE_DAILY, SCHEDULE_INTERVAL
from src.utils.logger import log_audit
from src.utils.timezone_helper import now

logger = logging.getLogger(__name__)

GRAPH = 'https://graph.microsoft.com/v1.0'
USER_SELECT = 'id,displayName,userPrincipalName,department,jobTitle,accountEnabled'
SCHEDULER_JOB_ID = 'entra_user_sync'
SCHEDULER_REFRESH_JOB_ID = 'entra_user_sync_refresh'
REQUEST_TIMEOUT = 30
# Arbitrary constant identifying the sync's Postgres advisory lock.
ADVISORY_LOCK_KEY = 0x0E7A5C


class EntraSyncError(Exception):
    """The sync could not run (configuration, credentials or Graph failure)."""


class SyncAborted(Exception):
    """The safety brake stopped a run before it changed anything."""


# --------------------------------------------------------------------------- #
# Microsoft Graph client (client-credentials flow)
# --------------------------------------------------------------------------- #

def credentials_configured(config=None):
    from src import azure_oauth_configured
    config = config or current_app.config
    return azure_oauth_configured(config) and bool(config.get('AZURE_OAUTH_CLIENT_SECRET'))


class GraphClient:
    """Minimal Graph client for the few read-only calls the sync makes."""

    def __init__(self, tenant_id, client_id, client_secret, session=None):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = session or requests.Session()
        self._token = None

    @classmethod
    def from_config(cls, config=None):
        config = config or current_app.config
        if not credentials_configured(config):
            raise EntraSyncError(
                'Entra ID credentials are not configured (AZURE_OAUTH_CLIENT_ID, '
                'AZURE_OAUTH_CLIENT_SECRET and a single-tenant AZURE_OAUTH_TENANT_ID).'
            )
        return cls(config['AZURE_OAUTH_TENANT_ID'].strip(), config['AZURE_OAUTH_CLIENT_ID'],
                   config['AZURE_OAUTH_CLIENT_SECRET'])

    def _get_token(self):
        if self._token:
            return self._token
        resp = self.http.post(
            f'https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'scope': 'https://graph.microsoft.com/.default',
            },
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            raise EntraSyncError(f'Could not obtain a Graph token (HTTP {resp.status_code}).')
        self._token = resp.json().get('access_token')
        return self._token

    def get(self, url, params=None, allow_404=False):
        if not url.startswith('https://'):
            url = GRAPH + url
        resp = self.http.get(url, params=params, timeout=REQUEST_TIMEOUT,
                             headers={'Authorization': f'Bearer {self._get_token()}'})
        if allow_404 and resp.status_code == 404:
            return None
        if not resp.ok:
            raise EntraSyncError(f'Microsoft Graph error {resp.status_code} for {url.split("?")[0]}')
        return resp.json()

    def group_users(self, group_id):
        """All users that are transitive members of ``group_id`` (pagination followed)."""
        users = []
        url = f'/groups/{group_id}/transitiveMembers'
        params = {'$select': USER_SELECT, '$top': 999}
        while url:
            page = self.get(url, params=params)
            params = None  # nextLink already carries the query
            for member in page.get('value', []):
                if member.get('@odata.type') == '#microsoft.graph.user':
                    users.append(member)
            url = page.get('@odata.nextLink')
        return users

    def manager_id(self, user_id):
        data = self.get(f'/users/{user_id}/manager', params={'$select': 'id'}, allow_404=True)
        return data.get('id') if data else None


def fetch_scope(graph, group_ids):
    """Return {oid: entra_user} for every enabled user in the configured groups.

    Raises EntraSyncError if any group cannot be read: a partial view of the scope
    would otherwise archive everyone in the missing group.
    """
    if not group_ids:
        raise EntraSyncError('No Entra group ids are configured.')
    scope = {}
    for group_id in group_ids:
        for member in graph.group_users(group_id):
            if member.get('accountEnabled') is False or not member.get('id'):
                continue
            scope[member['id']] = member
    for oid, member in scope.items():
        member['managerId'] = graph.manager_id(oid)
    return scope


# --------------------------------------------------------------------------- #
# Planning (read-only) and applying
# --------------------------------------------------------------------------- #

def _change(action, user, member=None, fields=None):
    return {
        'action': action,
        'user_id': user.id if user else None,
        'oid': (member or {}).get('id') or (user.entra_oid if user else None),
        'upn': (member or {}).get('userPrincipalName') or (user.email if user else None),
        'name': (member or {}).get('displayName') or (user.name if user else None),
        'fields': fields or {},
    }


#: (User attribute, Graph property) pairs kept in sync for existing users.
SYNCED_FIELDS = (('name', 'displayName'), ('department', 'department'), ('job_title', 'jobTitle'))


class _PlanContext:
    """State shared by the planning helpers while one plan is built."""

    def __init__(self, scope, default_role):
        self.scope = scope
        self.default_role = default_role
        self.by_oid = {u.entra_oid: u for u in
                       User.query.filter(User.entra_oid.isnot(None)).order_by(User.id).all()}
        # oid -> OpsDeck user (existing) or None (to be created), for manager resolution.
        self.resolved = {}
        self.planned_emails = set()
        self.changes = []
        self.errors = []


def build_plan(scope, default_role='user'):
    """Compute the changes needed to reconcile OpsDeck users with ``scope``.

    Returns a dict with ``changes`` (create/update/unarchive/archive entries),
    ``errors`` (conflicts that were skipped) and ``linked_count`` (Entra-linked,
    non-archived users today, the base of the archive brake). Nothing is written.
    """
    ctx = _PlanContext(scope, default_role)
    for oid, member in sorted(scope.items(), key=lambda kv: (kv[1].get('userPrincipalName') or '').lower()):
        _plan_member(ctx, oid, member)
    for change in ctx.changes:
        _plan_manager(ctx, change)
    _plan_archives(ctx)

    changes = [c for c in ctx.changes if c['action'] != 'unchanged']
    linked_count = sum(1 for u in ctx.by_oid.values() if not u.is_archived)
    return {'changes': changes, 'errors': ctx.errors, 'linked_count': linked_count,
            'counts': _counts(changes)}


def _match_user(ctx, oid, upn):
    """Find the OpsDeck user for an Entra member: by oid, else by UPN.

    Returns (user, linked_by_upn, error).
    """
    user = ctx.by_oid.get(oid)
    if user is not None or not upn:
        return user, False, None
    user = User.query.filter(func.lower(User.email) == upn.lower()).first()
    if user is None:
        return None, False, None
    if user.entra_oid and user.entra_oid != oid:
        return None, False, 'Email already linked to a different Entra object id'
    return user, True, None


def _plan_member(ctx, oid, member):
    upn = (member.get('userPrincipalName') or '').strip()
    user, linked_by_upn, error = _match_user(ctx, oid, upn)
    if error:
        ctx.errors.append({'upn': upn, 'error': error})
        return
    if user is None:
        _plan_create(ctx, oid, member, upn)
        return

    ctx.resolved[oid] = user
    fields = {'entra_oid': [user.entra_oid, oid]} if linked_by_upn else {}
    fields.update(_field_diff(user, member))
    if user.is_archived:
        action = 'unarchive'
    else:
        action = 'update' if fields else 'unchanged'
    ctx.changes.append(_change(action, user, member, fields))


def _plan_create(ctx, oid, member, upn):
    if not upn or upn.lower() in ctx.planned_emails:
        ctx.errors.append({'upn': upn or oid, 'error': 'Missing or duplicate userPrincipalName'})
        return
    ctx.planned_emails.add(upn.lower())
    ctx.resolved[oid] = None
    ctx.changes.append(_change('create', None, member, {
        'email': [None, upn],
        'name': [None, member.get('displayName') or upn],
        'department': [None, member.get('department')],
        'job_title': [None, member.get('jobTitle')],
        'role': [None, ctx.default_role],
    }))


def _field_diff(user, member):
    fields = {}
    for attr, key in SYNCED_FIELDS:
        new = member.get(key)
        if attr == 'name' and not new:
            continue  # never blank a name
        old = getattr(user, attr)
        if (old or None) != (new or None):
            fields[attr] = [old, new]
    return fields


def _plan_manager(ctx, change):
    """Link the manager, only to users that are (or will be) in OpsDeck."""
    member = ctx.scope.get(change['oid']) if change['oid'] else None
    if not member:
        return
    current = ctx.resolved.get(change['oid'])
    current_manager = current.manager if current else None
    if current_manager and not current_manager.entra_oid:
        return  # manually set to a local-only user: leave it alone
    current_manager_oid = current_manager.entra_oid if current_manager else None

    manager_oid = member.get('managerId')
    if manager_oid not in ctx.resolved and manager_oid not in ctx.by_oid:
        manager_oid = None
    if manager_oid == current_manager_oid:
        return
    change['fields']['manager'] = [current_manager_oid, manager_oid]
    change['manager_display'] = [_name_of(current_manager_oid, ctx.scope, ctx.by_oid),
                                 _name_of(manager_oid, ctx.scope, ctx.by_oid)]
    if change['action'] == 'unchanged':
        change['action'] = 'update'


def _plan_archives(ctx):
    for oid, user in ctx.by_oid.items():
        if oid not in ctx.scope and not user.is_archived:
            ctx.changes.append(_change('archive', user))


def _name_of(oid, scope, by_oid):
    if not oid:
        return None
    if oid in scope:
        return scope[oid].get('displayName') or scope[oid].get('userPrincipalName')
    return by_oid[oid].name if oid in by_oid else oid


def _counts(changes):
    counts = {'create': 0, 'update': 0, 'archive': 0, 'unarchive': 0}
    for c in changes:
        counts[c['action']] += 1
    return counts


def plan_fingerprint(plan):
    """Stable hash of a plan, so a confirmed preview can be checked before applying."""
    payload = json.dumps(plan['changes'], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def check_archive_brake(plan, threshold_percent):
    """Raise SyncAborted if the plan would archive too many synced users."""
    to_archive = plan['counts']['archive']
    base = plan['linked_count']
    if to_archive and base and to_archive * 100 > base * threshold_percent:
        raise SyncAborted(
            f'Run would archive {to_archive} of {base} synced users, above the '
            f'{threshold_percent}% safety threshold. Nothing was changed.'
        )


ARCHIVE_STATE = {'archive': True, 'unarchive': False}


def apply_plan(plan):
    """Write ``plan`` to the database in one transaction."""
    by_oid = {change['oid']: _apply_user_change(change) for change in plan['changes']}
    db.session.flush()
    _apply_managers(plan, by_oid)
    db.session.commit()
    _audit_changes(plan, by_oid)


def _apply_user_change(change):
    if change['action'] == 'create':
        f = change['fields']
        user = User(email=f['email'][1], name=f['name'][1], department=f['department'][1],
                    job_title=f['job_title'][1], role=f['role'][1], entra_oid=change['oid'])
        db.session.add(user)
        return user
    user = db.session.get(User, change['user_id'])
    for attr in ('entra_oid', 'name', 'department', 'job_title'):
        if attr in change['fields']:
            setattr(user, attr, change['fields'][attr][1])
    if change['action'] in ARCHIVE_STATE:
        user.is_archived = ARCHIVE_STATE[change['action']]
    return user


def _apply_managers(plan, by_oid):
    for change in plan['changes']:
        if 'manager' not in change['fields']:
            continue
        manager_oid = change['fields']['manager'][1]
        manager = None
        if manager_oid:
            manager = by_oid.get(manager_oid) or User.query.filter_by(entra_oid=manager_oid).first()
        by_oid[change['oid']].manager = manager


def _audit_changes(plan, by_oid):
    for change in plan['changes']:
        user = by_oid[change['oid']]
        log_audit(
            event_type='user.entra_sync',
            action=change['action'],
            target_object=f'User:{user.id}',
            target_info=f'{user.name} ({user.email})',
            changes=json.dumps(change['fields'], default=str),
        )


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #

@contextmanager
def _run_lock():
    """Stop two workers (each gunicorn worker has its own scheduler) syncing at once."""
    if db.engine.dialect.name != 'postgresql':
        yield True
        return
    with db.engine.connect() as conn:
        acquired = conn.execute(text('SELECT pg_try_advisory_lock(:k)'), {'k': ADVISORY_LOCK_KEY}).scalar()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text('SELECT pg_advisory_unlock(:k)'), {'k': ADVISORY_LOCK_KEY})


def _recent_scheduled_run(minutes=10):
    from datetime import timedelta
    cutoff = now() - timedelta(minutes=minutes)
    return EntraSyncRun.query.filter(EntraSyncRun.trigger == 'scheduled',
                                     EntraSyncRun.started_at >= cutoff).first() is not None


def preview(graph=None):
    """Dry run: fetch the scope and build the plan without recording anything."""
    settings = EntraSyncSettings.get()
    if not settings.enabled:
        raise EntraSyncError('Entra ID sync is disabled.')
    graph = graph or GraphClient.from_config()
    scope = fetch_scope(graph, settings.group_id_list)
    plan = build_plan(scope, settings.default_role)
    plan['fingerprint'] = plan_fingerprint(plan)
    return plan


def run_sync(trigger, triggered_by=None, dry_run=False, graph=None, enforce_brake=None,
             expected_fingerprint=None):
    """Run the sync end to end and record it in EntraSyncRun.

    ``enforce_brake`` defaults to True for scheduled runs. ``expected_fingerprint``,
    when given, makes the run abort if the plan differs from the one the admin
    previewed. Returns the EntraSyncRun row, or None when a scheduled run was skipped
    because another worker already ran it.
    """
    settings = EntraSyncSettings.get()
    if enforce_brake is None:
        enforce_brake = trigger == 'scheduled'

    with _run_lock() as acquired:
        if _should_skip(acquired, trigger):
            return None
        run = EntraSyncRun(trigger=trigger, triggered_by=triggered_by, dry_run=dry_run, status='running')
        db.session.add(run)
        db.session.commit()
        plan = _execute(run, settings, graph, dry_run, enforce_brake, expected_fingerprint)

    _finish_run(run, plan)
    if run.status != 'success' and trigger == 'scheduled':
        notify_admins(run)
    return run


def _should_skip(acquired, trigger):
    """True if a scheduled run must be skipped; raises for a busy manual/CLI run.

    Every gunicorn worker runs its own scheduler: the first one to fire does the work
    and the others skip silently instead of recording a failure.
    """
    if acquired and not (trigger == 'scheduled' and _recent_scheduled_run()):
        return False
    if trigger == 'scheduled':
        return True
    raise EntraSyncError('Another Entra sync is already running.')


def _execute(run, settings, graph, dry_run, enforce_brake, expected_fingerprint):
    """Fetch, plan, check and (unless dry run) apply. Sets run.status; returns the plan."""
    plan = None
    try:
        if not settings.enabled:
            raise EntraSyncError('Entra ID sync is disabled.')
        scope = fetch_scope(graph or GraphClient.from_config(), settings.group_id_list)
        plan = build_plan(scope, settings.default_role)
        if expected_fingerprint and plan_fingerprint(plan) != expected_fingerprint:
            raise SyncAborted('Entra ID changed since the preview. Review the new preview and confirm again.')
        if not dry_run:
            if enforce_brake:
                check_archive_brake(plan, settings.archive_threshold_percent)
            apply_plan(plan)
        run.status = 'success'
    except SyncAborted as exc:
        db.session.rollback()
        run.status, run.error = 'aborted', str(exc)
    except Exception as exc:  # recorded on the run; the scheduler must not crash
        db.session.rollback()
        logger.exception('Entra ID sync failed')
        run.status, run.error = 'error', str(exc)
    return plan


def _finish_run(run, plan):
    if plan:
        counts = plan['counts']
        run.created_count, run.updated_count = counts['create'], counts['update']
        run.archived_count, run.unarchived_count = counts['archive'], counts['unarchive']
        run.changes_json = json.dumps({'changes': plan['changes'], 'errors': plan['errors']}, default=str)
    run.finished_at = now()
    db.session.commit()

    log_audit(
        event_type='integration.entra_sync',
        action='dry_run' if run.dry_run else 'sync',
        outcome='success' if run.status == 'success' else 'failure',
        target_object=f'EntraSyncRun:{run.id}',
        user_email=run.triggered_by,
        trigger=run.trigger,
        target_info=(f'{run.created_count} created, {run.updated_count} updated, '
                     f'{run.archived_count} archived, {run.unarchived_count} unarchived'),
        error_message=run.error,
    )


def notify_admins(run):
    """Email the configured notification recipient (or the admins) about a failed run."""
    from src import notifications
    from ..models import NotificationSetting

    setting = NotificationSetting.query.first()
    if setting and setting.email_recipient:
        recipients = [setting.email_recipient]
    else:
        recipients = [u.email for u in User.query.filter_by(role='admin', is_archived=False).all()]
    if not recipients:
        return
    body = (f'<p>The scheduled Microsoft Entra ID user sync did not complete '
            f'(status: <b>{run.status}</b>).</p><p>{run.error or ""}</p>'
            f'<p>Review it under Administration &gt; Entra ID Sync.</p>')
    notifications.send_email(current_app._get_current_object(),
                             'OpsDeck - Entra ID sync needs attention', body, recipients)


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #

def _scheduled_job(app):
    with app.app_context():
        settings = EntraSyncSettings.get()
        if settings.enabled and settings.schedule_mode in (SCHEDULE_DAILY, SCHEDULE_INTERVAL):
            run_sync('scheduled')


def configure_schedule(app, scheduler):
    """(Re-)register the sync job on ``scheduler`` according to the saved settings.

    Returns the registered job, or None when sync is disabled or unscheduled.
    """
    if scheduler.get_job(SCHEDULER_JOB_ID):
        scheduler.remove_job(SCHEDULER_JOB_ID)
    settings = EntraSyncSettings.get()
    app.extensions['entra_sync_schedule_stamp'] = _stamp(settings)
    if not settings.enabled:
        return None
    if settings.schedule_mode == SCHEDULE_DAILY:
        hour, minute = parse_daily_time(settings.daily_time)
        return scheduler.add_job(func=_scheduled_job, args=[app], trigger='cron', hour=hour,
                                 minute=minute, id=SCHEDULER_JOB_ID, replace_existing=True)
    if settings.schedule_mode == SCHEDULE_INTERVAL:
        return scheduler.add_job(func=_scheduled_job, args=[app], trigger='interval',
                                 hours=max(1, settings.interval_hours or 1),
                                 id=SCHEDULER_JOB_ID, replace_existing=True)
    return None


def _stamp(settings):
    return (settings.enabled, settings.schedule_mode, settings.daily_time, settings.interval_hours)


def refresh_schedule(app, scheduler):
    """Pick up schedule changes saved by another worker (cheap, runs every few minutes)."""
    with app.app_context():
        try:
            settings = EntraSyncSettings.get()
        except Exception:  # table not created yet (fresh install before migrations)
            db.session.rollback()
            return
        if app.extensions.get('entra_sync_schedule_stamp') != _stamp(settings):
            configure_schedule(app, scheduler)


def reschedule_current_app():
    """Re-register the job in this process after the settings were saved."""
    scheduler = current_app.extensions.get('opsdeck_scheduler')
    if scheduler is not None:
        configure_schedule(current_app._get_current_object(), scheduler)


def parse_daily_time(value):
    try:
        hour, minute = (int(p) for p in (value or '').split(':'))
    except ValueError:
        raise ValueError('Daily time must be HH:MM.')
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError('Daily time must be HH:MM.')
    return hour, minute
