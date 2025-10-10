from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, Location
from .main import login_required

locations_bp = Blueprint('locations', __name__)

@locations_bp.route('/')
@login_required
def locations():
    locations = Location.query.filter_by(is_archived=False).all()
    return render_template('locations/list.html', locations=locations)

@locations_bp.route('/archived')
@login_required
def archived_locations():
    locations = Location.query.filter_by(is_archived=True).all()
    return render_template('locations/archived.html', locations=locations)


@locations_bp.route('/<int:id>/archive', methods=['POST'])
@login_required
def archive_location(id):
    location = Location.query.get_or_404(id)
    location.is_archived = True
    db.session.commit()
    flash(f'Location "{location.name}" has been archived.')
    return redirect(url_for('locations.locations'))


@locations_bp.route('/<int:id>/unarchive', methods=['POST'])
@login_required
def unarchive_location(id):
    location = Location.query.get_or_404(id)
    location.is_archived = False
    db.session.commit()
    flash(f'Location "{location.name}" has been restored.')
    return redirect(url_for('locations.archived_locations'))


@locations_bp.route('/new', methods=['GET', 'POST'])
@login_required
def new_location():
    if request.method == 'POST':
        location = Location(name=request.form['name'])
        db.session.add(location)
        db.session.commit()
        flash('Location created successfully!')
        return redirect(url_for('locations.locations'))

    return render_template('locations/form.html')

@locations_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_location(id):
    location = Location.query.get_or_404(id)

    if request.method == 'POST':
        location.name = request.form['name']
        db.session.commit()
        flash('Location updated successfully!')
        return redirect(url_for('locations.locations'))

    return render_template('locations/form.html', location=location)

@locations_bp.route('/<int:id>')
@login_required
def location_detail(id):
    location = Location.query.get_or_404(id)
    return render_template('locations/detail.html', location=location)