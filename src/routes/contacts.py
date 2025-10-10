from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Contact, Supplier
from .main import login_required

contacts_bp = Blueprint('contacts', __name__)

@contacts_bp.route('/')
@login_required
def contacts():
    contacts = Contact.query.filter_by(is_archived=False).join(Supplier).all()
    return render_template('contacts/list.html', contacts=contacts)

@contacts_bp.route('/archived')
@login_required
def archived_contacts():
    contacts = Contact.query.filter_by(is_archived=True).join(Supplier).all()
    return render_template('contacts/archived.html', contacts=contacts)

@contacts_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_contact(id):
    contact = Contact.query.get_or_404(id)
    contact.is_archived = True
    db.session.commit()
    flash(f'Contact "{contact.name}" has been archived.')
    return redirect(url_for('contacts.contacts'))

@contacts_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_contact(id):
    contact = Contact.query.get_or_404(id)
    contact.is_archived = False
    db.session.commit()
    flash(f'Contact "{contact.name}" has been restored.')
    return redirect(url_for('contacts.archived_contacts'))

@contacts_bp.route('/<int:id>')
@login_required
def contact_detail(id):
    contact = Contact.query.get_or_404(id)
    return render_template('contacts/detail.html', contact=contact)

@contacts_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_contact():
    if request.method == 'POST':
        contact = Contact(
            name=request.form['name'],
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            role=request.form.get('role'),
            supplier_id=request.form['supplier_id']
        )
        db.session.add(contact)
        db.session.commit()
        flash('Contact created successfully!')
        return redirect(url_for('contacts.contacts'))

    suppliers = Supplier.query.all()
    return render_template('contacts/form.html', suppliers=suppliers)

@contacts_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_contact(id):
    contact = Contact.query.get_or_404(id)

    if request.method == 'POST':
        contact.name = request.form['name']
        contact.email = request.form.get('email')
        contact.phone = request.form.get('phone')
        contact.role = request.form.get('role')
        contact.supplier_id = request.form['supplier_id']
        db.session.commit()
        flash('Contact updated successfully!')
        return redirect(url_for('contacts.contacts'))

    suppliers = Supplier.query.all()
    return render_template('contacts/form.html', contact=contact, suppliers=suppliers)

@contacts_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
def delete_contact(id):
    contact = Contact.query.get_or_404(id)
    db.session.delete(contact)
    db.session.commit()
    flash('Contact deleted successfully!')
    return redirect(url_for('contacts.contacts'))