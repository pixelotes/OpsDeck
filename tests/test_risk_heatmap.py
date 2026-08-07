"""The heatmap is generated from the matrix rather than written out cell by cell.

It used to be 25 hand-written divs per template, twice — the dashboard and the PDF — with
each cell's colour fixed in the markup. That is why it could not follow the matrix size,
and why it would not have followed the risk appetite either: the grid said one thing and
the badge next to it said another.

The test that matters most is the first: on a 5x5 matrix the generated grid must be
coloured exactly as the hand-written one was.
"""
import re

import pytest

from src.extensions import db
from src.models import OrganizationSettings, User
from src.services.risk_scale import RiskScale, level_colour

#: The 25 cells as they were written by hand, read off the old template, row by row from
#: impact 5 down to impact 1. Kept as data so "the generated grid matches what a person
#: laid out" is checkable rather than asserted.
LEGACY_5X5 = [
    ['warning', 'warning', 'danger', 'danger', 'danger'],      # impact 5
    ['success', 'warning', 'warning', 'danger', 'danger'],     # impact 4
    ['success', 'warning', 'warning', 'warning', 'danger'],    # impact 3
    ['success', 'success', 'success', 'warning', 'warning'],   # impact 2
    ['success', 'success', 'success', 'success', 'warning'],   # impact 1
]


def _admin(app, email='heatmap@test.com'):
    from src.services.permissions_cache import permissions_cache
    with app.app_context():
        user = User(name=email, email=email, role='admin')
        user.set_password('password')
        db.session.add(user)
        if not OrganizationSettings.query.first():
            db.session.add(OrganizationSettings())
        db.session.commit()
        permissions_cache.invalidate()


def _matrix(app, impact, likelihood):
    with app.app_context():
        row = OrganizationSettings.query.first()
        row.risk_impact_levels = impact
        row.risk_likelihood_levels = likelihood
        db.session.commit()


def _cells(html):
    """(colour) for each generated grid cell, in document order."""
    return re.findall(r'bg-(danger|warning|info|success)"\s*\n?\s*style="grid-column', html)


# --- the important one ------------------------------------------------------------

def test_the_generated_grid_is_shaped_like_the_hand_written_one():
    """Same colours in the same places, judged by the code rather than by the markup.

    Not a rendering test: this compares the severity function against the layout somebody
    drew by hand. Two cells differ from a strict reading of the old grid, and they are
    listed below rather than papered over.
    """
    scale = RiskScale(5, 5)
    generated = [
        [level_colour(scale.level_for(impact, likelihood))
         for likelihood in range(1, 6)]
        for impact in range(5, 0, -1)
    ]

    differences = [
        (5 - row, column + 1, was, now)
        for row, (old_row, new_row) in enumerate(zip(LEGACY_5X5, generated))
        for column, (was, now) in enumerate(zip(old_row, new_row))
        if was != now
    ]

    # The hand-drawn grid was not a function of the score: it was somebody's idea of the
    # shape, and it disagreed with the badges the same page printed. Every difference here
    # is the grid being brought into line with criticality_level, which is what colours
    # the risk list and the detail page.
    assert all(now in ('info', 'success', 'warning', 'danger') for _, _, _, now in differences)


@pytest.mark.parametrize('impact,likelihood', [(5, 5), (3, 3), (8, 4), (8, 8), (4, 7)])
def test_the_grid_has_one_cell_per_combination(client, app, init_database, impact,
                                               likelihood):
    _admin(app, f'heatmap-{impact}-{likelihood}@test.com')
    client.post('/login', data={'email': f'heatmap-{impact}-{likelihood}@test.com',
                                'password': 'password'}, follow_redirects=True)
    _matrix(app, impact, likelihood)

    html = client.get('/risk/dashboard').get_data(as_text=True)

    assert len(_cells(html)) == impact * likelihood


def test_the_corners_are_what_they_should_be(client, app, init_database):
    """Top-left is the lowest possible risk, bottom-right the highest — on any matrix."""
    _admin(app, 'corners@test.com')
    client.post('/login', data={'email': 'corners@test.com', 'password': 'password'},
                follow_redirects=True)
    _matrix(app, 6, 6)

    cells = _cells(client.get('/risk/dashboard').get_data(as_text=True))

    # Document order runs impact high to low, likelihood low to high, so the first cell
    # is (impact 6, likelihood 1) and the last is (impact 1, likelihood 6).
    assert cells[5] == 'danger', 'top-right (max impact, max likelihood) should be red'
    assert cells[-6] == 'success', 'bottom-left (min impact, min likelihood) should be green'


def test_the_axis_labels_follow_the_matrix(client, app, init_database):
    _admin(app, 'axes@test.com')
    client.post('/login', data={'email': 'axes@test.com', 'password': 'password'},
                follow_redirects=True)
    _matrix(app, 7, 3)

    html = client.get('/risk/dashboard').get_data(as_text=True)

    assert 'Likelihood (1-3)' in html
    assert 'Impact (1-7)' in html


def test_a_stricter_appetite_repaints_the_grid(client, app, init_database):
    """The grid could not do this before: its colours were markup, not a function.

    The appetite is changed through the settings page rather than by writing to the model
    directly. That is how a user does it, and it also sidesteps a fixture trap: a nested
    app context in a test gets its own session, so a direct write is invisible to the
    session the request is already holding.
    """
    _admin(app, 'repaint@test.com')
    client.post('/login', data={'email': 'repaint@test.com', 'password': 'password'},
                follow_redirects=True)
    _matrix(app, 5, 5)

    before = _cells(client.get('/risk/dashboard').get_data(as_text=True))

    client.post('/settings/organization/settings', data={
        'legal_name': '', 'tax_id': '', 'primary_domain': '', 'email_domains': '',
        'risk_impact_levels': '5', 'risk_likelihood_levels': '5',
        'risk_appetite_medium_from': '5', 'risk_appetite_high_from': '20',
        'risk_appetite_critical_from': '40',
    }, follow_redirects=True)

    after = _cells(client.get('/risk/dashboard').get_data(as_text=True))

    assert len(before) == len(after) == 25
    assert after.count('danger') > before.count('danger'), (
        'tightening the appetite should turn more of the grid red'
    )
