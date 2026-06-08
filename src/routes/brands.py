from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify
)
from ..models import db
from ..models.assets import Brand, AssetModel, Asset, Peripheral
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.logger import log_audit


brands_bp = Blueprint('brands', __name__)


# ----- Brand CRUD -----

@brands_bp.route('/')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def list_brands():
    brands = Brand.query.order_by(Brand.name).all()
    return render_template('brands/list.html', brands=brands)


@brands_bp.route('/<int:id>')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def brand_detail(id):
    brand = db.get_or_404(Brand, id)
    return render_template('brands/detail.html', brand=brand)


@brands_bp.route('/new', methods=['GET'])
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def new_brand():
    return render_template('brands/form.html', brand=None)


@brands_bp.route('/new', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def create_brand():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    name = (request.form.get('name') or '').strip()
    if not name:
        if is_ajax:
            return jsonify({'error': 'Brand name is required'}), 400
        flash('Brand name is required.', 'danger')
        return redirect(url_for('brands.new_brand'))
    existing = Brand.query.filter_by(name=name).first()
    if existing:
        if is_ajax:
            return jsonify({'id': existing.id, 'name': existing.name, 'existing': True})
        flash(f'Brand "{name}" already exists.', 'warning')
        return redirect(url_for('brands.list_brands'))
    brand = Brand(
        name=name,
        website=request.form.get('website') or None,
        notes=request.form.get('notes') or None,
    )
    db.session.add(brand)
    db.session.commit()
    log_audit(
        event_type='brand.created', action='create',
        target_object=f'Brand:{brand.id}', target_info=brand.name,
    )
    if is_ajax:
        return jsonify({'id': brand.id, 'name': brand.name, 'existing': False})
    flash(f'Brand "{brand.name}" created.', 'success')
    return redirect(url_for('brands.brand_detail', id=brand.id))


@brands_bp.route('/<int:id>/edit', methods=['GET'])
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def edit_brand(id):
    brand = db.get_or_404(Brand, id)
    return render_template('brands/form.html', brand=brand)


@brands_bp.route('/<int:id>/edit', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def update_brand(id):
    brand = db.get_or_404(Brand, id)
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('Brand name is required.', 'danger')
        return redirect(url_for('brands.edit_brand', id=id))
    clash = Brand.query.filter(Brand.name == name, Brand.id != id).first()
    if clash:
        flash(f'Another brand with name "{name}" already exists.', 'danger')
        return redirect(url_for('brands.edit_brand', id=id))
    brand.name = name
    brand.website = request.form.get('website') or None
    brand.notes = request.form.get('notes') or None
    db.session.commit()
    log_audit(
        event_type='brand.updated', action='update',
        target_object=f'Brand:{brand.id}', target_info=brand.name,
    )
    flash(f'Brand "{brand.name}" updated.', 'success')
    return redirect(url_for('brands.brand_detail', id=brand.id))


@brands_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def delete_brand(id):
    brand = db.get_or_404(Brand, id)
    in_use_assets = Asset.query.filter_by(brand_id=id).count()
    in_use_peripherals = Peripheral.query.filter_by(brand_id=id).count()
    if in_use_assets or in_use_peripherals:
        flash(
            f'Cannot delete brand "{brand.name}": in use by '
            f'{in_use_assets} asset(s) and {in_use_peripherals} peripheral(s).',
            'danger',
        )
        return redirect(url_for('brands.brand_detail', id=id))
    name = brand.name
    db.session.delete(brand)  # cascades to its AssetModels
    db.session.commit()
    log_audit(
        event_type='brand.deleted', action='delete',
        target_object=f'Brand:{id}', target_info=name,
    )
    flash(f'Brand "{name}" deleted.', 'success')
    return redirect(url_for('brands.list_brands'))


# ----- AssetModel CRUD (nested under brand) -----

@brands_bp.route('/<int:brand_id>/models/create', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def create_model(brand_id):
    """Create an AssetModel under a Brand.
    Supports both AJAX (returns JSON) and standard form POST.
    """
    brand = db.get_or_404(Brand, brand_id)
    if not has_write_permission('core_inventory'):
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'error': 'Write access required'}), 403
        flash('Write access required for this action.', 'danger')
        return redirect(url_for('brands.brand_detail', id=brand_id))

    # Accept both form posts and JSON. get_json(silent=True) avoids the 415 that
    # request.json raises on a non-JSON (e.g. multipart) request.
    payload = request.get_json(silent=True) or {}
    name = (request.form.get('name') or payload.get('name') or '').strip()
    notes = request.form.get('notes') or payload.get('notes')
    if not name:
        if request.is_json:
            return jsonify({'error': 'Model name is required'}), 400
        flash('Model name is required.', 'danger')
        return redirect(url_for('brands.brand_detail', id=brand_id))

    existing = AssetModel.query.filter_by(brand_id=brand.id, name=name).first()
    if existing:
        if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'id': existing.id, 'name': existing.name, 'brand_id': brand.id, 'existing': True})
        flash(f'Model "{name}" already exists for brand "{brand.name}".', 'warning')
        return redirect(url_for('brands.brand_detail', id=brand_id))

    model = AssetModel(name=name, brand_id=brand.id, notes=notes or None)
    db.session.add(model)
    db.session.commit()
    log_audit(
        event_type='asset_model.created', action='create',
        target_object=f'AssetModel:{model.id}', target_info=f'{brand.name} / {model.name}',
    )

    if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'id': model.id, 'name': model.name, 'brand_id': brand.id, 'existing': False})
    flash(f'Model "{model.name}" created.', 'success')
    return redirect(url_for('brands.brand_detail', id=brand_id))


@brands_bp.route('/<int:brand_id>/models/<int:model_id>/delete', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def delete_model(brand_id, model_id):
    model = db.get_or_404(AssetModel, model_id)
    if model.brand_id != brand_id:
        flash('Model does not belong to this brand.', 'danger')
        return redirect(url_for('brands.brand_detail', id=brand_id))
    in_use_assets = Asset.query.filter_by(model_id=model_id).count()
    in_use_peripherals = Peripheral.query.filter_by(model_id=model_id).count()
    if in_use_assets or in_use_peripherals:
        flash(
            f'Cannot delete model "{model.name}": in use by '
            f'{in_use_assets} asset(s) and {in_use_peripherals} peripheral(s).',
            'danger',
        )
        return redirect(url_for('brands.brand_detail', id=brand_id))
    name = model.name
    db.session.delete(model)
    db.session.commit()
    log_audit(
        event_type='asset_model.deleted', action='delete',
        target_object=f'AssetModel:{model_id}', target_info=name,
    )
    flash(f'Model "{name}" deleted.', 'success')
    return redirect(url_for('brands.brand_detail', id=brand_id))


# ----- JSON endpoint used by brand/model pickers in forms -----

@brands_bp.route('/<int:brand_id>/models.json')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def list_models_json(brand_id):
    """Returns the AssetModels for a given brand, sorted by name.
    Used by dependent <select> pickers in asset/peripheral forms.
    """
    models = AssetModel.query.filter_by(brand_id=brand_id).order_by(AssetModel.name).all()
    return jsonify([{'id': m.id, 'name': m.name} for m in models])
