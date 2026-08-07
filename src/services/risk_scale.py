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

#: Lower bound of each band, as a percentage of the maximum possible score, highest first.
#:
#: These reproduce the thresholds they replace exactly. On a 5x5 matrix the maximum is 25,
#: so 80% is 20, 60% is 15 and 20% is 5 — which is precisely `>= 20`, `>= 15`, `>= 5`.
#: tests/test_risk_scale.py pins that equivalence across all 25 combinations, because
#: "the refactor changed no risk's severity" is the one claim worth proving here.
BANDS = (
    (80, 'Critical'),
    (60, 'High'),
    (20, 'Medium'),
    (0, 'Low'),
)


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

    def level_for(self, impact, likelihood):
        """Low / Medium / High / Critical for this pair on this scale."""
        raw = self.score(impact, likelihood)
        for lower_bound, name in BANDS:
            # Integer arithmetic on purpose: `raw / max_score >= 0.8` invites a float
            # comparison to decide whether a risk is Critical, and a value landing exactly
            # on a boundary is the normal case, not the edge case — 4x5 on a 5x5 matrix is
            # exactly 80%.
            if raw * 100 >= self.max_score * lower_bound:
                return name
        return BANDS[-1][1]

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
