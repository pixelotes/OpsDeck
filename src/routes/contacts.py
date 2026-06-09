from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Contact, Supplier
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

contacts_bp = Blueprint('contacts', __name__)

@contacts_bp.route('/', methods=['GET'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def contacts():
    contacts = Contact.query.filter_by(is_archived=False).join(Supplier).all()
    return render_template('contacts/list.html', contacts=contacts)

@contacts_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def archived_contacts():
    contacts = Contact.query.filter_by(is_archived=True).join(Supplier).all()
    return render_template('contacts/archived.html', contacts=contacts)

@contacts_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='WRITE')
def archive_contact(id):
    contact = db.get_or_404(Contact, id)
    contact.is_archived = True
    db.session.commit()
    flash(f'Contact "{contact.name}" has been archived.', 'warning')
    return redirect(url_for('contacts.contacts'))

@contacts_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='WRITE')
def unarchive_contact(id):
    contact = db.get_or_404(Contact, id)
    contact.is_archived = False
    db.session.commit()
    flash(f'Contact "{contact.name}" has been restored.', 'success')
    return redirect(url_for('contacts.archived_contacts'))

@contacts_bp.route('/<int:id>', methods=['GET'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def contact_detail(id):
    contact = db.get_or_404(Contact, id)
    return render_template('contacts/detail.html', contact=contact)

@contacts_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def new_contact():
    if request.method == 'POST':
        if not has_write_permission('procurement'):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for('contacts.contacts'))
        contact = Contact(
            name=request.form['name'],
            email=request.form.get('email'),
            phone=request.form.get('phone'),
            role=request.form.get('role'),
            supplier_id=request.form['supplier_id']
        )
        db.session.add(contact)
        db.session.commit()
        flash('Contact created successfully!', 'success')
        return redirect(url_for('contacts.contacts'))

    suppliers = Supplier.query.all()
    return render_template('contacts/form.html', suppliers=suppliers)

@contacts_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission('procurement', access_level='READ_ONLY')
def edit_contact(id):
    contact = db.get_or_404(Contact, id)

    if request.method == 'POST':
        if not has_write_permission('procurement'):
                flash('Write access required for this action.', 'danger')
                return redirect(url_for('contacts.contact_detail', id=id))
        contact.name = request.form['name']
        contact.email = request.form.get('email')
        contact.phone = request.form.get('phone')
        contact.role = request.form.get('role')
        contact.supplier_id = request.form['supplier_id']
        db.session.commit()
        flash('Contact updated successfully!', 'success')
        return redirect(url_for('contacts.contacts'))

    suppliers = Supplier.query.all()
    return render_template('contacts/form.html', contact=contact, suppliers=suppliers)

@contacts_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission('procurement', access_level='WRITE')
def delete_contact(id):
    contact = db.get_or_404(Contact, id)
    db.session.delete(contact)
    db.session.commit()
    flash('Contact deleted successfully!', 'success')
    return redirect(url_for('contacts.contacts'))