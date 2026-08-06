"""Roadmaps module — strategic planning of goals and initiatives over periods.

Positioning model: an initiative is placed on a 1-based integer *step* grid, where
each period (typically a quarter) is subdivided into ``STEPS_PER_PERIOD`` steps.
Steps are the source of truth — they are what the Gantt view drags and snaps to.
``planned_start_date`` / ``planned_end_date`` are denormalised from the steps and the
owning period's date range so that dates remain queryable in SQL (reports, event
engine). They are recomputed by ``services.roadmaps_service.recompute_dates`` and must
never be written directly from the API.
"""
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from .core import CustomPropertiesMixin
from src.utils.timezone_helper import now, today

# Each period is subdivided into this many draggable steps.
STEPS_PER_PERIOD = 4

ROADMAP_STATUSES = ('draft', 'active', 'archived')
INITIATIVE_STATUSES = ('planned', 'in_progress', 'done')
INITIATIVE_PRIORITIES = ('very_low', 'low', 'medium', 'high', 'very_high')

DEFAULT_GOAL_COLOR = '#2E5F9E'

# Entity types an initiative may be linked to (see RoadmapInitiativeLink). The UI for
# this lands in a later phase; the whitelist is the contract both ends validate against.
ROADMAP_LINKABLE_TYPES = (
    'Asset', 'Peripheral', 'License', 'Software', 'Subscription', 'Purchase',
    'Budget', 'BusinessService', 'Change', 'Request', 'Risk', 'Contract', 'Supplier',
)

# Bootstrap contextual colours, mirroring the status_color convention used by
# Certificate and other entities so templates can render badges without logic.
STATUS_COLORS = {'planned': 'secondary', 'in_progress': 'info', 'done': 'success'}
PRIORITY_COLORS = {
    'very_low': 'secondary', 'low': 'info', 'medium': 'primary',
    'high': 'warning', 'very_high': 'danger',
}


class Roadmap(db.Model):
    """A roadmap: the container for periods, goals and initiatives."""
    __tablename__ = 'roadmap'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), nullable=False, default='draft')
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    owner = db.relationship('User', foreign_keys=[owner_id])
    periods = db.relationship(
        'RoadmapPeriod', backref='roadmap', lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        order_by='RoadmapPeriod.position, RoadmapPeriod.id')
    goals = db.relationship(
        'RoadmapGoal', backref='roadmap', lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        order_by='RoadmapGoal.position, RoadmapGoal.id')

    @property
    def initiatives(self):
        """Query over every initiative in this roadmap, across all its goals."""
        return (RoadmapInitiative.query
                .join(RoadmapGoal, RoadmapInitiative.goal_id == RoadmapGoal.id)
                .filter(RoadmapGoal.roadmap_id == self.id)
                .order_by(RoadmapGoal.position, RoadmapInitiative.position))

    @property
    def goal_count(self):
        return self.goals.count()

    @property
    def initiative_count(self):
        return self.initiatives.count()

    @property
    def period_count(self):
        return self.periods.count()

    @property
    def progress(self):
        """Overall completion 0-100, weighted by story points (unpointed count as 1)."""
        initiatives = self.initiatives.all()
        if not initiatives:
            return 0
        weights = [(i, i.points or 1) for i in initiatives]
        total = sum(w for _, w in weights)
        done = sum((i.progress or 0) * w for i, w in weights)
        return round(done / total)

    @property
    def overdue_count(self):
        return sum(1 for i in self.initiatives.all() if i.is_overdue)

    @property
    def date_range_label(self):
        """Human label spanning the first and last period, e.g. "Q1 2027 – Q2 2028"."""
        periods = self.periods.all()
        if not periods:
            return None
        if len(periods) == 1:
            return periods[0].label
        return f"{periods[0].label} – {periods[-1].label}"

    @property
    def status_color(self):
        return {'draft': 'secondary', 'active': 'success', 'archived': 'dark'}.get(
            self.status, 'secondary')

    def __repr__(self):
        return f'<Roadmap {self.id} {self.name}>'


class RoadmapPeriod(db.Model):
    """A column of the roadmap: usually a quarter, but any labelled date range."""
    __tablename__ = 'roadmap_period'

    id = db.Column(db.Integer, primary_key=True)
    roadmap_id = db.Column(db.Integer, db.ForeignKey('roadmap.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    label = db.Column(db.String(50), nullable=False)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    @property
    def has_dates(self):
        return bool(self.start_date and self.end_date)

    def __repr__(self):
        return f'<RoadmapPeriod {self.id} {self.label}>'


class RoadmapGoal(db.Model):
    """A swimlane of the roadmap: a goal grouping related initiatives."""
    __tablename__ = 'roadmap_goal'

    id = db.Column(db.Integer, primary_key=True)
    roadmap_id = db.Column(db.Integer, db.ForeignKey('roadmap.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    color = db.Column(db.String(7), nullable=False, default=DEFAULT_GOAL_COLOR)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    owner = db.relationship('User', foreign_keys=[owner_id])
    initiatives = db.relationship(
        'RoadmapInitiative', backref='goal', lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        order_by='RoadmapInitiative.position, RoadmapInitiative.id')

    def __repr__(self):
        return f'<RoadmapGoal {self.id} {self.name}>'


class RoadmapInitiative(db.Model, CustomPropertiesMixin):
    """A bar on the roadmap: a unit of planned work spanning one or more steps."""
    __tablename__ = 'roadmap_initiative'

    id = db.Column(db.Integer, primary_key=True)
    goal_id = db.Column(db.Integer, db.ForeignKey('roadmap_goal.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False, default='')

    # Position on the step grid (1-based, inclusive on both ends).
    start_step = db.Column(db.Integer, nullable=False, default=1)
    end_step = db.Column(db.Integer, nullable=False, default=STEPS_PER_PERIOD)

    # Denormalised from the steps — see module docstring. Never written by the API.
    planned_start_date = db.Column(db.Date, nullable=True, index=True)
    planned_end_date = db.Column(db.Date, nullable=True, index=True)

    status = db.Column(db.String(50), nullable=False, default='planned')
    priority = db.Column(db.String(50), nullable=False, default='medium')
    progress = db.Column(db.Integer, nullable=False, default=0)
    points = db.Column(db.Integer, nullable=True)
    is_new = db.Column(db.Boolean, nullable=False, default=False)

    # External ticket: the key and the link are separate fields so no string parsing
    # is needed to build the href.
    external_ref = db.Column(db.String(100), nullable=False, default='')
    external_url = db.Column(db.String(500), nullable=True)

    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    position = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())

    owner = db.relationship('User', foreign_keys=[owner_id])
    links = db.relationship(
        'RoadmapInitiativeLink', backref='initiative', lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN)

    @property
    def roadmap(self):
        return self.goal.roadmap if self.goal else None

    @property
    def duration_steps(self):
        return self.end_step - self.start_step + 1

    @property
    def duration_periods(self):
        """Duration in periods, e.g. 1.5 for six steps at four steps per period."""
        return self.duration_steps / STEPS_PER_PERIOD

    @property
    def is_overdue(self):
        """Past its planned end date without being done."""
        if self.status == 'done' or not self.planned_end_date:
            return False
        return self.planned_end_date < today()

    @property
    def predecessors(self):
        """Initiatives this one depends on."""
        return [d.predecessor for d in self.incoming_dependencies.all()]

    @property
    def successors(self):
        """Initiatives depending on this one."""
        return [d.successor for d in self.outgoing_dependencies.all()]

    @property
    def status_color(self):
        return STATUS_COLORS.get(self.status, 'secondary')

    @property
    def priority_color(self):
        return PRIORITY_COLORS.get(self.priority, 'secondary')

    def __repr__(self):
        return f'<RoadmapInitiative {self.id} {self.name}>'


class RoadmapDependency(db.Model):
    """Finish-to-start link: ``successor.start_step = predecessor.end_step + lag``."""
    __tablename__ = 'roadmap_dependency'

    id = db.Column(db.Integer, primary_key=True)
    predecessor_id = db.Column(
        db.Integer, db.ForeignKey('roadmap_initiative.id', ondelete='CASCADE'),
        nullable=False, index=True)
    successor_id = db.Column(
        db.Integer, db.ForeignKey('roadmap_initiative.id', ondelete='CASCADE'),
        nullable=False, index=True)
    lag = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=lambda: now())

    predecessor = db.relationship(
        'RoadmapInitiative', foreign_keys=[predecessor_id],
        backref=db.backref('outgoing_dependencies', lazy=LAZY_DYNAMIC,
                           cascade=CASCADE_ALL_DELETE_ORPHAN))
    successor = db.relationship(
        'RoadmapInitiative', foreign_keys=[successor_id],
        backref=db.backref('incoming_dependencies', lazy=LAZY_DYNAMIC,
                           cascade=CASCADE_ALL_DELETE_ORPHAN))

    __table_args__ = (
        db.UniqueConstraint('predecessor_id', 'successor_id', name='uq_roadmap_dependency'),
    )

    def __repr__(self):
        return f'<RoadmapDependency {self.predecessor_id}->{self.successor_id} lag={self.lag}>'


class RoadmapInitiativeLink(db.Model):
    """Polymorphic link from an initiative to another OpsDeck entity.

    Follows the ActivityRelatedObject pattern. Created in phase 1 because adding it
    later means another migration; the UI that populates it lands in a later phase.
    """
    __tablename__ = 'roadmap_initiative_link'

    id = db.Column(db.Integer, primary_key=True)
    initiative_id = db.Column(
        db.Integer, db.ForeignKey('roadmap_initiative.id', ondelete='CASCADE'),
        nullable=False, index=True)
    related_object_id = db.Column(db.Integer, nullable=False)
    related_object_type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())

    __table_args__ = (
        db.UniqueConstraint('initiative_id', 'related_object_id', 'related_object_type',
                            name='uq_roadmap_initiative_link'),
        # Composite: lookups are always "which initiatives link to <type>:<id>".
        db.Index('ix_roadmap_initiative_link_related',
                 'related_object_type', 'related_object_id'),
    )

    @property
    def related_object(self):
        """Resolves the polymorphic relationship to the related object."""
        from .assets import Asset, Peripheral, Software, License
        from .procurement import Supplier, Subscription, Purchase, Budget
        from .contracts import Contract
        from .services import BusinessService
        from .change import Change
        from .request import Request
        from .security import Risk

        model_map = {
            'Asset': Asset,
            'Peripheral': Peripheral,
            'License': License,
            'Software': Software,
            'Subscription': Subscription,
            'Purchase': Purchase,
            'Budget': Budget,
            'BusinessService': BusinessService,
            'Change': Change,
            'Request': Request,
            'Risk': Risk,
            'Contract': Contract,
            'Supplier': Supplier,
        }

        model = model_map.get(self.related_object_type)
        if model:
            return db.session.get(model, self.related_object_id)
        return None

    def __repr__(self):
        return f'<RoadmapInitiativeLink {self.related_object_type}:{self.related_object_id}>'
