"""Runs API connector tasks and stores what they fetch.

A run walks a task's enabled subtasks, fetches every page of each endpoint through the
service's connector, saves the result as a ConnectorReport and diffs it against the
previous report of the same subtask. poll_due_tasks is the scheduler entry point.
"""
import json
import logging
from datetime import timedelta

from ..extensions import db
from ..models.connectors import ConnectorTask, ConnectorReport
from ..utils.differ import get_semantic_diff
from ..utils.timezone_helper import now

logger = logging.getLogger(__name__)

POLL_INTERVAL_MINUTES = 5
MIN_POLLING_INTERVAL = 300       # 5 minutes
MAX_POLLING_INTERVAL = 604800    # 7 days


def get_connector_class(service):
    """Connector class for a service key, or None when the service is unknown."""
    from ..connectors import (
        AtlassianConnector, AWSConnector, GitHubConnector, GoogleConnector,
        JumpCloudConnector, MicrosoftConnector,
    )
    return {
        'google': GoogleConnector,
        'microsoft': MicrosoftConnector,
        'atlassian': AtlassianConnector,
        'github': GitHubConnector,
        'jumpcloud': JumpCloudConnector,
        'aws': AWSConnector,
    }.get(service)


def _has_changes(diff):
    return bool(diff.get('added') or diff.get('removed') or diff.get('changed'))


def execute_subtask(task, subtask):
    """Fetch one endpoint, store the report and compare it with the previous one."""
    connector_class = get_connector_class(task.service)
    if not connector_class:
        raise ValueError(f"No connector found for service: {task.service}")

    connector = connector_class(task, subtask)
    data = connector.fetch_all_pages()
    new_report = connector.save_report(data)

    previous = (ConnectorReport.query
                .filter_by(subtask_id=subtask.id)
                .filter(ConnectorReport.id != new_report.id)
                .order_by(ConnectorReport.created_at.desc())
                .first())

    diff = None
    if previous:
        diff = get_semantic_diff(json.loads(previous.data), json.loads(new_report.data))

    return {
        'subtask_id': subtask.id,
        'subtask_name': subtask.name,
        'report_id': new_report.id,
        'record_count': new_report.record_count,
        'has_changes': _has_changes(diff) if diff else False,
        'diff_summary': str(diff)[:200] if diff else None,
    }


def execute_task(task):
    """Run every enabled subtask of a task; one failing subtask does not stop the rest."""
    logger.info("[Connectors] Running task %s (%s)", task.name, task.id)
    task.status = 'running'
    task.last_run = now()
    db.session.commit()

    results, errors = [], []
    try:
        for subtask in task.subtasks:
            if not subtask.enabled:
                continue
            try:
                results.append(execute_subtask(task, subtask))
            except Exception as e:
                db.session.rollback()
                logger.exception("[Connectors] Subtask %s failed", subtask.name)
                errors.append({'subtask_id': subtask.id, 'subtask_name': subtask.name,
                               'error': str(e)})

        task.status = 'error' if errors else 'idle'
        task.next_run = now() + timedelta(seconds=task.polling_interval or 3600)
        db.session.commit()
    except Exception:
        db.session.rollback()
        task.status = 'error'
        db.session.commit()
        raise

    return {
        'task_id': task.id,
        'task_name': task.name,
        'success': not errors,
        'results': results,
        'errors': errors,
    }


def poll_due_tasks(app):
    """Scheduler job: run every enabled task whose next_run has passed."""
    with app.app_context():
        due = (ConnectorTask.query
               .filter_by(enabled=True)
               .filter((ConnectorTask.next_run.is_(None)) | (ConnectorTask.next_run <= now()))
               .all())
        for task in due:
            try:
                result = execute_task(task)
                if result['success']:
                    changed = sum(1 for r in result['results'] if r.get('has_changes'))
                    app.logger.info(f"Connector task '{task.name}': {len(result['results'])} subtasks, "
                                    f"{changed} with changes")
                else:
                    app.logger.warning(f"Connector task '{task.name}' finished with "
                                       f"{len(result['errors'])} errors")
            except Exception as e:
                app.logger.error(f"Connector task '{task.name}' failed: {e}")
