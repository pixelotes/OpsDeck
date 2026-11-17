"""Seeds one disabled API connector task per supported service.

Credentials are never seeded: each connector is configured from
Settings > API Connectors before it can be enabled or run.
"""
from datetime import timedelta

from .extensions import db
from .models.connectors import ConnectorSubtask, ConnectorTask
from .utils.timezone_helper import now

FETCH_USERS = 'Fetch Users'
FETCH_GROUPS = 'Fetch Groups'
HOUR = 3600

# service: (task name, polling interval in seconds, [(subtask name, endpoint, pagination)])
CONNECTORS = {
    'google': ('Google Workspace Sync', HOUR, [
        (FETCH_USERS, '/admin/directory/v1/users', 'nextPageToken'),
        (FETCH_GROUPS, '/admin/directory/v1/groups', 'nextPageToken'),
        ('Fetch ChromeOS Devices', '/admin/directory/v1/customer/my_customer/devices/chromeos', 'nextPageToken'),
        ('Fetch Endpoint Manager Devices', '/v1/customers/my_customer/telemetry/devices', 'nextPageToken'),
    ]),
    'github': ('GitHub Organization Sync', HOUR, [
        # YOUR_ORG is replaced by the organization entered with the credentials.
        ('Fetch Organization Members', '/orgs/YOUR_ORG/members', 'link_header'),
        ('Fetch Repositories', '/orgs/YOUR_ORG/repos', 'link_header'),
        ('Fetch Outside Collaborators', '/orgs/YOUR_ORG/outside_collaborators', 'link_header'),
    ]),
    'jumpcloud': ('JumpCloud Directory Sync', 2 * HOUR, [
        (FETCH_USERS, '/api/systemusers', 'offset'),
        ('Fetch Systems', '/api/systems', 'offset'),
    ]),
    'atlassian': ('Atlassian Cloud Sync', 2 * HOUR, [
        ('Fetch Jira Users', '/rest/api/3/users', 'offset'),
        ('Fetch Jira Projects', '/rest/api/3/project/search', 'offset'),
        ('Fetch Confluence Spaces', '/wiki/rest/api/space', 'cursor'),
    ]),
    'microsoft': ('Microsoft 365 Sync', HOUR, [
        (FETCH_USERS, '/v1.0/users', 'nextLink'),
        (FETCH_GROUPS, '/v1.0/groups', 'nextLink'),
    ]),
    'aws': ('AWS Governance Sync', HOUR, [
        ('Fetch IAM Users', '/iam/users', 'token'),
        ('Fetch IAM Roles', '/iam/roles', 'token'),
        ('Fetch S3 Buckets', '/s3/buckets', 'token'),
        ('Fetch Secrets', '/secretsmanager/secrets', 'token'),
    ]),
}


def seed_all_connectors():
    """Create the connector tasks that do not exist yet (idempotent, matched by service)."""
    print("Seeding API connectors...")
    created = []
    for service, (name, interval, subtasks) in CONNECTORS.items():
        if ConnectorTask.query.filter_by(service=service).first():
            continue
        task = ConnectorTask(name=name, service=service, enabled=False, polling_interval=interval,
                             status='idle', next_run=now() + timedelta(seconds=interval),
                             auth_config=None)
        task.subtasks = [ConnectorSubtask(name=sub_name, endpoint=endpoint, method='GET',
                                          pagination_type=pagination, enabled=True)
                         for sub_name, endpoint, pagination in subtasks]
        db.session.add(task)
        created.append(f"{name} ({len(subtasks)} subtasks)")

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"✗ Error seeding connectors: {e}")
        raise

    if created:
        print(f"✓ Created {len(created)} connector task(s):")
        for line in created:
            print(f"  - {line}")
    else:
        print("✓ All connectors already exist, skipping...")
    print(f"✓ Total: {ConnectorTask.query.count()} tasks, {ConnectorSubtask.query.count()} subtasks")
