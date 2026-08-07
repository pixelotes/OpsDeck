from flask import (
    Blueprint, render_template, request, redirect, url_for, flash
)
from ..models import db, OrganizationSettings
from .main import login_required
from ..services.permissions_service import requires_permission, has_write_permission
from ..services.risk_scale import (MAX_LEVELS, MIN_LEVELS, RiskAppetite,
                                  clamp_levels)

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

        # Risk matrix size. clamp_levels keeps it between 3 and 8 and falls back to 5 on
        # anything unparseable, so a hand-crafted form cannot produce a 400-cell grid or a
        # matrix with one level where nothing can be distinguished from anything else.
        #
        # Existing risks are untouched by design: each one recorded the matrix it was
        # scored against, so this applies to what gets assessed from now on. Say so, since
        # the opposite is the reasonable thing to assume.
        previous = (org_settings.risk_impact_levels, org_settings.risk_likelihood_levels)
        org_settings.risk_impact_levels = clamp_levels(
            request.form.get('risk_impact_levels'))
        org_settings.risk_likelihood_levels = clamp_levels(
            request.form.get('risk_likelihood_levels'))
        current = (org_settings.risk_impact_levels, org_settings.risk_likelihood_levels)

        # Risk appetite. RiskAppetite sorts and bounds the three values, so a form that
        # puts Critical below High is read as the obvious intent rather than refused.
        appetite = RiskAppetite(request.form.get('risk_appetite_medium_from'),
                                request.form.get('risk_appetite_high_from'),
                                request.form.get('risk_appetite_critical_from'))
        previous_appetite = (org_settings.risk_appetite_medium_from,
                             org_settings.risk_appetite_high_from,
                             org_settings.risk_appetite_critical_from)
        org_settings.risk_appetite_medium_from = appetite.medium_from
        org_settings.risk_appetite_high_from = appetite.high_from
        org_settings.risk_appetite_critical_from = appetite.critical_from

        # Logo upload would be handled separately if needed

        db.session.commit()

        if previous_appetite != (appetite.medium_from, appetite.high_from,
                                 appetite.critical_from):
            flash(
                f'Risk appetite updated: Medium from {appetite.medium_from}%, High from '
                f'{appetite.high_from}%, Critical from {appetite.critical_from}%. This '
                f'applies to every risk immediately — the register is re-judged against '
                f'it, so some risks may change colour.',
                'info')

        if current != previous:
            flash(
                f'Risk matrix changed to {current[0]}x{current[1]}. Risks already '
                f'assessed keep the {previous[0]}x{previous[1]} matrix they were scored '
                f'on; the new size applies to assessments from now on.',
                'info')
        flash('Organization settings updated successfully!', 'success')
        return redirect(url_for('organization.settings'))

    return render_template('organization/settings.html', settings=org_settings,
                           min_levels=MIN_LEVELS, max_levels=MAX_LEVELS)
