# pixelotes/opsdeck/OpsDeck-feat-licenses/src/routes/opportunities.py

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
# Ensure Risk and Budget are imported if you implemented the previous changes
from ..models import db, Opportunity, Activity, Supplier, Contact, Risk, Budget
from .main import login_required

opportunities_bp = Blueprint('opportunities', __name__)

@opportunities_bp.route('/')
@login_required
def list_opportunities():
    opportunities = Opportunity.query.order_by(Opportunity.estimated_close_date.asc()).all()
    return render_template('opportunities/list.html', opportunities=opportunities)

@opportunities_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_opportunity():
    if request.method == 'POST':
        opportunity = Opportunity(
            name=request.form['name'],
            status=request.form['status'],
            potential_value=float(request.form.get('potential_value')) if request.form.get('potential_value') else None,
            currency=request.form.get('currency'),
            estimated_close_date=datetime.strptime(request.form['estimated_close_date'], '%Y-%m-%d').date() if request.form['estimated_close_date'] else None,
            notes=request.form.get('notes'),
            supplier_id=request.form.get('supplier_id') or None,
            primary_contact_id=request.form.get('primary_contact_id') or None,
            # Add risk_id and budget_id if you implemented previous changes
            risk_id=request.form.get('risk_id') or None,
            budget_id=request.form.get('budget_id') or None,
        )
        db.session.add(opportunity)
        db.session.commit()
        flash('Opportunity created successfully!', 'success')
        return redirect(url_for('opportunities.list_opportunities'))

    suppliers = Supplier.query.order_by(Supplier.name).all()
    contacts = Contact.query.order_by(Contact.name).all()
    # Add risks and budgets if you implemented previous changes
    risks = Risk.query.order_by(Risk.risk_description).all()
    budgets = Budget.query.order_by(Budget.name).all()
    return render_template('opportunities/form.html', suppliers=suppliers, contacts=contacts, risks=risks, budgets=budgets)

@opportunities_bp.route('/<int:id>')
@login_required
def detail(id):
    opportunity = Opportunity.query.get_or_404(id)
    return render_template('opportunities/detail.html', opportunity=opportunity)

# --- ADD THIS EDIT ROUTE ---
@opportunities_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_opportunity(id):
    opportunity = Opportunity.query.get_or_404(id)
    if request.method == 'POST':
        opportunity.name = request.form['name']
        opportunity.status = request.form['status']
        opportunity.potential_value = float(request.form.get('potential_value')) if request.form.get('potential_value') else None
        opportunity.currency = request.form.get('currency')
        opportunity.estimated_close_date = datetime.strptime(request.form['estimated_close_date'], '%Y-%m-%d').date() if request.form['estimated_close_date'] else None
        opportunity.notes = request.form.get('notes')
        opportunity.supplier_id = request.form.get('supplier_id') or None
        opportunity.primary_contact_id = request.form.get('primary_contact_id') or None
        # Add risk_id and budget_id updates if you implemented previous changes
        opportunity.risk_id=request.form.get('risk_id') or None
        opportunity.budget_id=request.form.get('budget_id') or None
        db.session.commit()
        flash('Opportunity updated successfully!', 'success')
        return redirect(url_for('opportunities.detail', id=id)) # Redirect to detail after edit

    # Fetch necessary data for the form dropdowns
    suppliers = Supplier.query.order_by(Supplier.name).all()
    contacts = Contact.query.order_by(Contact.name).all()
    # Add risks and budgets if you implemented previous changes
    risks = Risk.query.order_by(Risk.risk_description).all()
    budgets = Budget.query.order_by(Budget.name).all()
    return render_template('opportunities/form.html', opportunity=opportunity, suppliers=suppliers, contacts=contacts, risks=risks, budgets=budgets)


@opportunities_bp.route('/<int:id>/add_activity', methods=['POST'])
@login_required
def add_activity(id):
    opportunity = Opportunity.query.get_or_404(id)
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

    return redirect(url_for('opportunities.detail', id=id))

@opportunities_bp.route('/<int:opportunity_id>/add_task', methods=['POST'])
@login_required
def add_task(opportunity_id):
    description = request.form.get('task_description')
    if description:
        task = OpportunityTask(opportunity_id=opportunity_id, description=description)
        db.session.add(task)
        db.session.commit()
        flash('Task added.', 'success')
    else:
        flash('Task description cannot be empty.', 'warning')
    return redirect(url_for('opportunities.detail', id=opportunity_id))

@opportunities_bp.route('/task/<int:task_id>/toggle', methods=['POST'])
@login_required
def toggle_task(task_id):
    task = OpportunityTask.query.get_or_404(task_id)
    task.is_completed = not task.is_completed
    db.session.commit()
    flash('Task status updated.', 'info')
    return redirect(url_for('opportunities.detail', id=task.opportunity_id))

@opportunities_bp.route('/task/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = OpportunityTask.query.get_or_404(task_id)
    opportunity_id = task.opportunity_id
    db.session.delete(task)
    db.session.commit()
    flash('Task deleted.', 'success')
    return redirect(url_for('opportunities.detail', id=opportunity_id))