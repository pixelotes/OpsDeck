from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import db, Requirement, RequirementAction, Opportunity, Supplier
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.timezone_helper import now

requirements_bp = Blueprint('requirements', __name__, url_prefix='/requirements')

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'procurement'
DETAIL = 'requirements.detail'
LIST_REQUIREMENTS = 'requirements.list_requirements'

@requirements_bp.route('/timeline', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def timeline():
    """Timeline view showing requirement → evaluation → supplier flow"""
    # Get all non-archived requirements with their relationships
    requirements = Requirement.query.filter_by(is_archived=False).order_by(Requirement.created_at.desc()).all()

    timeline_data = []
    for req in requirements:
        item = {
            'requirement': req,
            'evaluations': req.evaluations,
            'suppliers': []
        }

        # Get suppliers linked through evaluations
        for eval in req.evaluations:
            if eval.supplier:
                item['suppliers'].append(eval.supplier)

        timeline_data.append(item)

    return render_template('requirements/timeline.html', timeline_data=timeline_data)

@requirements_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def list_requirements():
    # Start with base query
    query = Requirement.query.filter_by(is_archived=False)

    # Apply filters from URL parameters
    search = request.args.get('search', '').strip()
    if search:
        query = query.filter(
            db.or_(
                Requirement.name.ilike(f'%{search}%'),
                Requirement.description.ilike(f'%{search}%')
            )
        )

    status_filter = request.args.get('status')
    if status_filter and status_filter != 'all':
        query = query.filter_by(status=status_filter)

    priority_filter = request.args.get('priority')
    if priority_filter and priority_filter != 'all':
        query = query.filter_by(priority=priority_filter)

    type_filter = request.args.get('type')
    if type_filter and type_filter != 'all':
        query = query.filter_by(requirement_type=type_filter)

    # Sorting
    sort_by = request.args.get('sort', 'created_desc')
    if sort_by == 'created_desc':
        query = query.order_by(Requirement.created_at.desc())
    elif sort_by == 'created_asc':
        query = query.order_by(Requirement.created_at.asc())
    elif sort_by == 'priority':
        # Custom priority order: Critical, High, Medium, Low
        query = query.order_by(
            db.case(
                (Requirement.priority == 'Critical', 1),
                (Requirement.priority == 'High', 2),
                (Requirement.priority == 'Medium', 3),
                (Requirement.priority == 'Low', 4),
                else_=5
            )
        )
    elif sort_by == 'needed_by':
        query = query.order_by(Requirement.needed_by.asc().nullslast())
    elif sort_by == 'budget':
        query = query.order_by(Requirement.estimated_budget.desc().nullslast())

    requirements = query.all()

    # Get unique values for filter dropdowns
    all_statuses = db.session.query(Requirement.status).filter_by(is_archived=False).distinct().all()
    all_priorities = ['Critical', 'High', 'Medium', 'Low']
    all_types = db.session.query(Requirement.requirement_type).filter(Requirement.requirement_type.isnot(None), Requirement.is_archived == False).distinct().all()

    return render_template('requirements/list.html',
                           requirements=requirements,
                           all_statuses=[s[0] for s in all_statuses],
                           all_priorities=all_priorities,
                           all_types=[t[0] for t in all_types],
                           current_filters={
                               'search': search,
                               'status': status_filter,
                               'priority': priority_filter,
                               'type': type_filter,
                               'sort': sort_by
                           })

@requirements_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def new_requirement():
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to create requirements.', 'danger')
            return redirect(url_for(LIST_REQUIREMENTS))

        requirement = Requirement(
            name=request.form['name'],
            requirement_type=request.form.get('requirement_type'),
            priority=request.form.get('priority', 'Medium'),
            status=request.form.get('status', 'New'),
            description=request.form.get('description'),
            estimated_budget=float(request.form.get('estimated_budget')) if request.form.get('estimated_budget') else None,
            currency=request.form.get('currency', 'EUR'),
            needed_by=datetime.strptime(request.form['needed_by'], '%Y-%m-%d').date() if request.form.get('needed_by') else None,
        )
        db.session.add(requirement)
        db.session.commit()
        flash('Requirement created successfully.', 'success')
        return redirect(url_for(DETAIL, id=requirement.id))

    return render_template('requirements/form.html')

@requirements_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def detail(id):
    requirement = db.get_or_404(Requirement, id)
    # Get non-hidden actions
    visible_actions = [action for action in requirement.actions if not action.is_hidden]
    return render_template('requirements/detail.html', requirement=requirement, visible_actions=visible_actions)

@requirements_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_requirement(id):
    requirement = db.get_or_404(Requirement, id)
    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to update requirements.', 'danger')
            return redirect(url_for(LIST_REQUIREMENTS))

        requirement.name = request.form['name']
        requirement.requirement_type = request.form.get('requirement_type')
        requirement.priority = request.form.get('priority', 'Medium')
        requirement.status = request.form.get('status')
        requirement.description = request.form.get('description')
        requirement.estimated_budget = float(request.form.get('estimated_budget')) if request.form.get('estimated_budget') else None
        requirement.currency = request.form.get('currency', 'EUR')
        requirement.needed_by = datetime.strptime(request.form['needed_by'], '%Y-%m-%d').date() if request.form.get('needed_by') else None

        db.session.commit()
        flash('Requirement updated successfully.', 'success')
        return redirect(url_for(DETAIL, id=id))

    return render_template('requirements/form.html', requirement=requirement)

@requirements_bp.route('/<int:id>/convert', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def convert_requirement(id):
    requirement = db.get_or_404(Requirement, id)
    if requirement.status == 'Converted':
        flash('This requirement has already been converted.', 'warning')
        return redirect(url_for(LIST_REQUIREMENTS))

    if request.method == 'POST':
        if not has_write_permission(MODULE):
            flash('Write access required to convert requirements.', 'danger')
            return redirect(url_for(LIST_REQUIREMENTS))

        conversion_type = request.form.get('conversion_type')
        requirement.status = 'Converted'

        if conversion_type == 'evaluation':
            evaluation = Opportunity(
                name=f"Evaluation: {requirement.name}",
                status='Evaluating',
                requirement_id=requirement.id,  # Link back to source requirement
                potential_value=requirement.estimated_budget,
                currency=requirement.currency
            )
            db.session.add(evaluation)
            db.session.commit()
            flash('Requirement converted to a new Evaluation.', 'success')
            return redirect(url_for('evaluations.edit_evaluation', id=evaluation.id))

        elif conversion_type == 'supplier':
            supplier = Supplier(
                name=requirement.name,
            )
            db.session.add(supplier)
            db.session.commit()
            flash('Requirement converted to a new Supplier.', 'success')
            return redirect(url_for('suppliers.edit_supplier', id=supplier.id))

    return render_template('requirements/convert.html', requirement=requirement)

# --- Action Management ---

@requirements_bp.route('/<int:id>/add_action', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def add_action(id):
    if not has_write_permission(MODULE):
        flash('Write access required to add actions.', 'danger')
        return redirect(url_for(DETAIL, id=id))

    requirement = db.get_or_404(Requirement, id)
    action_type = request.form.get('action_type', 'Note')
    description = request.form.get('description')

    if not description:
        flash('Action description cannot be empty.', 'danger')
    else:
        action = RequirementAction(
            requirement_id=id,
            action_type=action_type,
            description=description
        )
        db.session.add(action)
        db.session.commit()
        flash('Action added successfully.', 'success')

    return redirect(url_for(DETAIL, id=id))

@requirements_bp.route('/action/<int:action_id>/edit', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def edit_action(action_id):
    if not has_write_permission(MODULE):
        flash('Write access required to edit actions.', 'danger')
        action = db.get_or_404(RequirementAction, action_id)
        return redirect(url_for(DETAIL, id=action.requirement_id))

    action = db.get_or_404(RequirementAction, action_id)
    action.description = request.form.get('description')
    action.action_type = request.form.get('action_type')
    action.edited_at = now()
    db.session.commit()
    flash('Action updated successfully.', 'success')

    return redirect(url_for(DETAIL, id=action.requirement_id))

@requirements_bp.route('/action/<int:action_id>/toggle_hidden', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def toggle_action_hidden(action_id):
    if not has_write_permission(MODULE):
        flash('Write access required to hide/show actions.', 'danger')
        action = db.get_or_404(RequirementAction, action_id)
        return redirect(url_for(DETAIL, id=action.requirement_id))

    action = db.get_or_404(RequirementAction, action_id)
    action.is_hidden = not action.is_hidden
    db.session.commit()
    flash('Action visibility updated.', 'info')

    return redirect(url_for(DETAIL, id=action.requirement_id))

@requirements_bp.route('/action/<int:action_id>/delete', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='READ_ONLY')
def delete_action(action_id):
    if not has_write_permission(MODULE):
        flash('Write access required to delete actions.', 'danger')
        action = db.get_or_404(RequirementAction, action_id)
        return redirect(url_for(DETAIL, id=action.requirement_id))

    action = db.get_or_404(RequirementAction, action_id)
    requirement_id = action.requirement_id
    db.session.delete(action)
    db.session.commit()
    flash('Action deleted.', 'success')

    return redirect(url_for(DETAIL, id=requirement_id))


# --- Legacy routes for backward compatibility ---
# These routes redirect from old /leads URLs to new /requirements URLs

from flask import request as flask_request

@requirements_bp.route('/leads/', defaults={'path': ''})
@requirements_bp.route('/leads/<path:path>')
def legacy_redirect(path):
    """Redirect old /leads URLs to /requirements"""
    # Get the full path with query string
    new_url = url_for(LIST_REQUIREMENTS)
    if path:
        # Try to map old route names to new ones
        path_map = {
            'new': 'new_requirement',
            'convert': 'convert_requirement',
            'edit': 'edit_requirement',
        }
        for old, new in path_map.items():
            if old in path:
                new_url = flask_request.url.replace('/leads/', '/requirements/').replace(f'/{old}', f'/{new}')
                break

    flash('This URL has been moved. Please update your bookmarks.', 'info')
    return redirect(new_url, code=301)
