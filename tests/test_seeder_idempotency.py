"""
The demo seeder must be safe to re-run.

It used to abort outright if any Supplier existed, so demo data for a new module could
not land on an already-seeded database — adding the Roadmaps examples meant editing rows
by hand. Master records are now matched on their natural key and derived ones are
guarded, so a second run adds only what is missing.
"""
from src.extensions import db
from src.models import (Supplier, User, Asset, Peripheral, Subscription, Risk,
                        Documentation, Link, Software, License, BusinessService, Change,
                        Request, SecurityActivity, Roadmap, MaintenanceLog, Group, Budget,
                        Purchase, Tag, Location, Contact, RoadmapGoal, RoadmapInitiative)

TRACKED = (Supplier, User, Asset, Peripheral, Subscription, Risk, Documentation, Link,
           Software, License, BusinessService, Change, Request, SecurityActivity, Roadmap,
           MaintenanceLog, Group, Budget, Purchase, Tag, Location, Contact)


def _seed(app):
    from src.seeder import seed_data
    from src.seeder_prod import seed_production_frameworks, seed_modules

    with app.app_context():
        seed_modules()
        seed_production_frameworks()
    seed_data(app)


def _counts(app):
    with app.app_context():
        return {model.__name__: model.query.count() for model in TRACKED}


def test_the_first_run_produces_data(app, init_database):
    _seed(app)
    counts = _counts(app)
    empty = [name for name, count in counts.items() if count == 0]
    assert empty == []


def test_a_second_run_duplicates_nothing(app, init_database):
    """The property that matters: running it twice leaves the same database."""
    _seed(app)
    before = _counts(app)
    _seed(app)

    assert _counts(app) == before


def test_a_third_run_is_still_stable(app, init_database):
    """Guards against a section that alternates rather than settling."""
    _seed(app)
    _seed(app)
    twice = _counts(app)
    _seed(app)

    assert _counts(app) == twice


def test_a_missing_master_record_is_restored(app, init_database):
    """A deleted supplier comes back, which is what makes topping up possible."""
    _seed(app)
    with app.app_context():
        db.session.delete(Supplier.query.filter_by(name='Figma').one())
        db.session.commit()
        assert Supplier.query.filter_by(name='Figma').first() is None

    _seed(app)

    with app.app_context():
        assert Supplier.query.filter_by(name='Figma').first() is not None


def test_a_new_module_can_be_seeded_into_a_populated_database(app, init_database):
    """The case this was written for: the Roadmaps demo data arriving after the rest.

    Deleting the roadmaps stands in for a database seeded before that section existed.
    """
    _seed(app)
    with app.app_context():
        for roadmap in Roadmap.query.all():
            db.session.delete(roadmap)
        db.session.commit()
        assert Roadmap.query.count() == 0

    _seed(app)

    with app.app_context():
        assert Roadmap.query.count() == 2
        assert RoadmapGoal.query.count() > 0
        assert RoadmapInitiative.query.count() > 0


def test_relationship_links_are_not_duplicated(app, init_database):
    """Association tables have unique pairs, so a re-run would otherwise fail outright."""
    _seed(app)
    with app.app_context():
        engineering = Group.query.filter_by(name='Engineering').one()
        members_before = len(engineering.users)
        activity = SecurityActivity.query.first()
        tags_before = len(activity.tags)

    _seed(app)

    with app.app_context():
        engineering = Group.query.filter_by(name='Engineering').one()
        assert len(engineering.users) == members_before
        assert len(SecurityActivity.query.first().tags) == tags_before
