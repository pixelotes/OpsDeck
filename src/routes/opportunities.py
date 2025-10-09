from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from datetime import datetime
from ..models import db, Opportunity, Activity, Supplier, Contact
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
        )
        db.session.add(opportunity)
        db.session.commit()
        flash('Opportunity created successfully!', 'success')
        return redirect(url_for('opportunities.list_opportunities'))
    
    suppliers = Supplier.query.order_by(Supplier.name).all()
    contacts = Contact.query.order_by(Contact.name).all()
    return render_template('opportunities/form.html', suppliers=suppliers, contacts=contacts)

@opportunities_bp.route('/<int:id>')
@login_required
def detail(id):
    opportunity = Opportunity.query.get_or_404(id)
    return render_template('opportunities/detail.html', opportunity=opportunity)

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