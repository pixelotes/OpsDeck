"""Supplier review questionnaires: templates, filling in, scheduling, reminders and compliance."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.models import db, Supplier, SecurityAssessment, User
from src.models.auth import Group
from src.models.supplier_review import (
    CODE_ACTIVE, CODE_CRITICAL, KIND_CHECK, KIND_REVIEW, STATUS_APPROVED, STATUS_INACTIVE,
    STATUS_ISSUES, STATUS_SCHEDULED, ReviewTemplate,
)
from src.services import supplier_review_service as reviews
from src.services.compliance_service import ComplianceEvaluator
from src.utils.timezone_helper import now, today

SEND_EMAIL = 'src.notifications.send_email'


# --- helpers --------------------------------------------------------------------------

def _supplier(name='Acme', owner=None, **kw):
    s = Supplier(name=name, **kw)
    if owner is not None:
        s.owner_type, s.owner_id = type(owner).__name__, owner.id
    db.session.add(s)
    db.session.commit()
    return s


def _owner_user():
    """The user logged in by the user_client fixture."""
    return User.query.filter_by(email='user@test.com').one()


def _answers(template, overrides=None, comment=None):
    """A complete, all-good form for ``template``; ``overrides`` maps question text -> answer."""
    overrides = overrides or {}
    data = {}
    for q in template.questions:
        default = 'yes' if q.kind == KIND_CHECK else 'ok'
        if q.code == CODE_CRITICAL:
            default = 'no'
        data[f'answer_{q.id}'] = overrides.get(q.text, default)
        if comment and q.text in comment:
            data[f'comment_{q.id}'] = comment[q.text]
    return data


def _rule(criteria):
    return SimpleNamespace(enabled=True, target_model='SecurityAssessment', frequency_days=365,
                           total_sla_days=395, get_criteria=lambda: criteria)


# --- templates ------------------------------------------------------------------------

def test_default_template_has_the_alf_questions(app, init_database):
    with app.app_context():
        template = reviews.ensure_default_template()
        db.session.commit()
        assert template.is_default
        assert [q.code for q in template.check_questions] == [CODE_ACTIVE, CODE_CRITICAL]
        assert len(template.review_questions) == 7
        assert reviews.ensure_default_template().id == template.id  # created once
        assert ReviewTemplate.query.count() == 1


def test_template_editor_creates_and_validates(auth_client, app):
    r = auth_client.post('/supplier-reviews/templates/new', data={
        'name': 'Light review', 'q_text': ['Still used?', 'Any issue?'],
        'q_kind': ['check', 'review'], 'q_help': ['', ''], 'q_code': ['supplier_active', ''],
        'is_default': '1'})
    assert r.status_code == 302
    with app.app_context():
        t = ReviewTemplate.query.filter_by(name='Light review').one()
        assert t.is_default
        assert [(q.kind, q.code) for q in t.questions] == [(KIND_CHECK, CODE_ACTIVE), (KIND_REVIEW, None)]
        assert ReviewTemplate.query.filter_by(is_default=True).count() == 1

    r = auth_client.post('/supplier-reviews/templates/new', data={
        'name': 'Only checks', 'q_text': ['Still used?'], 'q_kind': ['check'], 'q_help': [''],
        'q_code': ['']})
    assert r.status_code == 400
    assert b'at least one review question' in r.data


def test_template_pages_render(auth_client, app):
    assert auth_client.get('/supplier-reviews/templates').status_code == 200
    assert b'Certifications still held' in auth_client.get('/supplier-reviews/templates/new').data
    with app.app_context():
        template_id = ReviewTemplate.query.one().id
    assert auth_client.get(f'/supplier-reviews/templates/{template_id}/edit').status_code == 200


def test_editing_a_template_keeps_completed_answers(auth_client, app):
    with app.app_context():
        admin = User.query.filter_by(email='admin@test.com').one()
        review, _ = reviews.start_review(_supplier(owner=admin))
        reviews.complete_review(review, _answers(review.template), admin)
        db.session.commit()
        review_id, template_id = review.id, review.template.id
    auth_client.post(f'/supplier-reviews/templates/{template_id}/edit', data={
        'name': 'Renamed', 'q_text': ['New point'], 'q_kind': ['review'], 'q_help': [''], 'q_code': ['']})
    with app.app_context():
        texts = [a.question_text for a in db.session.get(SecurityAssessment, review_id).answers]
        assert 'Certifications still held' in texts and 'New point' not in texts


# --- filling in -----------------------------------------------------------------------

def test_group_owner_fills_in_the_review(user_client, app):
    with app.app_context():
        owner = _owner_user()
        team = Group(name='Procurement', users=[owner])
        db.session.add(team)
        db.session.commit()
        supplier = _supplier(owner=team, review_interval_months=12)
        review, _ = reviews.start_review(supplier)
        db.session.commit()
        review_id, supplier_id = review.id, supplier.id
        form = _answers(review.template, overrides={'Is the supplier critical?': 'yes'})
        form['notes'] = 'All good.'

    assert user_client.get(f'/supplier-reviews/{review_id}/fill').status_code == 200
    r = user_client.post(f'/supplier-reviews/{review_id}/fill', data=form)
    assert r.status_code == 302

    with app.app_context():
        review = db.session.get(SecurityAssessment, review_id)
        supplier = db.session.get(Supplier, supplier_id)
        assert review.status == STATUS_APPROVED
        assert review.completed_by.email == 'user@test.com'
        assert review.assessment_date == today()
        assert len(review.answers) == 9
        assert supplier.is_critical is True
        assert supplier.next_review_date.year == today().year + 1
        assert supplier.security_assessment_completed == today()
    detail = user_client.get(f'/supplier-reviews/{review_id}')
    assert detail.status_code == 200 and b'SLAs met' in detail.data


def test_not_ok_needs_a_comment(user_client, app):
    with app.app_context():
        review, _ = reviews.start_review(_supplier(owner=_owner_user()))
        db.session.commit()
        review_id = review.id
        bad = _answers(review.template, overrides={'Data breaches': 'not_ok'})
        good = _answers(review.template, overrides={'Data breaches': 'not_ok'},
                        comment={'Data breaches': 'Breach reported in May.'})

    r = user_client.post(f'/supplier-reviews/{review_id}/fill', data=bad)
    assert r.status_code == 400 and b'explain why' in r.data
    with app.app_context():
        assert db.session.get(SecurityAssessment, review_id).status == STATUS_SCHEDULED

    user_client.post(f'/supplier-reviews/{review_id}/fill', data=good)
    with app.app_context():
        review = db.session.get(SecurityAssessment, review_id)
        assert review.status == STATUS_ISSUES
        assert any(a.comment == 'Breach reported in May.' for a in review.answers)


def test_missing_answers_are_reported(user_client, app):
    with app.app_context():
        review, _ = reviews.start_review(_supplier(owner=_owner_user()))
        db.session.commit()
        review_id = review.id
    r = user_client.post(f'/supplier-reviews/{review_id}/fill', data={})
    assert r.status_code == 400 and b'needs an answer' in r.data


def test_inactive_supplier_skips_the_review_and_can_be_archived(user_client, app):
    with app.app_context():
        supplier = _supplier(owner=_owner_user(), review_interval_months=6)
        review, _ = reviews.start_review(supplier)
        db.session.commit()
        review_id, supplier_id = review.id, supplier.id
        active_q = next(q for q in review.template.questions if q.code == CODE_ACTIVE)
        critical_q = next(q for q in review.template.questions if q.code == CODE_CRITICAL)
        form = {f'answer_{active_q.id}': 'no', f'answer_{critical_q.id}': 'no', 'archive_supplier': '1'}

    assert user_client.post(f'/supplier-reviews/{review_id}/fill', data=form).status_code == 302
    with app.app_context():
        assert db.session.get(SecurityAssessment, review_id).status == STATUS_INACTIVE
        supplier = db.session.get(Supplier, supplier_id)
        assert supplier.is_archived and supplier.next_review_date is None


def test_someone_else_cannot_fill_the_review(user_client, app):
    with app.app_context():
        other = User(name='Other', email='other@test.com')
        other.set_password('x')
        db.session.add(other)
        db.session.commit()
        review, _ = reviews.start_review(_supplier(owner=other))
        db.session.commit()
        review_id = review.id
        form = _answers(review.template)
    r = user_client.post(f'/supplier-reviews/{review_id}/fill', data=form)
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(SecurityAssessment, review_id).status == STATUS_SCHEDULED


def test_completed_review_cannot_be_refilled(app, init_database):
    with app.app_context():
        owner = User(name='O', email='o@test.com')
        db.session.add(owner)
        review, _ = reviews.start_review(_supplier(owner=owner))
        reviews.complete_review(review, _answers(review.template), owner)
        with pytest.raises(reviews.ReviewError):
            reviews.complete_review(review, _answers(review.template), owner)


def test_start_review_is_idempotent_and_shown_to_the_owner(user_client, app):
    with app.app_context():
        supplier = _supplier(owner=_owner_user())
        supplier_id = supplier.id
    r = user_client.post(f'/supplier-reviews/supplier/{supplier_id}/start')
    assert r.status_code == 302
    user_client.post(f'/supplier-reviews/supplier/{supplier_id}/start')
    with app.app_context():
        assert SecurityAssessment.query.filter_by(supplier_id=supplier_id).count() == 1
    assert b'Acme' in user_client.get('/supplier-reviews/mine').data
    assert b'Supplier review: Acme' in user_client.get('/my-dashboard').data


# --- supplier form and detail ---------------------------------------------------------

def test_supplier_form_sets_the_review_schedule(auth_client, app):
    auth_client.post('/suppliers/new', data={'name': 'Acme', 'compliance_status': 'Pending',
                                             'review_interval_months': '12'})
    with app.app_context():
        supplier = Supplier.query.filter_by(name='Acme').one()
        assert supplier.review_interval_months == 12
        assert supplier.next_review_date == today()  # never reviewed: due now
        supplier_id = supplier.id
    auth_client.post(f'/suppliers/{supplier_id}/edit', data={
        'name': 'Acme', 'compliance_status': 'Pending', 'review_interval_months': ''})
    with app.app_context():
        supplier = db.session.get(Supplier, supplier_id)
        assert supplier.review_interval_months is None and supplier.next_review_date is None


def test_supplier_detail_shows_the_open_review(auth_client, app):
    with app.app_context():
        admin = User.query.filter_by(email='admin@test.com').one()
        supplier = _supplier(owner=admin, review_interval_months=12, next_review_date=today())
        reviews.start_review(supplier)
        db.session.commit()
        supplier_id = supplier.id
    page = auth_client.get(f'/suppliers/{supplier_id}').get_data(as_text=True)
    assert 'Fill in' in page and 'Review every:' in page


# --- scheduling and reminders ---------------------------------------------------------

def test_due_reviews_are_opened_and_owners_emailed(app, init_database):
    with app.app_context():
        owner = User(name='Owner', email='owner@test.com')
        db.session.add(owner)
        db.session.commit()
        due = _supplier('Due', owner=owner, review_interval_months=12,
                        next_review_date=today() + timedelta(days=10))
        _supplier('Later', owner=owner, review_interval_months=12,
                  next_review_date=today() + timedelta(days=60))
        _supplier('No owner', review_interval_months=12, next_review_date=today())
        _supplier('Archived', owner=owner, review_interval_months=12, next_review_date=today(),
                  is_archived=True)
        _supplier('No interval', owner=owner, next_review_date=today())

        with patch(SEND_EMAIL, return_value=True) as send:
            created = reviews.schedule_due_reviews()
            again = reviews.schedule_due_reviews()
        assert [r.supplier.name for r in created] == ['Due']
        assert again == []
        assert send.call_count == 1
        assert send.call_args[0][3] == ['owner@test.com']
        assert '/supplier-reviews/' in send.call_args[0][2]
        assert due.open_review.due_date == due.next_review_date


def test_overdue_reviews_are_reminded_weekly(app, init_database):
    with app.app_context():
        owner = User(name='Owner', email='owner@test.com')
        db.session.add(owner)
        db.session.commit()
        review, _ = reviews.start_review(_supplier(owner=owner), due_date=today() - timedelta(days=1))
        review.last_reminder_at = now() - timedelta(days=8)
        db.session.commit()
        with patch(SEND_EMAIL, return_value=True) as send:
            assert len(reviews.send_overdue_reminders()) == 1
            assert reviews.send_overdue_reminders() == []
        assert 'overdue' in send.call_args[0][1]


def test_cli_command(app, init_database):
    result = app.test_cli_runner().invoke(args=['schedule-supplier-reviews'])
    assert result.exit_code == 0 and '0 review(s) opened' in result.output


# --- compliance -----------------------------------------------------------------------

def test_scheduled_reviews_are_not_compliance_evidence(app, init_database):
    with app.app_context():
        owner = User(name='Owner', email='owner@test.com')
        db.session.add(owner)
        review, _ = reviews.start_review(_supplier(owner=owner))
        db.session.commit()
        evaluator = ComplianceEvaluator()
        assert evaluator.evaluate_rule(_rule({}))['status'] == 'non_compliant'
        assert evaluator.collect_evidence(_rule({}), 12) == []

        reviews.complete_review(review, _answers(review.template), owner)
        db.session.commit()
        assert evaluator.evaluate_rule(_rule({}))['status'] == 'compliant'
        assert evaluator.collect_evidence(_rule({}), 12) == [review]


def test_every_critical_supplier_must_be_reviewed(app, init_database):
    with app.app_context():
        owner = User(name='Owner', email='owner@test.com')
        db.session.add(owner)
        reviewed = _supplier('Reviewed', owner=owner, is_critical=True)
        pending = _supplier('Pending', owner=owner, is_critical=True)
        _supplier('Not critical', owner=owner)
        review, _ = reviews.start_review(reviewed)
        reviews.complete_review(review, _answers(
            review.template, overrides={'Is the supplier critical?': 'yes'}), owner)
        db.session.commit()

        evaluator = ComplianceEvaluator()
        assert evaluator.evaluate_rule(_rule({'scope': 'critical'}))['status'] == 'non_compliant'

        second, _ = reviews.start_review(pending)
        reviews.complete_review(second, _answers(
            second.template, overrides={'Is the supplier critical?': 'yes'}), owner)
        db.session.commit()
        assert evaluator.evaluate_rule(_rule({'scope': 'critical'}))['status'] == 'compliant'
        # 'all' also needs the non-critical supplier
        assert evaluator.evaluate_rule(_rule({'scope': 'all'}))['status'] == 'non_compliant'
