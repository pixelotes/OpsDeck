from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Location
from .main import login_required
from ..services.permissions_service import requires_permission

locations_bp = Blueprint('locations', __name__)

# Frequently-referenced literals (avoid duplication, Sonar S1192)
MODULE = 'core_inventory'
LIST_LOCATIONS = 'locations.list_locations'

@locations_bp.route('/', methods=['GET'])
@login_required
@requires_permission(MODULE)
def list_locations():
    locations = Location.query.filter_by(is_archived=False).all()
    return render_template('locations/list.html', locations=locations)

@locations_bp.route('/archived', methods=['GET'])
@login_required
@requires_permission(MODULE)
def archived_locations():
    locations = Location.query.filter_by(is_archived=True).all()
    return render_template('locations/archived.html', locations=locations)


@locations_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def archive_location(id):
    location = db.get_or_404(Location, id)
    location.is_archived = True
    db.session.commit()
    flash(f'Location "{location.name}" has been archived.', 'warning')
    return redirect(url_for(LIST_LOCATIONS))


@locations_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def unarchive_location(id):
    location = db.get_or_404(Location, id)
    location.is_archived = False
    db.session.commit()
    flash(f'Location "{location.name}" has been restored.', 'success')
    return redirect(url_for('locations.archived_locations'))


@locations_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def new_location():
    if request.method == 'POST':
        location = Location(
            name=request.form['name'],
            address=request.form.get('address', '').strip() or None,
            city=request.form.get('city', '').strip() or None,
            zip_code=request.form.get('zip_code', '').strip() or None,
            country=request.form.get('country', '').strip() or None,
            timezone=request.form.get('timezone', '').strip() or None,
            tax_id_override=request.form.get('tax_id_override', '').strip() or None,
            phone=request.form.get('phone', '').strip() or None,
            reception_email=request.form.get('reception_email', '').strip() or None
        )
        db.session.add(location)
        db.session.commit()
        flash('Location created successfully!', 'success')
        return redirect(url_for(LIST_LOCATIONS))

    return render_template('locations/form.html')

@locations_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@requires_permission(MODULE, access_level='WRITE')
def edit_location(id):
    location = db.get_or_404(Location, id)

    if request.method == 'POST':
        location.name = request.form['name']
        location.address = request.form.get('address', '').strip() or None
        location.city = request.form.get('city', '').strip() or None
        location.zip_code = request.form.get('zip_code', '').strip() or None
        location.country = request.form.get('country', '').strip() or None
        location.timezone = request.form.get('timezone', '').strip() or None
        location.tax_id_override = request.form.get('tax_id_override', '').strip() or None
        location.phone = request.form.get('phone', '').strip() or None
        location.reception_email = request.form.get('reception_email', '').strip() or None
        db.session.commit()
        flash('Location updated successfully!', 'success')
        return redirect(url_for(LIST_LOCATIONS))

    return render_template('locations/form.html', location=location)

@locations_bp.route('/<int:id>', methods=['GET'])
@login_required
def location_detail(id):
    location = db.get_or_404(Location, id)
    return render_template('locations/detail.html', location=location)