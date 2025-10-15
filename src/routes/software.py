from flask import Blueprint, render_template, request, flash, redirect, url_for
from ..models import db, Software, Supplier, User, Group
from .main import login_required

software_bp = Blueprint('software', __name__, url_prefix='/software')

@software_bp.route('/')
@login_required
def list_software():
    page = request.args.get('page', 1, type=int)
    all_software = Software.query.filter_by(is_archived=False).order_by(Software.name.asc()).paginate(page=page, per_page=15)
    return render_template('software/list.html', all_software=all_software)

@software_bp.route('/<int:id>')
@login_required
def detail(id):
    software = Software.query.get_or_404(id)
    return render_template('software/detail.html', software=software)

@software_bp.route('/new', methods=['GET', 'POST'])
@login_required
def add_software():
    if request.method == 'POST':
        owner_type, owner_id = (request.form['owner'].split('_') + [None])[:2]

        new_software = Software(
            name=request.form['name'],
            category=request.form.get('category'),
            description=request.form.get('description'),
            supplier_id=request.form.get('supplier_id') or None,
            owner_type=owner_type,
            owner_id=owner_id or None,
            iso_27001_control_references=request.form.get('iso_27001_control_references')
        )
        db.session.add(new_software)
        db.session.commit()
        flash('Software added successfully!', 'success')
        return redirect(url_for('software.list_software'))

    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('software/form.html', software=None, suppliers=suppliers, users=users, groups=groups)

@software_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_software(id):
    software = Software.query.get_or_404(id)
    if request.method == 'POST':
        owner_type, owner_id = (request.form['owner'].split('_') + [None])[:2]

        software.name = request.form['name']
        software.category = request.form.get('category')
        software.description = request.form.get('description')
        software.supplier_id = request.form.get('supplier_id') or None
        software.owner_type = owner_type
        software.owner_id = owner_id or None
        software.iso_27001_control_references = request.form.get('iso_27001_control_references')
        
        db.session.commit()
        flash('Software updated successfully!', 'success')
        return redirect(url_for('software.detail', id=id))

    suppliers = Supplier.query.filter_by(is_archived=False).order_by(Supplier.name).all()
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    groups = Group.query.order_by(Group.name).all()
    return render_template('software/form.html', software=software, suppliers=suppliers, users=users, groups=groups)