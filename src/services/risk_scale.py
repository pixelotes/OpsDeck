"""The risk matrix: how a score is computed and what it is called.

Every risk carries an impact and a likelihood chosen from a scale — 1..5 historically,
configurable now. The score is their product, and a name (Low/Medium/High/Critical) comes
from where that product sits.

The whole reason this is a module rather than four lines in a model is that the naming
used to be `score >= 20`, repeated in six places, and 20 only means "critical" while the
scale is 5x5 and the maximum is 25. Change the matrix to 3x3 and the highest score
possible becomes 9, so nothing is ever Critical again — silently, with no error anywhere.

So the bands are fractions of the maximum, and comparison happens on that fraction rather
than on the raw product. That is also what lets a company change its matrix and keep its
history: a 4 out of 5 and a 6 out of 8 are both 80% of the way up their own scale, and
they should rank the same. A risk therefore records the scale it was scored against, and
old risks keep meaning what they meant when somebody assessed them.
"""
from dataclasses import dataclass

#: What the matrix was before it could be configured. New rows default to this so the
#: migration for existing data is a no-op.
DEFAULT_LEVELS = 5

#: Fewer than three levels cannot express "middling", and past eight the grid stops being
#: readable — 8x8 is already 64 cells to render and to colour.
MIN_LEVELS = 3
MAX_LEVELS = 8

#: Where the bands fall by default, as percentages of the maximum possible score.
#:
#: These reproduce the thresholds they replace exactly. On a 5x5 matrix the maximum is 25,
#: so 80% is 20, 60% is 15 and 20% is 5 — which is precisely `>= 20`, `>= 15`, `>= 5`.
#: tests/test_risk_scale.py pins that equivalence across all 25 combinations, because
#: "the refactor changed no risk's severity" is the one claim worth proving here.
DEFAULT_MEDIUM_FROM = 20
DEFAULT_HIGH_FROM = 60
DEFAULT_CRITICAL_FROM = 80


@dataclass(frozen=True)
class RiskAppetite:
    """Where an organisation draws the line between green, amber and red.

    Two settings govern a severity and they are not the same kind of thing, which is why
    this is separate from RiskScale and behaves differently:

    * The matrix size is *how you measured*. Changing it must not reinterpret past
      assessments, so every risk records the matrix it was scored on. Re-measuring
      history would falsify it.
    * The appetite is *what you are willing to tolerate*. It is current policy, and
      changing it is meant to re-judge the whole register — telling the organisation
      which of the risks it already holds are no longer acceptable. Stamping it per risk
      would defeat the purpose: you would tighten your appetite and the register would
      keep reporting yesterday's verdicts.

    So appetite is read live from settings, and scores are re-coloured the moment it
    changes.
    """

    medium_from: int = DEFAULT_MEDIUM_FROM
    high_from: int = DEFAULT_HIGH_FROM
    critical_from: int = DEFAULT_CRITICAL_FROM

    def __post_init__(self):
        # Sorted rather than rejected: these arrive from a form, and three numbers in the
        # wrong order is a mistake with an obvious reading, not a reason to refuse.
        # Bounds first, so a 0 or a 300 cannot survive by being in order.
        values = sorted(max(1, min(100, _as_int(value, fallback)))
                        for value, fallback in (
                            (self.medium_from, DEFAULT_MEDIUM_FROM),
                            (self.high_from, DEFAULT_HIGH_FROM),
                            (self.critical_from, DEFAULT_CRITICAL_FROM)))
        object.__setattr__(self, 'medium_from', values[0])
        object.__setattr__(self, 'high_from', values[1])
        object.__setattr__(self, 'critical_from', values[2])

    @property
    def bands(self):
        """Lower bound and name of each band, highest first."""
        return (
            (self.critical_from, 'Critical'),
            (self.high_from, 'High'),
            (self.medium_from, 'Medium'),
            (0, 'Low'),
        )

    def level_for_percent(self, percent):
        for lower_bound, name in self.bands:
            if percent >= lower_bound:
                return name
        return 'Low'


def _as_int(value, fallback):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


#: The appetite in force when nothing says otherwise — the thresholds that were hardcoded.
DEFAULT_APPETITE = RiskAppetite()

#: Bootstrap contextual class per severity, so the register, the detail page, the cards
#: and the heatmap agree. This mapping was written out inline in four templates as a chain
#: of conditionals, which is why the heatmap grid could drift from the badges beside it.
LEVEL_COLOURS = {
    'Critical': 'danger',
    'High': 'warning',
    'Medium': 'info',
    'Low': 'success',
}


def level_colour(level):
    """Bootstrap contextual class for a severity name."""
    return LEVEL_COLOURS.get(level, 'secondary')


def clamp_score(value):
    """Coerce a submitted impact or likelihood into 1..MAX_LEVELS.

    The upper bound is the largest matrix anyone can configure, not the largest this
    particular risk allows: this runs on the model, before the risk's own matrix columns
    have their defaults, so it is the outer bound. None passes through — both score
    columns are nullable and a half-filled risk is a real state.
    """
    if value is None:
        return None
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 1
    return max(1, min(MAX_LEVELS, score))


def clamp_levels(value):
    """Coerce a level count into the supported range, falling back to the default."""
    try:
        levels = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LEVELS
    return max(MIN_LEVELS, min(MAX_LEVELS, levels))


@dataclass(frozen=True)
class RiskScale:
    """An impact x likelihood matrix. Rectangular: the two axes are independent.

    Frozen because a scale is a fact about how something was measured, not a setting to
    mutate: changing the organisation's matrix produces a new scale for new assessments
    and leaves the old ones alone.
    """

    impact_levels: int = DEFAULT_LEVELS
    likelihood_levels: int = DEFAULT_LEVELS

    def __post_init__(self):
        object.__setattr__(self, 'impact_levels', clamp_levels(self.impact_levels))
        object.__setattr__(self, 'likelihood_levels', clamp_levels(self.likelihood_levels))

    @property
    def max_score(self):
        return self.impact_levels * self.likelihood_levels

    def score(self, impact, likelihood):
        """The raw product, which is what gets displayed and stored."""
        return (impact or 0) * (likelihood or 0)

    def percent(self, impact, likelihood):
        """Where the score sits on this scale, 0-100.

        This is the number to compare across scales, sort by, or feed a chart. The raw
        product cannot be compared between matrices of different sizes: 12 is most of the
        way up a 4x4 and barely halfway up a 5x5.
        """
        return round(100 * self.score(impact, likelihood) / self.max_score)

    def level_for(self, impact, likelihood, appetite=None):
        """Low / Medium / High / Critical for this pair, under the given appetite."""
        raw = self.score(impact, likelihood)
        appetite = appetite or DEFAULT_APPETITE

        for lower_bound, name in appetite.bands:
            # Integer arithmetic on purpose: `raw / max_score >= 0.8` invites a float
            # comparison to decide whether a risk is Critical, and a value landing exactly
            # on a boundary is the normal case, not the edge case — 4x5 on a 5x5 matrix is
            # exactly 80%. Comparing against the rounded percent would misjudge the
            # boundary too, so the raw product is compared instead.
            if raw * 100 >= self.max_score * lower_bound:
                return name
        return 'Low'

    def levels(self, axis):
        """1..n for 'impact' or 'likelihood', for rendering axes and building selects."""
        count = self.impact_levels if axis == 'impact' else self.likelihood_levels
        return list(range(1, count + 1))

    def clamp_value(self, value):
        """Bring a stored or submitted level into range.

        Needed because nothing validated these before: a risk can already hold a 99, and
        shrinking the matrix leaves values above the new maximum.
        """
        try:
            level = int(value)
        except (TypeError, ValueError):
            return 1
        return max(1, min(max(self.impact_levels, self.likelihood_levels), level))


#: The scale used when nothing says otherwise — what every existing risk was scored on.
DEFAULT_SCALE = RiskScale()


def _settings_row():
    """The organisation settings singleton, fetched once per request.

    Cached because criticality_level runs inside loops over the whole register — the risk
    dashboard reads it for every risk it renders — and an uncached lookup would turn that
    into one query per row. Falls back to None whenever there is no row, no table or no
    application context: a fresh install has none of them, and this is reached while
    rendering pages, where raising would lose the page over a setting nobody has chosen.
    """
    try:
        from flask import has_app_context, has_request_context, request
        from ..models.core import OrganizationSettings

        if not has_app_context():
            return None

        # Cached on the request, not on `g`. `g` lives as long as the application
        # context, which outlives a single request in a CLI command or a background job —
        # and there, code that changes the settings and then reads them back would get
        # the value from before its own write.
        if not has_request_context():
            return OrganizationSettings.query.first()

        if not hasattr(request, '_risk_settings'):
            request._risk_settings = OrganizationSettings.query.first()
        return request._risk_settings
    except Exception:
        return None


def current_scale():
    """The organisation's configured matrix, for scoring something new.

    Only for new assessments. Reading an existing risk goes through its own stored
    levels, never through this: that is the whole point of storing them.
    """
    settings = _settings_row()
    if settings is None:
        return DEFAULT_SCALE

    return RiskScale(settings.risk_impact_levels, settings.risk_likelihood_levels)


def current_appetite():
    """The appetite in force right now, applied to every risk as it is read.

    Deliberately not stamped per risk — see RiskAppetite. Tightening the appetite is
    supposed to re-judge the register, which is the reason to change it.
    """
    settings = _settings_row()
    if settings is None:
        return DEFAULT_APPETITE

    return RiskAppetite(settings.risk_appetite_medium_from,
                        settings.risk_appetite_high_from,
                        settings.risk_appetite_critical_from)
