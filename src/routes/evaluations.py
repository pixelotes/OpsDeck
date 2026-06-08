from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from datetime import datetime
from ..models import db, Opportunity, Activity, OpportunityTask, Supplier, Contact, Risk, Budget
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.timezone_helper import now

evaluations_bp = Blueprint('evaluations', __name__, url_prefix='/evaluations')

@evaluations_bp.route('/kanban', methods=['GET'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def kanban_view():
    """Kanban board view for evaluations"""
    # Group evaluations by status
    statuses = ['Evaluating', 'PoC', 'Negotiating', 'Won', 'Lost']
    evaluations_by_status = {}

    for status in statuses:
        evaluations_by_status[status] = Opportunity.query.filter_by(status=status).order_by(Opportunity.estimated_close_date.asc()).all()

    return render_template('evaluations/kanban.html',
                           evaluations_by_status=evaluations_by_status,
                           statuses=statuses)

@evaluations_bp.route('/', methods=['GET'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def list_evaluations():
    # Start with base query
    query = Opportunity.query

    # Apply filters from URL parameters
    search = request.args.get('search', '').strip()
    if search:
        query = query.filter(
            db.or_(
                Opportunity.name.ilike(f'%{search}%'),
                Opportunity.notes.ilike(f'%{search}%')
            )
        )

    status_filter = request.args.get('status')
    if status_filter and status_filter != 'all':
        query = query.filter_by(status=status_filter)

    supplier_filter = request.args.get('supplier')
    if supplier_filter and supplier_filter != 'all':
        query = query.filter_by(supplier_id=int(supplier_filter))

    # Filter by linked requirement
    requirement_filter = request.args.get('requirement')
    if requirement_filter == 'linked':
        query = query.filter(Opportunity.requirement_id.isnot(None))
    elif requirement_filter == 'unlinked':
        query = query.filter(Opportunity.requirement_id.is_(None))

    # Sorting
    sort_by = request.args.get('sort', 'close_date')
    if sort_by == 'close_date':
        query = query.order_by(Opportunity.estimated_close_date.asc().nullslast())
    elif sort_by == 'created_desc':
        query = query.order_by(Opportunity.created_at.desc())
    elif sort_by == 'value':
        query = query.order_by(Opportunity.potential_value.desc().nullslast())
    elif sort_by == 'name':
        query = query.order_by(Opportunity.name.asc())

    evaluations = query.all()

    # Get unique values for filter dropdowns
    all_statuses = db.session.query(Opportunity.status).distinct().all()
    all_suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()

    return render_template('evaluations/list.html',
                           evaluations=evaluations,
                           all_statuses=[s[0] for s in all_statuses],
                           all_suppliers=all_suppliers,
                           current_filters={
                               'search': search,
                               'status': status_filter,
                               'supplier': supplier_filter,
                               'requirement': requirement_filter,
                               'sort': sort_by
                           })

@evaluations_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def new_evaluation():
    if request.method == 'POST':
        if not has_write_permission('procurement'):
            flash('Write access required to create evaluations.', 'danger')
            return redirect(url_for('evaluations.list_evaluations'))

        evaluation = Opportunity(
            name=request.form['name'],
            status=request.form['status'],
            potential_value=float(request.form.get('potential_value')) if request.form.get('potential_value') else None,
            currency=request.form.get('currency'),
            estimated_close_date=datetime.strptime(request.form['estimated_close_date'], '%Y-%m-%d').date() if request.form.get('estimated_close_date') else None,
            notes=request.form.get('notes'),
            supplier_id=request.form.get('supplier_id') or None,
            primary_contact_id=request.form.get('primary_contact_id') or None,
            requirement_id=request.form.get('requirement_id') or None,
            risk_id=request.form.get('risk_id') or None,
            budget_id=request.form.get('budget_id') or None,
        )
        db.session.add(evaluation)
        db.session.commit()
        flash('Evaluation created successfully!', 'success')
        return redirect(url_for('evaluations.detail', id=evaluation.id))

    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    contacts = Contact.query.filter_by(is_archived=False).order_by(Contact.name).all()
    risks = Risk.query.order_by(Risk.risk_description).all()
    budgets = Budget.query.order_by(Budget.name).all()
    # Get requirements for linking
    from ..models import Requirement
    requirements = Requirement.query.filter_by(is_archived=False).order_by(Requirement.created_at.desc()).all()

    return render_template('evaluations/form.html',
                           suppliers=suppliers,
                           contacts=contacts,
                           risks=risks,
                           budgets=budgets,
                           requirements=requirements)

@evaluations_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def detail(id):
    evaluation = db.get_or_404(Opportunity, id)
    # Filter out hidden activities and tasks
    visible_activities = [activity for activity in evaluation.activities if not activity.is_hidden]
    visible_tasks = [task for task in evaluation.tasks if not task.is_hidden]
    return render_template('evaluations/detail.html',
                           evaluation=evaluation,
                           visible_activities=visible_activities,
                           visible_tasks=visible_tasks)

@evaluations_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def edit_evaluation(id):
    evaluation = db.get_or_404(Opportunity, id)
    if request.method == 'POST':
        if not has_write_permission('procurement'):
            flash('Write access required to update evaluations.', 'danger')
            return redirect(url_for('evaluations.detail', id=id))

        evaluation.name = request.form['name']
        evaluation.status = request.form['status']
        evaluation.potential_value = float(request.form.get('potential_value')) if request.form.get('potential_value') else None
        evaluation.currency = request.form.get('currency')
        evaluation.estimated_close_date = datetime.strptime(request.form['estimated_close_date'], '%Y-%m-%d').date() if request.form.get('estimated_close_date') else None
        evaluation.notes = request.form.get('notes')
        evaluation.supplier_id = request.form.get('supplier_id') or None
        evaluation.primary_contact_id = request.form.get('primary_contact_id') or None
        evaluation.requirement_id = request.form.get('requirement_id') or None
        evaluation.risk_id = request.form.get('risk_id') or None
        evaluation.budget_id = request.form.get('budget_id') or None

        db.session.commit()
        flash('Evaluation updated successfully!', 'success')
        return redirect(url_for('evaluations.detail', id=id))

    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    contacts = Contact.query.filter_by(is_archived=False).order_by(Contact.name).all()
    risks = Risk.query.order_by(Risk.risk_description).all()
    budgets = Budget.query.order_by(Budget.name).all()
    from ..models import Requirement
    requirements = Requirement.query.filter_by(is_archived=False).order_by(Requirement.created_at.desc()).all()

    return render_template('evaluations/form.html',
                           evaluation=evaluation,
                           suppliers=suppliers,
                           contacts=contacts,
                           risks=risks,
                           budgets=budgets,
                           requirements=requirements)

# --- Activity Management ---

@evaluations_bp.route('/<int:id>/add_activity', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def add_activity(id):
    if not has_write_permission('procurement'):
        flash('Write access required to add activities.', 'danger')
        return redirect(url_for('evaluations.detail', id=id))

    db.get_or_404(Opportunity, id)
    activity_type = request.form.get('type')
    notes = request.form.get('notes')

    if not notes:
        flash('Activity notes cannot be empty.', 'danger')
    else:
        activity = Activity(
            type=activity_type,
            notes=notes,
            opportunity_id=id
        )
        db.session.add(activity)
        db.session.commit()
        flash('Activity added successfully.', 'success')

    return redirect(url_for('evaluations.detail', id=id))

@evaluations_bp.route('/activity/<int:activity_id>/edit', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def edit_activity(activity_id):
    if not has_write_permission('procurement'):
        flash('Write access required to edit activities.', 'danger')
        activity = db.get_or_404(Activity, activity_id)
        return redirect(url_for('evaluations.detail', id=activity.opportunity_id))

    activity = db.get_or_404(Activity, activity_id)
    activity.notes = request.form.get('notes')
    activity.type = request.form.get('type')
    activity.edited_at = now()
    db.session.commit()
    flash('Activity updated successfully.', 'success')

    return redirect(url_for('evaluations.detail', id=activity.opportunity_id))

@evaluations_bp.route('/activity/<int:activity_id>/toggle_hidden', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def toggle_activity_hidden(activity_id):
    if not has_write_permission('procurement'):
        flash('Write access required to hide/show activities.', 'danger')
        activity = db.get_or_404(Activity, activity_id)
        return redirect(url_for('evaluations.detail', id=activity.opportunity_id))

    activity = db.get_or_404(Activity, activity_id)
    activity.is_hidden = not activity.is_hidden
    db.session.commit()
    flash('Activity visibility updated.', 'info')

    return redirect(url_for('evaluations.detail', id=activity.opportunity_id))

@evaluations_bp.route('/activity/<int:activity_id>/delete', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def delete_activity(activity_id):
    if not has_write_permission('procurement'):
        flash('Write access required to delete activities.', 'danger')
        activity = db.get_or_404(Activity, activity_id)
        return redirect(url_for('evaluations.detail', id=activity.opportunity_id))

    activity = db.get_or_404(Activity, activity_id)
    opportunity_id = activity.opportunity_id
    db.session.delete(activity)
    db.session.commit()
    flash('Activity deleted.', 'success')

    return redirect(url_for('evaluations.detail', id=opportunity_id))

# --- Task Management ---

@evaluations_bp.route('/<int:evaluation_id>/add_task', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def add_task(evaluation_id):
    if not has_write_permission('procurement'):
        flash('Write access required to add tasks.', 'danger')
        return redirect(url_for('evaluations.detail', id=evaluation_id))

    description = request.form.get('task_description')
    due_date_str = request.form.get('due_date')

    if not description:
        flash('Task description cannot be empty.', 'warning')
    else:
        task = OpportunityTask(
            opportunity_id=evaluation_id,
            description=description,
            due_date=datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None
        )
        db.session.add(task)
        db.session.commit()
        flash('Task added.', 'success')

    return redirect(url_for('evaluations.detail', id=evaluation_id))

@evaluations_bp.route('/task/<int:task_id>/toggle', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def toggle_task(task_id):
    if not has_write_permission('procurement'):
        flash('Write access required to update tasks.', 'danger')
        task = db.get_or_404(OpportunityTask, task_id)
        return redirect(url_for('evaluations.detail', id=task.opportunity_id))

    task = db.get_or_404(OpportunityTask, task_id)
    task.is_completed = not task.is_completed
    if task.is_completed:
        task.completed_at = now()
    else:
        task.completed_at = None
    db.session.commit()
    flash('Task status updated.', 'info')

    return redirect(url_for('evaluations.detail', id=task.opportunity_id))

@evaluations_bp.route('/task/<int:task_id>/edit', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def edit_task(task_id):
    if not has_write_permission('procurement'):
        flash('Write access required to edit tasks.', 'danger')
        task = db.get_or_404(OpportunityTask, task_id)
        return redirect(url_for('evaluations.detail', id=task.opportunity_id))

    task = db.get_or_404(OpportunityTask, task_id)
    task.description = request.form.get('description')
    due_date_str = request.form.get('due_date')
    task.due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None
    db.session.commit()
    flash('Task updated.', 'success')

    return redirect(url_for('evaluations.detail', id=task.opportunity_id))

@evaluations_bp.route('/task/<int:task_id>/toggle_hidden', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def toggle_task_hidden(task_id):
    if not has_write_permission('procurement'):
        flash('Write access required to hide/show tasks.', 'danger')
        task = db.get_or_404(OpportunityTask, task_id)
        return redirect(url_for('evaluations.detail', id=task.opportunity_id))

    task = db.get_or_404(OpportunityTask, task_id)
    task.is_hidden = not task.is_hidden
    db.session.commit()
    flash('Task visibility updated.', 'info')

    return redirect(url_for('evaluations.detail', id=task.opportunity_id))

@evaluations_bp.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def delete_task(task_id):
    if not has_write_permission('procurement'):
        flash('Write access required to delete tasks.', 'danger')
        task = db.get_or_404(OpportunityTask, task_id)
        return redirect(url_for('evaluations.detail', id=task.opportunity_id))

    task = db.get_or_404(OpportunityTask, task_id)
    opportunity_id = task.opportunity_id
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted.', 'success')

    return redirect(url_for('evaluations.detail', id=opportunity_id))


# --- API Routes for Kanban ---

@evaluations_bp.route('/api/<int:evaluation_id>/update_status', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def update_status(evaluation_id):
    """API endpoint to update evaluation status (for Kanban drag & drop)"""
    if not has_write_permission('procurement'):
        return jsonify({'success': False, 'error': 'Write access required'}), 403

    evaluation = db.get_or_404(Opportunity, evaluation_id)
    data = request.get_json()
    new_status = data.get('status')

    valid_statuses = ['Evaluating', 'PoC', 'Negotiating', 'Won', 'Lost']
    if new_status not in valid_statuses:
        return jsonify({'success': False, 'error': 'Invalid status'}), 400

    evaluation.status = new_status
    db.session.commit()

    return jsonify({'success': True, 'message': f'Status updated to {new_status}'})
