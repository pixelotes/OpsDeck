"""Supplier review questionnaires: scheduling, assignment, completion and reminders.

Flow: a supplier with a review interval and an owner gets a 'Scheduled' review
(a SecurityAssessment linked to a ReviewTemplate) LEAD_DAYS before its
next_review_date, and its owner is emailed. The owner (or any member of the owner
group) fills in the questionnaire; on completion the review becomes evidence for the
compliance rules and the supplier's next review date moves forward by its interval.
Open reviews past their due date are reminded once a week.
"""
import html
from contextlib import contextmanager
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from flask import current_app, url_for
from sqlalchemy import and_, or_, text

from ..extensions import db
from ..models.procurement import Supplier
from ..models.security import SecurityAssessment
from ..models.supplier_review import (
    ANSWER_NO, ANSWER_NOT_OK, ANSWER_YES, CHECK_ANSWERS, CODE_ACTIVE, CODE_CRITICAL,
    DEFAULT_QUESTIONS, DEFAULT_TEMPLATE_NAME, KIND_CHECK, REVIEW_ANSWERS, STATUS_APPROVED,
    STATUS_INACTIVE, STATUS_ISSUES, STATUS_SCHEDULED, ReviewQuestion, ReviewTemplate,
    SupplierReviewAnswer,
)
from src.utils.timezone_helper import now, today

# A review is created this many days before the supplier's next_review_date.
LEAD_DAYS = 14
# Overdue reviews are reminded at most this often.
REMINDER_INTERVAL_DAYS = 7
ADVISORY_LOCK_KEY = 74_210_027


class ReviewError(ValueError):
    """The submitted questionnaire is incomplete or invalid. ``errors`` lists why."""

    def __init__(self, errors, question_ids=()):
        super().__init__('; '.join(errors))
        self.errors = errors
        self.question_ids = set(question_ids)


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

def ensure_default_template():
    """The default template, created from DEFAULT_QUESTIONS the first time it is needed."""
    template = (ReviewTemplate.query.filter_by(is_default=True, is_archived=False).first()
                or ReviewTemplate.query.filter_by(is_archived=False).order_by(ReviewTemplate.id).first())
    if template:
        return template
    template = ReviewTemplate(name=DEFAULT_TEMPLATE_NAME, is_default=True,
                              description='Periodic review of a supplier by its owner.')
    for position, (kind, code, question, help_text) in enumerate(DEFAULT_QUESTIONS):
        template.questions.append(ReviewQuestion(position=position, kind=kind, code=code,
                                                 text=question, help_text=help_text))
    db.session.add(template)
    db.session.flush()
    return template


def set_default_template(template):
    ReviewTemplate.query.filter(ReviewTemplate.id != template.id).update({'is_default': False})
    template.is_default = True


# --------------------------------------------------------------------------- #
# Who may fill a review
# --------------------------------------------------------------------------- #

def is_reviewer(user, supplier):
    """True if ``user`` owns the supplier, directly or through the owner group."""
    return bool(user) and any(u.id == user.id for u in supplier.owner_users)


def owner_filter(user):
    """SQL condition: suppliers owned by ``user`` or by one of their groups."""
    group_ids = [g.id for g in user.groups]
    conditions = [and_(Supplier.owner_type == 'User', Supplier.owner_id == user.id)]
    if group_ids:
        conditions.append(and_(Supplier.owner_type == 'Group', Supplier.owner_id.in_(group_ids)))
    return or_(*conditions)


def open_reviews_for(user):
    """Scheduled reviews assigned to ``user``, soonest due first."""
    if not user:
        return []
    return (SecurityAssessment.query.join(Supplier)
            .filter(SecurityAssessment.status == STATUS_SCHEDULED,
                    Supplier.is_archived.is_(False), owner_filter(user))
            .order_by(SecurityAssessment.due_date.asc().nullslast()).all())


# --------------------------------------------------------------------------- #
# Creating and completing reviews
# --------------------------------------------------------------------------- #

def start_review(supplier, template=None, due_date=None):
    """Open a questionnaire review for ``supplier``; returns the existing one if open."""
    existing = supplier.open_review
    if existing:
        return existing, False
    template = template or ensure_default_template()
    review = SecurityAssessment(supplier=supplier, template=template, status=STATUS_SCHEDULED,
                                assessment_date=today(), due_date=due_date or supplier.next_review_date)
    db.session.add(review)
    db.session.flush()
    return review, True


def initial_next_review_date(supplier):
    """When a supplier first gets an interval: last completed review + interval, or today."""
    if not supplier.review_interval_months:
        return None
    last = supplier.last_completed_review
    if last:
        return last.assessment_date + relativedelta(months=supplier.review_interval_months)
    return today()


def _validate(questions, form):
    """Parse answers from the form; returns {question_id: (answer, comment)} or raises."""
    errors, bad_ids, parsed = [], [], {}
    by_code = {}
    for q in questions:
        answer = (form.get(f'answer_{q.id}') or '').strip() or None
        comment = (form.get(f'comment_{q.id}') or '').strip() or None
        parsed[q.id] = (answer, comment)
        if q.code:
            by_code[q.code] = answer

    inactive = by_code.get(CODE_ACTIVE) == ANSWER_NO
    for q in questions:
        answer, comment = parsed[q.id]
        allowed = CHECK_ANSWERS if q.kind == KIND_CHECK else REVIEW_ANSWERS
        if answer is not None and answer not in allowed:
            errors.append(f'"{q.text}": invalid answer.')
        elif answer is None and (q.kind == KIND_CHECK or not inactive):
            errors.append(f'"{q.text}" needs an answer.')
        elif answer == ANSWER_NOT_OK and not comment:
            errors.append(f'"{q.text}" is Not OK: explain why in the comment.')
        else:
            continue
        bad_ids.append(q.id)
    if errors:
        raise ReviewError(errors, bad_ids)
    return parsed, by_code


def complete_review(review, form, user):
    """Store the answers of an open review and apply their effects. Raises ReviewError."""
    if not review.is_open:
        raise ReviewError(['This review is already completed.'])
    template = review.template or ensure_default_template()
    review.template = template
    questions = template.questions
    parsed, by_code = _validate(questions, form)

    supplier = review.supplier
    review.answers.clear()
    for position, q in enumerate(questions):
        answer, comment = parsed[q.id]
        review.answers.append(SupplierReviewAnswer(
            question_id=q.id, position=position, kind=q.kind, code=q.code,
            question_text=q.text, answer=answer, comment=comment))

    inactive = by_code.get(CODE_ACTIVE) == ANSWER_NO
    if CODE_CRITICAL in by_code:
        supplier.is_critical = by_code[CODE_CRITICAL] == ANSWER_YES
    if inactive:
        review.status = STATUS_INACTIVE
    elif any(a == ANSWER_NOT_OK for a, _ in parsed.values()):
        review.status = STATUS_ISSUES
    else:
        review.status = STATUS_APPROVED

    review.notes = (form.get('notes') or '').strip() or None
    review.assessment_date = today()
    review.completed_at = now()
    review.completed_by = user
    supplier.security_assessment_completed = review.assessment_date

    if inactive and form.get('archive_supplier'):
        supplier.is_archived = True
        supplier.next_review_date = None
    elif supplier.review_interval_months:
        supplier.next_review_date = review.assessment_date + relativedelta(
            months=supplier.review_interval_months)
    return review


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #

def _review_url(review):
    base = (current_app.config.get('APP_BASE_URL') or '').rstrip('/')
    with current_app.test_request_context():
        path = url_for('supplier_reviews.fill_review', id=review.id)
    return f'{base}{path}'


def notify_owner(review, reminder=False):
    """Email the supplier owner(s) about an open review. Returns True if sent."""
    from src import notifications

    recipients = [u.email for u in review.supplier.owner_users if u.email]
    review.last_reminder_at = now()
    if not recipients:
        current_app.logger.warning('Supplier review %s: the supplier has no owner with an email.', review.id)
        return False
    name = html.escape(review.supplier.name)
    due = review.due_date.strftime('%Y-%m-%d') if review.due_date else 'as soon as possible'
    url = html.escape(_review_url(review))
    if reminder:
        subject = f'Reminder: supplier review for {review.supplier.name} is overdue'
        intro = f'<p>The review of <b>{name}</b> was due on {due} and is still open.</p>'
    else:
        subject = f'Supplier review: {review.supplier.name}'
        intro = (f'<p>You are the owner of <b>{name}</b> and its periodic review is due on '
                 f'<b>{due}</b>.</p>')
    body = (f'{intro}<p>It takes a few minutes: confirm the supplier is still active and '
            f'critical, then check its issues, certifications, prices, terms, breaches and SLAs.</p>'
            f'<p><a href="{url}">Fill in the review</a></p>')
    return notifications.send_email(current_app._get_current_object(), subject, body, recipients)


# --------------------------------------------------------------------------- #
# Scheduled job
# --------------------------------------------------------------------------- #

def schedule_due_reviews(as_of=None):
    """Open reviews for suppliers due within LEAD_DAYS and email their owners."""
    as_of = as_of or today()
    due = Supplier.query.filter(
        Supplier.is_archived.is_(False),
        Supplier.review_interval_months.isnot(None),
        Supplier.next_review_date.isnot(None),
        Supplier.next_review_date <= as_of + timedelta(days=LEAD_DAYS),
        Supplier.owner_id.isnot(None),
    ).all()
    created = []
    for supplier in due:
        review, is_new = start_review(supplier)
        if is_new:
            notify_owner(review)
            created.append(review)
    db.session.commit()
    return created


def send_overdue_reminders(as_of=None):
    """Remind owners of open reviews past their due date, once per REMINDER_INTERVAL_DAYS."""
    as_of = as_of or today()
    cutoff = now() - timedelta(days=REMINDER_INTERVAL_DAYS)
    overdue = SecurityAssessment.query.join(Supplier).filter(
        SecurityAssessment.status == STATUS_SCHEDULED,
        SecurityAssessment.due_date < as_of,
        Supplier.is_archived.is_(False),
        or_(SecurityAssessment.last_reminder_at.is_(None), SecurityAssessment.last_reminder_at < cutoff),
    ).all()
    for review in overdue:
        notify_owner(review, reminder=True)
    db.session.commit()
    return overdue


@contextmanager
def _run_lock():
    """Each gunicorn worker runs its own scheduler: only one of them does the work."""
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


def run_daily(app):
    """Scheduler entry point."""
    with app.app_context():
        with _run_lock() as acquired:
            if not acquired:
                return
            try:
                created = schedule_due_reviews()
                reminded = send_overdue_reminders()
                app.logger.info('Supplier reviews: %d opened, %d reminders sent.', len(created), len(reminded))
            except Exception:  # the scheduler must not crash
                db.session.rollback()
                app.logger.exception('Supplier review scheduling failed.')

