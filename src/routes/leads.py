from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..models import db, Lead, Opportunity, Supplier
from .main import login_required

leads_bp = Blueprint('leads', __name__, url_prefix='/leads')

@leads_bp.route('/')
@login_required
def list_leads():
    leads = Lead.query.order_by(Lead.created_at.desc()).all()
    return render_template('leads/list.html', leads=leads)

@leads_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_lead():
    if request.method == 'POST':
        lead = Lead(
            company_name=request.form['company_name'],
            contact_name=request.form.get('contact_name'),
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            status=request.form.get('status', 'New'),
            notes=request.form.get('notes')
        )
        db.session.add(lead)
        db.session.commit()
        flash('Lead created successfully.', 'success')
        return redirect(url_for('leads.list_leads'))
    return render_template('leads/form.html')

@leads_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_lead(id):
    lead = Lead.query.get_or_404(id)
    if request.method == 'POST':
        lead.company_name = request.form['company_name']
        lead.contact_name = request.form.get('contact_name')
        lead.email = request.form.get('email')
        lead.phone = request.form.get('phone')
        lead.status = request.form.get('status')
        lead.notes = request.form.get('notes')
        db.session.commit()
        flash('Lead updated successfully.', 'success')
        return redirect(url_for('leads.list_leads'))
    return render_template('leads/form.html', lead=lead)

@leads_bp.route('/<int:id>/convert', methods=['GET', 'POST'])
@login_required
def convert_lead(id):
    lead = Lead.query.get_or_404(id)
    if lead.status == 'Converted':
        flash('This lead has already been converted.', 'warning')
        return redirect(url_for('leads.list_leads'))

    if request.method == 'POST':
        conversion_type = request.form.get('conversion_type')
        lead.status = 'Converted'
        
        if conversion_type == 'opportunity':
            opportunity = Opportunity(
                name=f"Opportunity from {lead.company_name}",
                status='Evaluating'
            )
            db.session.add(opportunity)
            db.session.commit()
            flash('Lead converted to a new Opportunity.', 'success')
            return redirect(url_for('opportunities.edit_opportunity', id=opportunity.id))

        elif conversion_type == 'supplier':
            supplier = Supplier(
                name=lead.company_name,
                email=lead.email,
                phone=lead.phone
            )
            db.session.add(supplier)
            db.session.commit()
            flash('Lead converted to a new Supplier.', 'success')
            return redirect(url_for('suppliers.edit_supplier', id=supplier.id))
            
    return render_template('leads/convert.html', lead=lead)