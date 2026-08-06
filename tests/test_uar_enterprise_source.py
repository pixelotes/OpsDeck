"""The 'Enterprise Report' UAR source must call the engine correctly.

This source never ran. _load_dataset looked the Report up itself and then called
``engine.load_from_report(report)``, while the signature is
``load_from_report(table_name, report_id)`` — one argument short, with a Report object
where a table name belongs. Any attempt to use it raised TypeError immediately.

It survived because the opsdeck_enterprise plugin is not installed here, so the branch
died earlier on the import and nothing reached the call. These tests therefore stub the
engine method rather than the plugin: that is enough to pin the calling convention and
the return value, which is where the bugs were, and it does not pretend to exercise the
real report loading — that still needs an environment with the plugin.
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
            engine, 'dataset_a', 'Enterprise Report', {'report_id': 7}
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
            engine, 'dataset_b', 'Enterprise Report', {'report_id': 7}
        )

    assert data == engine.rows
    assert UARAutomationService()._create_snapshot(data, 'Dataset B')['row_count'] == 2


def test_a_missing_report_id_is_refused_before_the_engine_is_touched(app, init_database):
    engine = _RecordingEngine()

    with app.app_context():
        with pytest.raises(ValueError, match='report_id is required'):
            UARAutomationService()._load_dataset(
                engine, 'dataset_a', 'Enterprise Report', {}
            )

    assert engine.calls == []


def test_a_missing_plugin_is_reported_as_a_configuration_error(app, init_database):
    """Without opsdeck_enterprise the engine raises ImportError; callers see a message."""
    class _NoPluginEngine(AccessReviewEngine):
        def load_from_report(self, table_name, report_id):
            raise ImportError('No module named opsdeck_enterprise')

    with app.app_context():
        with pytest.raises(ValueError, match='Enterprise plugin not available'):
            UARAutomationService()._load_dataset(
                _NoPluginEngine(), 'dataset_a', 'Enterprise Report', {'report_id': 7}
            )
