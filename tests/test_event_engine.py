"""Tests for the event engine: AuditLog rows matched against EventRules -> queue."""
import json
from src.models import db, User
from src.models.audit_log import AuditLog
from src.models.event_rules import EventRule
from src.models.communications import ScheduledCommunication, EmailTemplate
from src.services.event_engine import process_event_rules
from src.utils.communications_context import get_template_context, render_email_template


def _admin():
    u = User(name='Admin', email='admin@test.com', role='admin')
    u.set_password('x')
    db.session.add(u)
    db.session.commit()
    return u


def _template():
    t = EmailTemplate(name='Asset Created', category='events',
                      subject='Asset {{ entity }} {{ action }}d',
                      body_html='<p>{{ actor }} {{ action }}d {{ entity }}</p>', is_active=True)
    db.session.add(t)
    db.session.commit()
    return t


def _audit(entity_type='Asset', action='create', entity_id=1, repr_='Laptop-01', changes=None):
    row = AuditLog(action=action, entity_type=entity_type, entity_id=entity_id,
                   entity_repr=repr_, user_email='alice@test.com',
                   changes=json.dumps(changes) if changes else None, event_processed=False)
    db.session.add(row)
    db.session.commit()
    return row


def _rule(**kw):
    defaults = dict(name='R', entity_type='Asset', action='create',
                    recipient_mode='admins', channels=['email'])
    defaults.update(kw)
    rule = EventRule(**defaults)
    db.session.add(rule)
    db.session.commit()
    return rule


def test_matches_logic(app, init_database):
    with app.app_context():
        r = EventRule(name='r', entity_type='Asset', action='create', enabled=True)
        assert r.matches('Asset', 'create')
        assert not r.matches('Asset', 'update')
        assert not r.matches('Subscription', 'create')
        r.action = 'any'
        assert r.matches('Asset', 'delete')
        r.enabled = False
        assert not r.matches('Asset', 'create')


def test_engine_enqueues_on_match(app, init_database):
    with app.app_context():
        _admin()
        t = _template()
        rule = _rule(template_id=t.id)
        audit = _audit()

        process_event_rules(app)

        comms = ScheduledCommunication.query.filter_by(event_rule_id=rule.id).all()
        assert len(comms) == 1
        assert comms[0].recipient_email == 'admin@test.com'
        assert comms[0].audit_log_id == audit.id
        assert comms[0].channel == 'email'
        assert db.session.get(AuditLog, audit.id).event_processed is True


def test_engine_marks_processed_without_match(app, init_database):
    with app.app_context():
        _admin()
        audit = _audit(entity_type='Subscription', action='delete')  # no rule for this

        process_event_rules(app)

        assert db.session.get(AuditLog, audit.id).event_processed is True
        assert ScheduledCommunication.query.filter_by(target_type='Subscription').count() == 0


def test_engine_skips_disabled_rule(app, init_database):
    with app.app_context():
        _admin()
        t = _template()
        _rule(template_id=t.id, enabled=False)
        _audit()

        process_event_rules(app)

        assert ScheduledCommunication.query.count() == 0


def test_engine_multichannel_fans_out(app, init_database):
    with app.app_context():
        _admin()
        t = _template()
        rule = _rule(template_id=t.id, channels=['email', 'discord'],
                     discord_webhook_url='https://discord.com/api/webhooks/1/x')
        _audit()

        process_event_rules(app)

        comms = ScheduledCommunication.query.filter_by(event_rule_id=rule.id).all()
        assert {c.channel for c in comms} == {'email', 'discord'}


def test_event_template_context(app, init_database):
    with app.app_context():
        _admin()
        t = _template()
        rule = _rule(template_id=t.id)
        _audit(changes={'status': {'old': 'active', 'new': 'retired'}})
        process_event_rules(app)

        comm = ScheduledCommunication.query.filter_by(event_rule_id=rule.id).first()
        ctx = get_template_context(comm)
        assert ctx['entity'] == 'Laptop-01'
        assert ctx['action'] == 'create'
        assert ctx['actor'] == 'alice@test.com'
        assert ctx['changes']['status']['new'] == 'retired'


class _FakeTemplate:
    def __init__(self, subject, body_html):
        self.subject = subject
        self.body_html = body_html


def test_render_missing_var_falls_back_to_empty(app):
    """A template referencing a variable absent from context renders empty,
    not the raw {{ ... }} markup."""
    with app.app_context():
        tpl = _FakeTemplate('Hi {{ user.name }}', '<p>{{ user.name }} did {{ action }}</p>')
        subject, body = render_email_template(tpl, {'action': 'create'})
        assert subject == 'Hi '
        assert '{{' not in body
        assert 'did create' in body


def test_render_changes_if_else(app):
    """The seeded-style if/else over `changes` renders both branches safely."""
    with app.app_context():
        body = ('{% if changes %}{% for f, v in changes.items() %}{{ f }}:{{ v.new }} '
                '{% endfor %}{% else %}none{% endif %}')
        tpl = _FakeTemplate('s', body)
        _, with_ch = render_email_template(tpl, {'changes': {'status': {'old': 'a', 'new': 'b'}}})
        _, without = render_email_template(tpl, {'changes': None})
        assert with_ch.strip() == 'status:b'
        assert without == 'none'


def test_create_rule_route(auth_client, app):
    auth_client.post('/settings/event-rules/create', data={
        'name': 'New asset alert',
        'entity_type': 'Asset',
        'action': 'create',
        'recipient_mode': 'admins',
        'channel_email': 'on',
    }, follow_redirects=True)

    with app.app_context():
        rule = EventRule.query.filter_by(name='New asset alert').first()
        assert rule is not None
        assert rule.entity_type == 'Asset'
        assert rule.channels == ['email']
