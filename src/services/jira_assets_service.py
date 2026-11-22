"""One-way sync from Jira Service Management Assets into OpsDeck records.

A run fetches the objects a profile selects, builds a plan and (unless it is a dry
run) applies it in one transaction:

* **link**: an unlinked OpsDeck record that matches a Jira object (assets by serial
  number, suppliers by name) is bound to it;
* **create**: a Jira object with no OpsDeck record is imported, unless its status maps
  to "archive" (retired objects are not imported) or the profile only links;
* **update / archive / unarchive**: the state of linked records follows Jira. Only the
  state is synced (asset status and archived flag; supplier archived and critical
  flags); every other field belongs to OpsDeck after the import.

Linked records that no longer match the profile are reported, never changed: the
query may simply have been narrowed. Scheduled runs abort when they would archive more
than the profile's threshold of linked records.
"""
import hashlib
import json
import logging
from contextlib import contextmanager
from datetime import date, timedelta

from flask import current_app
from sqlalchemy import func, text

from ..extensions import db
from ..models import Asset, AssetHistory, AssetModel, Brand, Supplier, User
from ..models.jira_assets import (
    ACTION_ACTIVE, ACTION_ARCHIVE, ASSET_STATUSES, CRITICAL_YES, TARGET_ASSET, TARGET_SUPPLIER,
    JiraAssetsProfile, JiraAssetsRun,
)
from ..utils.logger import log_audit
from ..utils.timezone_helper import now
from .jira_assets_client import JiraAssetsClient, type_clause

logger = logging.getLogger(__name__)

ADVISORY_LOCK_BASE = 0x4A41_0000   # + profile id
SCHEDULER_LOCK_KEY = 0x4A41_FFFF
SCHEDULER_JOB_ID = 'jira_assets_sync'
SCHEDULER_INTERVAL_MINUTES = 15
MAX_WARNINGS = 200
ACTIONS = ('create', 'link', 'update', 'archive', 'unarchive')


class JiraAssetsSyncError(Exception):
    """The sync cannot run (disabled, misconfigured, busy)."""


class SyncAborted(Exception):
    """The run stopped before writing anything (safety threshold, plan changed)."""


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def build_aql(profile):
    clause = type_clause(profile.object_type)
    extra = (profile.aql_filter or '').strip()
    return f'{clause} AND ({extra})' if extra else clause


def fetch(profile, client=None):
    client = client or JiraAssetsClient.from_connector()
    return client.search(build_aql(profile))


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #

def _first(obj, attribute):
    if not attribute:
        return None
    values = obj['attrs'].get(attribute) or []
    return values[0].strip() if values and values[0].strip() else None


def _lookup_action(status_map, value):
    if value is None:
        return None
    folded = {k.strip().casefold(): v for k, v in status_map.items()}
    return folded.get(value.strip().casefold())


class _People:
    """Resolve the people Jira names (AAD user labels or emails) to OpsDeck users."""

    def __init__(self):
        self.by_email, self.by_name = {}, {}
        for user in User.query.filter_by(is_archived=False).all():
            if user.email:
                self.by_email[user.email.casefold()] = user
            if user.name:
                self.by_name.setdefault(user.name.strip().casefold(), []).append(user)

    def find(self, value):
        if not value:
            return None
        key = value.strip().casefold()
        if '@' in key:
            return self.by_email.get(key)
        matches = self.by_name.get(key) or []
        return matches[0] if len(matches) == 1 else None


class _Plan:
    def __init__(self, profile, objects):
        self.profile = profile
        self.objects = objects
        self.changes, self.warnings = [], []
        self.people = _People()

    def warn(self, message):
        if len(self.warnings) < MAX_WARNINGS:
            self.warnings.append(message)
        elif len(self.warnings) == MAX_WARNINGS:
            self.warnings.append('More warnings were left out.')

    def result(self, linked_total):
        self.changes.sort(key=lambda c: (ACTIONS.index(c['action']), c['label'] or '', c['jira_id']))
        counts = dict.fromkeys(ACTIONS, 0)
        for change in self.changes:
            counts[change['action']] += 1
        return {'changes': self.changes, 'warnings': self.warnings, 'counts': counts,
                'fetched': len(self.objects), 'linked_total': linked_total}


def _ref(obj):
    return obj['key'] or obj['id']


def _change(action, obj, record=None, fields=None, refs=None):
    return {'action': action, 'jira_id': obj['id'], 'jira_key': obj['key'], 'label': obj['label'],
            'record_id': record.id if record is not None else None,
            'record_name': getattr(record, 'name', None) if record is not None else obj['label'],
            'fields': fields or {}, 'refs': refs or {}}


def _state_action(fields, base_action):
    archived = fields.get('is_archived')
    if archived and archived[1] is True:
        return 'archive'
    if archived and archived[1] is False:
        return 'unarchive'
    return base_action


def build_plan(profile, objects):
    """Compare the fetched ``objects`` with OpsDeck and return the plan (reads only)."""
    plan = _Plan(profile, objects)
    if profile.target == TARGET_ASSET:
        linked_total = _plan_assets(plan)
    elif profile.target == TARGET_SUPPLIER:
        linked_total = _plan_suppliers(plan)
    else:
        raise JiraAssetsSyncError(f'Unknown target "{profile.target}".')
    return plan.result(linked_total)


def _desired_state(plan, obj, target):
    """(status, archived) the record should have, or None if the status is unmapped."""
    value = _first(obj, plan.profile.status_attribute)
    action = _lookup_action(plan.profile.status_map, value)
    if action is None:
        plan.warn(f'{_ref(obj)} ({obj["label"]}): status "{value or "empty"}" is not mapped; '
                  'its state was left unchanged.')
        return None
    if action == ACTION_ARCHIVE:
        return None, True
    if target == TARGET_ASSET and action in ASSET_STATUSES:
        return action, False
    if target == TARGET_SUPPLIER and action == ACTION_ACTIVE:
        return None, False
    plan.warn(f'{_ref(obj)}: status "{value}" maps to "{action}", which does not apply here.')
    return None


def _diff(record, wanted):
    fields = {}
    for attr, new in wanted.items():
        old = getattr(record, attr)
        if new is not None and old != new:
            fields[attr] = [old, new]
    return fields


def _linked_records(model):
    return {r.jira_object_id: r for r in model.query.filter(model.jira_object_id.isnot(None)).all()}


def _report_missing(plan, linked, seen):
    for jira_id, record in linked.items():
        if jira_id not in seen and not record.is_archived:
            plan.warn(f'{record.name} is linked to Jira object {jira_id}, which no longer matches '
                      'this profile. It was left unchanged.')


def _plan_assets(plan):
    linked = _linked_records(Asset)
    by_serial = {}
    for asset in Asset.query.filter(Asset.serial_number.isnot(None)).all():
        by_serial[asset.serial_number.strip().casefold()] = asset
    fields_map = plan.profile.field_map
    seen = set()
    for obj in plan.objects:
        seen.add(obj['id'])
        state = _desired_state(plan, obj, TARGET_ASSET)
        status, archived = state if state else (None, None)
        wanted = {'status': status, 'is_archived': archived}
        record = linked.get(obj['id'])
        if record is not None:
            fields = _diff(record, wanted)
            if fields:
                plan.changes.append(_change(_state_action(fields, 'update'), obj, record, fields))
            continue
        serial = _first(obj, fields_map.get('serial_number'))
        match = by_serial.get(serial.casefold()) if serial else None
        if match is not None:
            if match.jira_object_id:
                plan.warn(f'{_ref(obj)}: serial number {serial} belongs to {match.name}, already '
                          f'linked to Jira object {match.jira_object_id}. Skipped.')
                continue
            fields = {'jira_object_id': [None, obj['id']], **_diff(match, wanted)}
            plan.changes.append(_change('link', obj, match, fields))
            continue
        if not plan.profile.create_missing or state is None or archived:
            continue
        plan.changes.append(_asset_create(plan, obj, fields_map, status, serial))
    _report_missing(plan, linked, seen)
    return len(linked)


def _asset_create(plan, obj, fields_map, status, serial):
    name = (_first(obj, fields_map.get('name')) or obj['label'] or obj['key'] or obj['id'])[:100]
    fields = {
        'name': [None, name],
        'serial_number': [None, serial[:100] if serial else None],
        'status': [None, status],
        'brand': [None, (_first(obj, fields_map.get('brand')) or '')[:100] or None],
        'model': [None, (_first(obj, fields_map.get('model')) or '')[:100] or None],
        'purchase_date': [None, _parse_date(_first(obj, fields_map.get('purchase_date')))],
    }
    refs = {}
    assignee = _first(obj, fields_map.get('assignee'))
    user = plan.people.find(assignee)
    if user is not None:
        fields['user'] = [None, user.name]
        refs['user_id'] = user.id
    elif assignee:
        plan.warn(f'{_ref(obj)} ({name}): assignee "{assignee}" was not found in OpsDeck.')
    fields = {k: v for k, v in fields.items() if v[1] is not None}
    return _change('create', obj, None, fields, refs)


def _plan_suppliers(plan):
    linked = _linked_records(Supplier)
    by_name = {}
    for supplier in Supplier.query.all():
        by_name.setdefault(supplier.name.strip().casefold(), []).append(supplier)
    fields_map = plan.profile.field_map
    seen = set()
    for obj in plan.objects:
        seen.add(obj['id'])
        state = _desired_state(plan, obj, TARGET_SUPPLIER)
        archived = state[1] if state else None
        critical_value = _first(obj, fields_map.get('critical'))
        critical = critical_value.casefold() in CRITICAL_YES if critical_value else None
        wanted = {'is_archived': archived, 'is_critical': critical}
        record = linked.get(obj['id'])
        if record is not None:
            fields = _diff(record, wanted)
            if fields:
                plan.changes.append(_change(_state_action(fields, 'update'), obj, record, fields))
            continue
        name = (_first(obj, fields_map.get('name')) or obj['label'] or '').strip()
        matches = [s for s in by_name.get(name.casefold(), []) if not s.jira_object_id]
        if len(matches) == 1:
            fields = {'jira_object_id': [None, obj['id']], **_diff(matches[0], wanted)}
            plan.changes.append(_change('link', obj, matches[0], fields))
            continue
        if len(matches) > 1:
            plan.warn(f'{_ref(obj)}: {len(matches)} OpsDeck suppliers are called "{name}". Skipped.')
            continue
        if not plan.profile.create_missing or state is None or archived or not name:
            continue
        plan.changes.append(_supplier_create(plan, obj, fields_map, name, critical))
    _report_missing(plan, linked, seen)
    return len(linked)


def _supplier_create(plan, obj, fields_map, name, critical):
    fields = {
        'name': [None, name[:100]],
        'website': [None, (_first(obj, fields_map.get('website')) or '')[:255] or None],
        'email': [None, (_first(obj, fields_map.get('email')) or '')[:100] or None],
        'phone': [None, (_first(obj, fields_map.get('phone')) or '')[:20] or None],
        'is_critical': [None, bool(critical)],
    }
    refs = {}
    owner = _first(obj, fields_map.get('owner'))
    user = plan.people.find(owner)
    if user is not None:
        fields['owner'] = [None, user.name]
        refs['owner_id'] = user.id
    elif owner:
        plan.warn(f'{_ref(obj)} ({name}): owner "{owner}" was not found in OpsDeck.')
    fields = {k: v for k, v in fields.items() if v[1] is not None}
    return _change('create', obj, None, fields, refs)


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def plan_fingerprint(plan):
    """Stable hash of a plan, so a confirmed preview can be checked before applying."""
    payload = json.dumps(plan['changes'], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def check_archive_brake(plan, threshold_percent):
    to_archive = plan['counts']['archive']
    base = plan['linked_total']
    if to_archive and base and to_archive * 100 > base * threshold_percent:
        raise SyncAborted(f'The run would archive {to_archive} of {base} linked records, above the '
                          f'{threshold_percent}% safety threshold. Nothing was changed.')


# --------------------------------------------------------------------------- #
# Applying
# --------------------------------------------------------------------------- #

def apply_plan(profile, plan):
    """Write ``plan`` in one transaction and audit every change."""
    applied = []
    for change in plan['changes']:
        if profile.target == TARGET_ASSET:
            record = _apply_asset(change)
        else:
            record = _apply_supplier(change)
        applied.append((change, record))
    db.session.commit()
    for change, record in applied:          # so the recorded run links to every record
        change['record_id'], change['record_name'] = record.id, record.name
    for change, record in applied:
        log_audit(
            event_type=f'{profile.target}.jira_sync',
            action=change['action'],
            target_object=f'{"Asset" if profile.target == TARGET_ASSET else "Supplier"}:{record.id}',
            target_info=f'{record.name} (Jira {change["jira_key"] or change["jira_id"]})',
            changes=json.dumps(change['fields'], default=str),
        )


def _find_or_create_brand(name):
    if not name:
        return None
    brand = Brand.query.filter(func.lower(Brand.name) == name.lower()).first()
    if brand is None:
        brand = Brand(name=name)
        db.session.add(brand)
        db.session.flush()
    return brand


def _find_or_create_model(brand, name):
    if not name or brand is None:
        return None
    model = AssetModel.query.filter(AssetModel.brand_id == brand.id,
                                    func.lower(AssetModel.name) == name.lower()).first()
    if model is None:
        model = AssetModel(name=name, brand_id=brand.id)
        db.session.add(model)
        db.session.flush()
    return model


def _new(change, key):
    return change['fields'].get(key, [None, None])[1]


def _apply_asset(change):
    if change['action'] == 'create':
        brand = _find_or_create_brand(_new(change, 'brand'))
        purchase = _new(change, 'purchase_date')
        asset = Asset(name=_new(change, 'name'), serial_number=_new(change, 'serial_number'),
                      status=_new(change, 'status'), brand=brand,
                      model=_find_or_create_model(brand, _new(change, 'model')),
                      user_id=change['refs'].get('user_id'), jira_object_id=change['jira_id'],
                      purchase_date=date.fromisoformat(purchase) if purchase else None)
        db.session.add(asset)
        db.session.flush()
        db.session.add(AssetHistory(asset_id=asset.id, field_changed='Jira sync',
                                    new_value=f'Imported from Jira {change["jira_key"] or change["jira_id"]}'))
        return asset
    asset = db.session.get(Asset, change['record_id'])
    for attr, (old, new) in change['fields'].items():
        setattr(asset, attr, new)
        if attr in ('status', 'is_archived'):
            db.session.add(AssetHistory(asset_id=asset.id, field_changed=f'{attr} (Jira sync)',
                                        old_value=str(old), new_value=str(new)))
    return asset


def _apply_supplier(change):
    if change['action'] == 'create':
        supplier = Supplier(name=_new(change, 'name'), website=_new(change, 'website'),
                            email=_new(change, 'email'), phone=_new(change, 'phone'),
                            is_critical=bool(_new(change, 'is_critical')),
                            jira_object_id=change['jira_id'])
        if change['refs'].get('owner_id'):
            supplier.owner_type, supplier.owner_id = 'User', change['refs']['owner_id']
        db.session.add(supplier)
        db.session.flush()
        return supplier
    supplier = db.session.get(Supplier, change['record_id'])
    for attr, (_, new) in change['fields'].items():
        setattr(supplier, attr, new)
    return supplier


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #

@contextmanager
def _advisory_lock(key):
    """Stop two workers (each gunicorn worker has its own scheduler) running at once."""
    if db.engine.dialect.name != 'postgresql':
        yield True
        return
    with db.engine.connect() as conn:
        acquired = conn.execute(text('SELECT pg_try_advisory_lock(:k)'), {'k': key}).scalar()
        try:
            yield acquired
        finally:
            if acquired:
                conn.execute(text('SELECT pg_advisory_unlock(:k)'), {'k': key})


def preview(profile, client=None):
    """Dry run without recording anything: fetch and plan."""
    plan = build_plan(profile, fetch(profile, client))
    plan['fingerprint'] = plan_fingerprint(plan)
    return plan


def run_sync(profile, trigger, triggered_by=None, dry_run=False, client=None, enforce_brake=None,
             expected_fingerprint=None):
    """Run ``profile`` end to end and record it. Returns the JiraAssetsRun."""
    if enforce_brake is None:
        enforce_brake = trigger == 'scheduled'
    with _advisory_lock(ADVISORY_LOCK_BASE + profile.id) as acquired:
        if not acquired:
            raise JiraAssetsSyncError(f'"{profile.name}" is already running.')
        run = JiraAssetsRun(profile_id=profile.id, trigger=trigger, triggered_by=triggered_by,
                            dry_run=dry_run, status='running')
        db.session.add(run)
        db.session.commit()
        plan = _execute(profile, run, client, dry_run, enforce_brake, expected_fingerprint)
    _finish_run(profile, run, plan)
    if run.status != 'success' and trigger == 'scheduled':
        notify_admins(profile, run)
    return run


def _execute(profile, run, client, dry_run, enforce_brake, expected_fingerprint):
    plan = None
    try:
        plan = build_plan(profile, fetch(profile, client))
        if expected_fingerprint and plan_fingerprint(plan) != expected_fingerprint:
            raise SyncAborted('Jira or OpsDeck changed since the preview. Review the new preview and confirm again.')
        if not dry_run:
            if enforce_brake:
                check_archive_brake(plan, profile.archive_threshold_percent)
            apply_plan(profile, plan)
        run.status = 'success'
    except SyncAborted as exc:
        db.session.rollback()
        run.status, run.error = 'aborted', str(exc)
    except Exception as exc:  # recorded on the run; the scheduler must not crash
        db.session.rollback()
        logger.exception('Jira Assets sync failed')
        run.status, run.error = 'error', str(exc)
    return plan


def _finish_run(profile, run, plan):
    if plan:
        counts = plan['counts']
        run.fetched_count = plan['fetched']
        run.created_count, run.linked_count = counts['create'], counts['link']
        run.updated_count = counts['update']
        run.archived_count, run.unarchived_count = counts['archive'], counts['unarchive']
        run.changes_json = json.dumps({'changes': plan['changes'], 'warnings': plan['warnings']}, default=str)
    run.finished_at = now()
    db.session.commit()
    log_audit(
        event_type='integration.jira_assets',
        action='dry_run' if run.dry_run else 'sync',
        outcome='success' if run.status == 'success' else 'failure',
        target_object=f'JiraAssetsRun:{run.id}',
        user_email=run.triggered_by,
        trigger=run.trigger,
        target_info=(f'{profile.name}: {run.fetched_count} fetched, {run.created_count} created, '
                     f'{run.linked_count} linked, {run.updated_count} updated, {run.archived_count} archived, '
                     f'{run.unarchived_count} unarchived'),
        error_message=run.error,
    )


def notify_admins(profile, run):
    """Email the notification recipient (or the admins) about a failed scheduled run."""
    from src import notifications
    from ..models import NotificationSetting
    setting = NotificationSetting.query.first()
    if setting and setting.email_recipient:
        recipients = [setting.email_recipient]
    else:
        recipients = [u.email for u in User.query.filter_by(role='admin', is_archived=False).all()]
    if not recipients:
        return
    body = (f'<p>The scheduled Jira Assets sync <b>{profile.name}</b> did not complete '
            f'(status: <b>{run.status}</b>).</p><p>{run.error or ""}</p>'
            f'<p>Review it under Settings &gt; Jira Assets Sync.</p>')
    notifications.send_email(current_app._get_current_object(),
                             'OpsDeck - Jira Assets sync needs attention', body, recipients)


def schedule_next(profile, from_time=None):
    hours = profile.interval_hours or 0
    profile.next_run_at = (from_time or now()) + timedelta(hours=hours) if hours > 0 else None


def run_due_profiles(app):
    """Scheduler entry point: run the enabled profiles whose next run has passed."""
    with app.app_context(), _advisory_lock(SCHEDULER_LOCK_KEY) as acquired:
        if not acquired:
            return
        try:
            due = JiraAssetsProfile.query.filter(
                JiraAssetsProfile.enabled.is_(True), JiraAssetsProfile.interval_hours > 0,
                (JiraAssetsProfile.next_run_at.is_(None)) | (JiraAssetsProfile.next_run_at <= now()),
            ).all()
        except Exception:  # table not created yet (fresh install before migrations)
            db.session.rollback()
            return
        for profile in due:
            schedule_next(profile)
            db.session.commit()
            try:
                run_sync(profile, 'scheduled')
            except Exception:
                db.session.rollback()
                app.logger.exception('Scheduled Jira Assets sync "%s" failed.', profile.name)
