from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db
from ..models.assets import Brand, AssetModel, Asset, Peripheral
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from src.utils.logger import log_audit


asset_models_bp = Blueprint('asset_models', __name__)


@asset_models_bp.route('/')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def list_models():
    brand_id = request.args.get('brand_id', type=int)
    query = AssetModel.query.join(Brand)
    if brand_id:
        query = query.filter(AssetModel.brand_id == brand_id)
    models = query.order_by(Brand.name, AssetModel.name).all()
    brands = Brand.query.order_by(Brand.name).all()
    return render_template('asset_models/list.html', models=models, brands=brands,
                           selected_brand_id=brand_id)


@asset_models_bp.route('/<int:id>')
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def model_detail(id):
    model = db.get_or_404(AssetModel, id)
    return render_template('asset_models/detail.html', model=model)


@asset_models_bp.route('/new', methods=['GET'])
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def new_model():
    brands = Brand.query.order_by(Brand.name).all()
    return render_template('asset_models/form.html', model=None, brands=brands,
                           preselected_brand_id=request.args.get('brand_id', type=int))


@asset_models_bp.route('/new', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def create_model():
    name = (request.form.get('name') or '').strip()
    brand_id = request.form.get('brand_id', type=int)

    if not name:
        flash('Model name is required.', 'danger')
        return redirect(url_for('asset_models.new_model'))
    brand = db.session.get(Brand, brand_id) if brand_id else None
    if not brand:
        flash('A valid brand is required.', 'danger')
        return redirect(url_for('asset_models.new_model'))

    existing = AssetModel.query.filter_by(brand_id=brand.id, name=name).first()
    if existing:
        flash(f'Model "{name}" already exists for brand "{brand.name}".', 'warning')
        return redirect(url_for('asset_models.list_models'))

    model = AssetModel(name=name, brand_id=brand.id, notes=request.form.get('notes') or None)
    db.session.add(model)
    db.session.commit()
    log_audit(
        event_type='asset_model.created', action='create',
        target_object=f'AssetModel:{model.id}', target_info=f'{brand.name} / {model.name}',
    )
    flash(f'Model "{model.name}" created.', 'success')
    return redirect(url_for('asset_models.list_models'))


@asset_models_bp.route('/<int:id>/edit', methods=['GET'])
@login_required
@requires_permission('core_inventory', access_level='READ_ONLY')
def edit_model(id):
    model = db.get_or_404(AssetModel, id)
    brands = Brand.query.order_by(Brand.name).all()
    return render_template('asset_models/form.html', model=model, brands=brands,
                           preselected_brand_id=model.brand_id)


@asset_models_bp.route('/<int:id>/edit', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def update_model(id):
    model = db.get_or_404(AssetModel, id)
    name = (request.form.get('name') or '').strip()
    brand_id = request.form.get('brand_id', type=int)

    if not name:
        flash('Model name is required.', 'danger')
        return redirect(url_for('asset_models.edit_model', id=id))
    brand = db.session.get(Brand, brand_id) if brand_id else None
    if not brand:
        flash('A valid brand is required.', 'danger')
        return redirect(url_for('asset_models.edit_model', id=id))

    clash = AssetModel.query.filter(
        AssetModel.brand_id == brand.id,
        AssetModel.name == name,
        AssetModel.id != id,
    ).first()
    if clash:
        flash(f'Another model named "{name}" already exists for brand "{brand.name}".', 'danger')
        return redirect(url_for('asset_models.edit_model', id=id))

    model.name = name
    model.brand_id = brand.id
    model.notes = request.form.get('notes') or None
    db.session.commit()
    log_audit(
        event_type='asset_model.updated', action='update',
        target_object=f'AssetModel:{model.id}', target_info=f'{brand.name} / {model.name}',
    )
    flash(f'Model "{model.name}" updated.', 'success')
    return redirect(url_for('asset_models.list_models'))


@asset_models_bp.route('/<int:id>/delete', methods=['POST'])
@login_required
@requires_permission('core_inventory', access_level='WRITE')
def delete_model(id):
    model = db.get_or_404(AssetModel, id)
    in_use_assets = Asset.query.filter_by(model_id=id).count()
    in_use_peripherals = Peripheral.query.filter_by(model_id=id).count()
    if in_use_assets or in_use_peripherals:
        flash(
            f'Cannot delete model "{model.name}": in use by '
            f'{in_use_assets} asset(s) and {in_use_peripherals} peripheral(s).',
            'danger',
        )
        return redirect(url_for('asset_models.list_models'))
    name = model.name
    db.session.delete(model)
    db.session.commit()
    log_audit(
        event_type='asset_model.deleted', action='delete',
        target_object=f'AssetModel:{id}', target_info=name,
    )
    flash(f'Model "{name}" deleted.', 'success')
    return redirect(url_for('asset_models.list_models'))
