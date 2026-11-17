"""The 'Connector Report' UAR source must call the engine correctly.

This source never ran. _load_dataset looked the Report up itself and then called
``engine.load_from_report(report)``, while the signature is
``load_from_report(table_name, report_id)`` — one argument short, with a Report object
where a table name belongs. Any attempt to use it raised TypeError immediately.

The engine method is stubbed in the first tests to pin the calling convention and the
return value, which is where the bugs were; the last ones exercise the real loader now
that connector reports live in core instead of the opsdeck-enterprise plugin.
"""
import pytest

from src.services.uar_service import UARAutomationService
from src.utils.uar_engine import AccessReviewEngine


class _RecordingEngine(AccessReviewEngine):
    """An engine that records how load_from_report was called."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self.rows = [{'email': 'a@test.com'}, {'email': 'b@test.com'}]

    def load_from_report(self, table_name, report_id):
        self.calls.append((table_name, report_id))
        return self.rows


def test_the_engine_is_called_with_a_table_name_and_a_report_id(app, init_database):
    """The regression: positional arguments, in the right order, both present."""
    engine = _RecordingEngine()

    with app.app_context():
        UARAutomationService()._load_dataset(
            engine, 'dataset_a', 'Connector Report', {'report_id': 7}
        )

    assert engine.calls == [('dataset_a', 7)]


def test_the_rows_are_returned_so_the_snapshot_can_count_them(app, init_database):
    """The second defect: the branch returned [] and the execution recorded 0 rows.

    _load_dataset's return value feeds _create_snapshot, which is where row_count comes
    from, so returning nothing would have reported an empty dataset that had actually
    been loaded — a silent wrong number instead of a loud crash.
    """
    engine = _RecordingEngine()

    with app.app_context():
        data = UARAutomationService()._load_dataset(
            engine, 'dataset_b', 'Connector Report', {'report_id': 7}
        )

    assert data == engine.rows
    assert UARAutomationService()._create_snapshot(data, 'Dataset B')['row_count'] == 2


def test_a_missing_report_id_is_refused_before_the_engine_is_touched(app, init_database):
    engine = _RecordingEngine()

    with app.app_context():
        with pytest.raises(ValueError, match='report_id is required'):
            UARAutomationService()._load_dataset(
                engine, 'dataset_a', 'Connector Report', {}
            )

    assert engine.calls == []


def test_a_connector_report_is_loaded_into_the_engine(app, init_database):
    """With connectors in core the real loader runs: the report's items become rows."""
    import json
    from src import db
    from src.models.connectors import ConnectorTask, ConnectorSubtask, ConnectorReport

    with app.app_context():
        task = ConnectorTask(name='GitHub', service='github')
        subtask = ConnectorSubtask(task=task, name='Members', endpoint='/orgs/x/members')
        report = ConnectorReport(subtask=subtask, record_count=2, data=json.dumps(
            {'items': [{'email': 'a@test.com'}, {'email': 'b@test.com'}], 'total_count': 2}))
        db.session.add_all([task, subtask, report])
        db.session.commit()

        engine = AccessReviewEngine()
        data = UARAutomationService()._load_dataset(
            engine, 'dataset_a', 'Connector Report', {'report_id': report.id})

    assert [row['email'] for row in data] == ['a@test.com', 'b@test.com']


def test_a_missing_report_is_refused(app, init_database):
    with app.app_context():
        with pytest.raises(ValueError, match='not found'):
            UARAutomationService()._load_dataset(
                AccessReviewEngine(), 'dataset_a', 'Connector Report', {'report_id': 999})
