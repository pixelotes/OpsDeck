"""Configuring the risk matrix, and what happens to what was already scored.

The interesting case is not setting the size; it is changing it afterwards. A risk
assessed as 4 out of 5 must keep meaning "high" once the organisation moves to 8x8,
rather than quietly becoming "about half". That works because each risk records the
matrix it was scored against, and these tests are what hold that in place.
"""
import pytest

from src.extensions import db
from src.models import OrganizationSettings, Risk
from src.services.risk_scale import (DEFAULT_LEVELS, MAX_LEVELS, MIN_LEVELS,
                                      RiskScale, current_scale)


def _settings(app, impact=None, likelihood=None):
    with app.app_context():
        row = OrganizationSettings.query.first()
        if not row:
            row = OrganizationSettings()
            db.session.add(row)
        if impact is not None:
            row.risk_impact_levels = impact
        if likelihood is not None:
            row.risk_likelihood_levels = likelihood
        db.session.commit()


def _risk(app, description, impact, likelihood):
    with app.app_context():
        risk = Risk(risk_description=description, status='Draft',
                    inherent_impact=impact, inherent_likelihood=likelihood,
                    residual_impact=impact, residual_likelihood=likelihood)
        db.session.add(risk)
        db.session.commit()
        return risk.id


# --- the default ------------------------------------------------------------------

def test_the_default_matrix_is_still_five_by_five(app, init_database):
    """Nothing about this feature may change what an existing install does."""
    with app.app_context():
        row = OrganizationSettings()
        db.session.add(row)
        db.session.commit()

        assert row.risk_impact_levels == 5
        assert row.risk_likelihood_levels == 5
        assert DEFAULT_LEVELS == 5


def test_a_missing_settings_row_still_yields_five_by_five(app, init_database):
    """A fresh install has no row, and forms render before anyone visits settings."""
    with app.app_context():
        OrganizationSettings.query.delete()
        db.session.commit()

        assert current_scale() == RiskScale(5, 5)


# --- stamping ---------------------------------------------------------------------

def test_a_new_risk_records_the_organisation_s_current_matrix(app, init_database):
    _settings(app, impact=8, likelihood=4)
    risk_id = _risk(app, 'rectangular', 6, 3)

    with app.app_context():
        risk = db.session.get(Risk, risk_id)
        assert (risk.impact_levels, risk.likelihood_levels) == (8, 4)
        assert risk.scale.max_score == 32


def test_changing_the_matrix_does_not_touch_what_was_already_scored(app, init_database):
    """The whole reason the levels live on the risk."""
    _settings(app, impact=5, likelihood=5)
    old_id = _risk(app, 'scored on 5x5', 4, 5)          # 20/25 = 80% = Critical

    with app.app_context():
        old = db.session.get(Risk, old_id)
        assert old.criticality_level == 'Critical'
        assert old.residual_percent == 80

    _settings(app, impact=8, likelihood=8)

    with app.app_context():
        old = db.session.get(Risk, old_id)
        assert (old.impact_levels, old.likelihood_levels) == (5, 5), 'the old risk moved'
        assert old.criticality_level == 'Critical', 'severity changed under it'
        assert old.residual_percent == 80

    new_id = _risk(app, 'scored on 8x8', 4, 5)          # the same raw 20, of 64 = 31%

    with app.app_context():
        new = db.session.get(Risk, new_id)
        assert (new.impact_levels, new.likelihood_levels) == (8, 8)
        assert new.residual_score == db.session.get(Risk, old_id).residual_score
        assert new.residual_percent == 31
        assert new.criticality_level == 'Medium', (
            'the same raw score is much less severe on a bigger matrix, which is the '
            'point of comparing by percentage'
        )


# --- validation -------------------------------------------------------------------

@pytest.mark.parametrize('submitted,expected', [
    (99, MAX_LEVELS),
    (0, 1),
    (-3, 1),
    ('4', 4),
    ('nonsense', 1),
])
def test_a_score_outside_the_range_is_clamped_on_write(app, init_database, submitted,
                                                       expected):
    """Validated on the model, so the importer and the seeder cannot walk around it."""
    risk_id = _risk(app, f'submitted {submitted}', submitted, 3)

    with app.app_context():
        assert db.session.get(Risk, risk_id).residual_impact == expected


def test_a_null_score_is_not_turned_into_a_one(app, init_database):
    """The validator must pass None through rather than coercing it.

    On Risk the column default then fills it in, which is pre-existing behaviour and not
    this change's business. What matters is that the guard does not turn "not scored yet"
    into "scored 1" — a silent, wrong, and very low risk.
    """
    from src.services.risk_scale import clamp_score

    assert clamp_score(None) is None

    with app.app_context():
        risk = Risk(risk_description='half filled', status='Draft')
        risk.residual_impact = None
        db.session.add(risk)
        db.session.commit()

        # The column default applies at insert, so it lands on the default level.
        assert risk.residual_impact == DEFAULT_LEVELS


def test_an_assessment_item_keeps_a_null_score(app, init_database):
    """RiskAssessmentItem has no column default, so None reaches the database."""
    from src.models import RiskAssessment, RiskAssessmentItem

    with app.app_context():
        assessment = RiskAssessment(name='Q1')
        db.session.add(assessment)
        db.session.flush()

        item = RiskAssessmentItem(assessment_id=assessment.id, risk_description='x')
        db.session.add(item)
        db.session.commit()

        assert item.residual_impact is None
        assert item.residual_score == 0
        assert item.criticality_level == 'Low'


# --- the settings screen ----------------------------------------------------------

def _admin(app, email='matrix-admin@test.com'):
    from src.models import User
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        user = User(name=email, email=email, role='admin')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
        permissions_cache.invalidate()


@pytest.mark.parametrize('submitted,expected', [
    ('8', 8),
    ('2', MIN_LEVELS),        # below the floor
    ('40', MAX_LEVELS),       # a 1600-cell grid, politely declined
    ('', DEFAULT_LEVELS),
])
def test_the_settings_form_clamps_what_it_is_given(client, app, init_database,
                                                   submitted, expected):
    _admin(app)
    client.post('/login', data={'email': 'matrix-admin@test.com', 'password': 'password'},
                follow_redirects=True)

    response = client.post('/settings/organization/settings', data={
        'legal_name': 'ACME', 'tax_id': '', 'primary_domain': '', 'email_domains': '',
        'risk_impact_levels': submitted, 'risk_likelihood_levels': '5',
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert OrganizationSettings.query.first().risk_impact_levels == expected


def test_changing_the_size_tells_the_user_what_it_did_not_do(client, app, init_database):
    """Assuming a resize rescales the register is the reasonable assumption. It doesn't."""
    _admin(app, 'matrix-admin2@test.com')
    client.post('/login', data={'email': 'matrix-admin2@test.com', 'password': 'password'},
                follow_redirects=True)

    response = client.post('/settings/organization/settings', data={
        'legal_name': 'ACME', 'tax_id': '', 'primary_domain': '', 'email_domains': '',
        'risk_impact_levels': '7', 'risk_likelihood_levels': '7',
    }, follow_redirects=True)

    body = response.get_data(as_text=True)
    assert '7x7' in body or '7&times;7' in body
    assert 'keep the 5x5 matrix' in body
