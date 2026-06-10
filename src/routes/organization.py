from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, OrganizationSettings
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission

organization_bp = Blueprint('organization', __name__)


@organization_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@requires_permission('settings', access_level='READ_ONLY')
def settings():
    """View/update organization settings (singleton pattern)."""
    # Get or create the singleton settings record
    org_settings = OrganizationSettings.query.first()
    if not org_settings:
        org_settings = OrganizationSettings()
        db.session.add(org_settings)
        db.session.commit()

    if request.method == 'POST':
        if not has_write_permission('settings'):
            flash('Write access required to update organization settings.', 'danger')
            return redirect(url_for('organization.settings'))
        org_settings.legal_name = request.form.get('legal_name', '').strip()
        org_settings.tax_id = request.form.get('tax_id', '').strip()
        org_settings.primary_domain = request.form.get('primary_domain', '').strip()
        org_settings.email_domains = request.form.get('email_domains', '').strip()
        # Logo upload would be handled separately if needed
        
        db.session.commit()
        flash('Organization settings updated successfully!', 'success')
        return redirect(url_for('organization.settings'))

    return render_template('organization/settings.html', settings=org_settings)
