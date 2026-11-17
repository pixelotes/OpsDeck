"""Supplier review questionnaires: filling them in, and managing their templates.

Reviews are filled in by the supplier's owner (the user, or any member of the owner
group), who may not have access to the Compliance module, so these routes check
ownership themselves instead of relying only on module permissions.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from ..models import db, Supplier, SecurityAssessment, User
from ..models.supplier_review import (
    ANSWER_LABELS, CHECK_ANSWERS, CHECK_CODES, KIND_CHECK, KIND_REVIEW, QUESTION_KINDS,
    REVIEW_ANSWERS, ReviewQuestion, ReviewTemplate,
)
from ..services import supplier_review_service as reviews
from ..services.permissions_service import (has_write_permission, requires_permission,
                                            user_has_module_access)
from .main import login_required

supplier_reviews_bp = Blueprint('supplier_reviews', __name__)

MODULE = 'compliance'
TEMPLATES_LIST = 'supplier_reviews.list_templates'
FILL = 'supplier_reviews.fill_review'
VIEW = 'supplier_reviews.view_review'


def _current_user():
    return db.session.get(User, session.get('user_id'))


def _can_fill(review, user):
    return reviews.is_reviewer(user, review.supplier) or has_write_permission(MODULE)


def _can_view(review, user):
    return (reviews.is_reviewer(user, review.supplier)
            or user_has_module_access(user.id, MODULE)
            or user_has_module_access(user.id, 'procurement'))


# --------------------------------------------------------------------------- #
# Reviews
# --------------------------------------------------------------------------- #

@supplier_reviews_bp.route('/mine')
@login_required
def my_reviews():
    user = _current_user()
    return render_template('supplier_reviews/mine.html', reviews=reviews.open_reviews_for(user))


@supplier_reviews_bp.route('/supplier/<int:supplier_id>/start', methods=['POST'])
@login_required
def start_review(supplier_id):
    supplier = db.get_or_404(Supplier, supplier_id)
    user = _current_user()
    if not (reviews.is_reviewer(user, supplier) or has_write_permission(MODULE)
            or has_write_permission('procurement')):
        flash('Only the supplier owner or a compliance editor can start a review.', 'danger')
        return redirect(url_for('suppliers.supplier_detail', id=supplier.id))
    template = None
    template_id = request.form.get('template_id', type=int)
    if template_id:
        template = db.session.get(ReviewTemplate, template_id)
        if not template or template.is_archived:
            flash('The selected template does not exist.', 'danger')
            return redirect(url_for('suppliers.supplier_detail', id=supplier.id))
    review, created = reviews.start_review(supplier, template=template)
    db.session.commit()
    if not created:
        flash('This supplier already has an open review.', 'info')
    return redirect(url_for(FILL, id=review.id))


@supplier_reviews_bp.route('/<int:id>')
@login_required
def view_review(id):
    review = db.get_or_404(SecurityAssessment, id)
    user = _current_user()
    if not _can_view(review, user):
        abort(403)
    return render_template('compliance/assessment_detail.html', assessment=review,
                           can_fill=review.is_open and _can_fill(review, user),
                           answer_labels=ANSWER_LABELS)


@supplier_reviews_bp.route('/<int:id>/fill', methods=['GET', 'POST'])
@login_required
def fill_review(id):
    review = db.get_or_404(SecurityAssessment, id)
    user = _current_user()
    if not review.is_open:
        return redirect(url_for(VIEW, id=review.id))
    if not _can_fill(review, user):
        flash('Only the supplier owner or a compliance editor can fill in this review.', 'danger')
        return redirect(url_for('main.my_dashboard'))
    if review.template is None:
        review.template = reviews.ensure_default_template()
        db.session.commit()

    errors, error_ids = [], set()
    if request.method == 'POST':
        try:
            reviews.complete_review(review, request.form, user)
        except reviews.ReviewError as exc:
            db.session.rollback()
            errors, error_ids = exc.errors, exc.question_ids
        else:
            db.session.commit()
            flash(f'Review of {review.supplier.name} completed: {review.status}.', 'success')
            return redirect(url_for(VIEW, id=review.id))

    return render_template('supplier_reviews/fill.html', review=review, template=review.template,
                           form=request.form, errors=errors, error_ids=error_ids, check_answers=CHECK_ANSWERS,
                           review_answers=REVIEW_ANSWERS, answer_labels=ANSWER_LABELS,
                           kind_check=KIND_CHECK), (400 if errors else 200)


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #

@supplier_reviews_bp.route('/templates')
@login_required
@requires_permission(MODULE)
def list_templates():
    reviews.ensure_default_template()
    db.session.commit()
    templates = ReviewTemplate.query.order_by(ReviewTemplate.is_archived, ReviewTemplate.name).all()
    return render_template('supplier_reviews/templates.html', templates=templates)


def _questions_from_form(form):
    """Rows of the template editor: parallel lists q_text / q_kind / q_help / q_code."""
    rows = zip(form.getlist('q_text'), form.getlist('q_kind'), form.getlist('q_help'),
               form.getlist('q_code'))
    questions, errors = [], []
    for text, kind, help_text, code in rows:
        text = text.strip()
        if not text:
            continue
        if kind not in QUESTION_KINDS:
            errors.append(f'"{text}": unknown question type.')
            continue
        code = code.strip() or None
        if code and (kind != KIND_CHECK or code not in CHECK_CODES):
            code = None
        questions.append((text[:255], kind, help_text.strip() or None, code))
    if not any(kind == KIND_REVIEW for _, kind, _, _ in questions):
        errors.append('A template needs at least one review question.')
    return questions, errors


def _save_template(template):
    form = request.form
    name = (form.get('name') or '').strip()
    questions, errors = _questions_from_form(form)
    if not name:
        errors.insert(0, 'The template needs a name.')
    if errors:
        return errors
    template.name = name[:150]
    template.description = (form.get('description') or '').strip() or None
    # Answers keep their own copy of each question, so questions can be replaced freely.
    template.questions.clear()
    db.session.flush()
    for position, (text, kind, help_text, code) in enumerate(questions):
        template.questions.append(ReviewQuestion(position=position, text=text, kind=kind,
                                                 help_text=help_text, code=code))
    if form.get('is_default') or not ReviewTemplate.query.filter(
            ReviewTemplate.is_default.is_(True), ReviewTemplate.id != template.id).count():
        db.session.flush()
        reviews.set_default_template(template)
    return []


@supplier_reviews_bp.route('/templates/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def new_template():
    template = ReviewTemplate()
    if request.method == 'POST':
        db.session.add(template)
        errors = _save_template(template)
        if not errors:
            db.session.commit()
            flash('Review template created.', 'success')
            return redirect(url_for(TEMPLATES_LIST))
        db.session.rollback()
        for e in errors:
            flash(e, 'danger')
        return render_template('supplier_reviews/template_form.html', template=None,
                               form_questions=_questions_from_form(request.form)[0],
                               kinds=QUESTION_KINDS, check_codes=CHECK_CODES), 400
    default = reviews.ensure_default_template()
    db.session.commit()
    rows = [(q.text, q.kind, q.help_text, q.code) for q in default.questions]
    return render_template('supplier_reviews/template_form.html', template=None, form_questions=rows,
                           kinds=QUESTION_KINDS, check_codes=CHECK_CODES)


@supplier_reviews_bp.route('/templates/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def edit_template(id):
    template = db.get_or_404(ReviewTemplate, id)
    if request.method == 'POST':
        errors = _save_template(template)
        if not errors:
            db.session.commit()
            flash('Review template saved.', 'success')
            return redirect(url_for(TEMPLATES_LIST))
        db.session.rollback()
        for e in errors:
            flash(e, 'danger')
        return render_template('supplier_reviews/template_form.html', template=template,
                               form_questions=_questions_from_form(request.form)[0],
                               kinds=QUESTION_KINDS, check_codes=CHECK_CODES), 400
    rows = [(q.text, q.kind, q.help_text, q.code) for q in template.questions]
    return render_template('supplier_reviews/template_form.html', template=template, form_questions=rows,
                           kinds=QUESTION_KINDS, check_codes=CHECK_CODES)


@supplier_reviews_bp.route('/templates/<int:id>/default', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def make_default_template(id):
    template = db.get_or_404(ReviewTemplate, id)
    template.is_archived = False
    reviews.set_default_template(template)
    db.session.commit()
    flash(f'"{template.name}" is now the default review template.', 'success')
    return redirect(url_for(TEMPLATES_LIST))


@supplier_reviews_bp.route('/templates/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def archive_template(id):
    template = db.get_or_404(ReviewTemplate, id)
    if template.is_default:
        flash('Make another template the default before archiving this one.', 'warning')
    else:
        template.is_archived = not template.is_archived
        db.session.commit()
        flash(f'Template {"archived" if template.is_archived else "restored"}.', 'success')
    return redirect(url_for(TEMPLATES_LIST))
