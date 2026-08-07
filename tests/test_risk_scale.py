"""The risk matrix, and the promise that centralising it changed nobody's severity.

The naming used to be `score >= 20 / >= 15 / >= 5`, written out in six places. Those
numbers only mean anything while the matrix is 5x5 and the maximum score is 25, which is
why they are percentages now. The first test here is the important one: it walks every
impact/likelihood pair on a 5x5 matrix and checks the new code agrees with the old
thresholds on all 25 of them.
"""
import pytest

from src.services.risk_scale import (BANDS, DEFAULT_LEVELS, MAX_LEVELS, MIN_LEVELS,
                                     RiskScale, clamp_levels)


def _legacy_level(score):
    """The thresholds exactly as they were written before this module existed."""
    if score >= 20:
        return 'Critical'
    elif score >= 15:
        return 'High'
    elif score >= 5:
        return 'Medium'
    return 'Low'


@pytest.mark.parametrize('impact', range(1, 6))
@pytest.mark.parametrize('likelihood', range(1, 6))
def test_a_five_by_five_matrix_names_every_pair_exactly_as_before(impact, likelihood):
    scale = RiskScale(5, 5)

    assert scale.level_for(impact, likelihood) == _legacy_level(impact * likelihood), (
        f'{impact}x{likelihood} = {impact * likelihood} on a 5x5 matrix'
    )


def test_the_boundaries_land_where_they_did():
    """The three scores that sit exactly on a band edge, which is where a float would bite."""
    scale = RiskScale(5, 5)

    assert scale.level_for(4, 5) == 'Critical'   # 20, exactly 80%
    assert scale.level_for(3, 5) == 'High'       # 15, exactly 60%
    assert scale.level_for(1, 5) == 'Medium'     # 5, exactly 20%
    assert scale.level_for(2, 2) == 'Low'        # 4, just under


# --- what changing the matrix does -------------------------------------------------

def test_the_same_position_on_different_scales_gets_the_same_name():
    """The point of percentages: 4/5 and 6/8 are both 80% of the way up."""
    assert RiskScale(5, 5).level_for(4, 5) == 'Critical'
    assert RiskScale(8, 8).level_for(7, 8) == 'Critical'   # 56/64 = 87%
    assert RiskScale(3, 3).level_for(3, 3) == 'Critical'   # 9/9 = 100%


def test_the_top_of_any_matrix_is_critical_and_the_bottom_is_low():
    """A matrix where nothing can ever be Critical is the failure this replaces.

    With the old absolute thresholds, a 3x3 matrix topped out at 9 and no risk in the
    organisation could reach 20, so every one of them was Low or Medium forever.
    """
    for impact in range(MIN_LEVELS, MAX_LEVELS + 1):
        for likelihood in range(MIN_LEVELS, MAX_LEVELS + 1):
            scale = RiskScale(impact, likelihood)
            assert scale.level_for(impact, likelihood) == 'Critical', scale
            assert scale.level_for(1, 1) == 'Low', scale


def test_percent_is_what_compares_across_scales():
    """The raw product cannot be compared between matrices; this is what can."""
    assert RiskScale(5, 5).percent(4, 5) == 80
    assert RiskScale(8, 8).percent(4, 5) == 31    # the same raw 20 is much lower on 8x8
    assert RiskScale(3, 3).percent(3, 3) == 100


def test_a_rectangular_matrix_is_allowed():
    """More granularity on impact than on likelihood is a normal way to run this."""
    scale = RiskScale(impact_levels=8, likelihood_levels=4)

    assert scale.max_score == 32
    assert scale.levels('impact') == list(range(1, 9))
    assert scale.levels('likelihood') == list(range(1, 5))
    assert scale.level_for(8, 4) == 'Critical'


# --- the guard rails ---------------------------------------------------------------

@pytest.mark.parametrize('given,expected', [
    (5, 5),
    (2, MIN_LEVELS),          # below the minimum
    (99, MAX_LEVELS),         # above the maximum
    ('7', 7),                 # a form field arrives as a string
    ('nonsense', DEFAULT_LEVELS),
    (None, DEFAULT_LEVELS),
])
def test_level_counts_are_clamped_into_range(given, expected):
    assert clamp_levels(given) == expected


def test_a_scale_clamps_its_own_levels_on_construction():
    """Nothing validated these before, so a stored 99 has to survive being read."""
    assert RiskScale(99, 1) == RiskScale(MAX_LEVELS, MIN_LEVELS)


def test_a_value_above_the_matrix_is_brought_back_in_range():
    """Shrinking the matrix leaves existing risks holding values it no longer has."""
    scale = RiskScale(3, 3)

    assert scale.clamp_value(9) == 3
    assert scale.clamp_value(0) == 1
    assert scale.clamp_value(None) == 1


def test_a_missing_score_does_not_raise():
    """Both columns are nullable, and a half-filled risk is a real state in this app."""
    scale = RiskScale(5, 5)

    assert scale.score(None, 3) == 0
    assert scale.level_for(None, None) == 'Low'


def test_the_bands_are_ordered_and_reach_zero():
    """A gap between bands would leave a score with no name at all."""
    bounds = [bound for bound, _ in BANDS]

    assert bounds == sorted(bounds, reverse=True)
    assert bounds[-1] == 0
