"""
Seeds one disabled API connector task per supported service.
"""
from datetime import timedelta
from .extensions import db
from .utils.timezone_helper import now
from .models.connectors import ConnectorTask, ConnectorSubtask


def seed_all_connectors():
    """
    Seeds the API connector tasks (Google, GitHub, JumpCloud, Atlassian, Microsoft 365, AWS).
    This function is idempotent - it won't create duplicates.
    """
    print("Seeding API connectors...")
    
    # Track what was created
    created_tasks = []
    
    # === GOOGLE WORKSPACE ===
    if not ConnectorTask.query.filter_by(service='google').first():
        google_task = ConnectorTask(
            name="Google Workspace Sync",
            service="google",
            enabled=False,  # Disabled by default - requires credentials
            polling_interval=3600,  # 1 hour
            status="idle",
            next_run=now() + timedelta(hours=1),
            auth_config=None,  # set from Settings > API Connectors
        )
        db.session.add(google_task)
        db.session.flush()
        
        google_subtasks = [
            ConnectorSubtask(
                task_id=google_task.id,
                name="Fetch Users",
                endpoint="/admin/directory/v1/users",
                method="GET",
                pagination_type="nextPageToken",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=google_task.id,
                name="Fetch Groups",
                endpoint="/admin/directory/v1/groups",
                method="GET",
                pagination_type="nextPageToken",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=google_task.id,
                name="Fetch ChromeOS Devices",
                endpoint="/admin/directory/v1/customer/my_customer/devices/chromeos",
                method="GET",
                pagination_type="nextPageToken",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=google_task.id,
                name="Fetch Endpoint Manager Devices",
                endpoint="/v1/customers/my_customer/telemetry/devices",
                method="GET",
                pagination_type="nextPageToken",
                enabled=True
            ),
        ]
        
        for subtask in google_subtasks:
            db.session.add(subtask)
        
        created_tasks.append(f"Google Workspace ({len(google_subtasks)} subtasks)")
    
    # === GITHUB ===
    if not ConnectorTask.query.filter_by(service='github').first():
        github_task = ConnectorTask(
            name="GitHub Organization Sync",
            service="github",
            enabled=False,  # Disabled by default - requires credentials
            polling_interval=3600,  # 1 hour
            status="idle",
            next_run=now() + timedelta(hours=1),
            auth_config=None,  # set from Settings > API Connectors
        )
        db.session.add(github_task)
        db.session.flush()
        
        github_subtasks = [
            ConnectorSubtask(
                task_id=github_task.id,
                name="Fetch Organization Members",
                endpoint="/orgs/YOUR_ORG/members",
                method="GET",
                pagination_type="link_header",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=github_task.id,
                name="Fetch Repositories",
                endpoint="/orgs/YOUR_ORG/repos",
                method="GET",
                pagination_type="link_header",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=github_task.id,
                name="Fetch Outside Collaborators",
                endpoint="/orgs/YOUR_ORG/outside_collaborators",
                method="GET",
                pagination_type="link_header",
                enabled=True
            ),
        ]
        
        for subtask in github_subtasks:
            db.session.add(subtask)
        
        created_tasks.append(f"GitHub ({len(github_subtasks)} subtasks)")
    
    # === JUMPCLOUD ===
    if not ConnectorTask.query.filter_by(service='jumpcloud').first():
        jumpcloud_task = ConnectorTask(
            name="JumpCloud Directory Sync",
            service="jumpcloud",
            enabled=False,  # Disabled by default - requires credentials
            polling_interval=7200,  # 2 hours
            status="idle",
            next_run=now() + timedelta(hours=2),
            auth_config=None,  # set from Settings > API Connectors
        )
        db.session.add(jumpcloud_task)
        db.session.flush()
        
        jumpcloud_subtasks = [
            ConnectorSubtask(
                task_id=jumpcloud_task.id,
                name="Fetch Users",
                endpoint="/api/systemusers",
                method="GET",
                pagination_type="offset",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=jumpcloud_task.id,
                name="Fetch Systems",
                endpoint="/api/systems",
                method="GET",
                pagination_type="offset",
                enabled=True
            ),
        ]
        
        for subtask in jumpcloud_subtasks:
            db.session.add(subtask)
        
        created_tasks.append(f"JumpCloud ({len(jumpcloud_subtasks)} subtasks)")
    
    # === ATLASSIAN ===
    if not ConnectorTask.query.filter_by(service='atlassian').first():
        atlassian_task = ConnectorTask(
            name="Atlassian Cloud Sync",
            service="atlassian",
            enabled=False,  # Disabled by default - requires credentials
            polling_interval=7200,  # 2 hours
            status="idle",
            next_run=now() + timedelta(hours=2),
            auth_config=None,  # set from Settings > API Connectors
        )
        db.session.add(atlassian_task)
        db.session.flush()
        
        atlassian_subtasks = [
            ConnectorSubtask(
                task_id=atlassian_task.id,
                name="Fetch Jira Users",
                endpoint="/rest/api/3/users",
                method="GET",
                pagination_type="offset",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=atlassian_task.id,
                name="Fetch Jira Projects",
                endpoint="/rest/api/3/project/search",
                method="GET",
                pagination_type="offset",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=atlassian_task.id,
                name="Fetch Confluence Spaces",
                endpoint="/wiki/rest/api/space",
                method="GET",
                pagination_type="cursor",
                enabled=True
            ),
        ]
        
        for subtask in atlassian_subtasks:
            db.session.add(subtask)
        
        created_tasks.append(f"Atlassian ({len(atlassian_subtasks)} subtasks)")
    
    # === MICROSOFT 365 ===
    if not ConnectorTask.query.filter_by(service='microsoft').first():
        ms365_task = ConnectorTask(
            name="Microsoft 365 Sync",
            service="microsoft",
            enabled=False,  # Disabled by default - requires credentials
            polling_interval=3600,  # 1 hour
            status="idle",
            next_run=now() + timedelta(hours=1),
            auth_config=None,  # set from Settings > API Connectors
        )
        db.session.add(ms365_task)
        db.session.flush()
        
        ms365_subtasks = [
            ConnectorSubtask(
                task_id=ms365_task.id,
                name="Fetch Users",
                endpoint="/v1.0/users",
                method="GET",
                pagination_type="nextLink",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=ms365_task.id,
                name="Fetch Groups",
                endpoint="/v1.0/groups",
                method="GET",
                pagination_type="nextLink",
                enabled=True
            ),
        ]
        
        for subtask in ms365_subtasks:
            db.session.add(subtask)
        

        created_tasks.append(f"Microsoft 365 ({len(ms365_subtasks)} subtasks)")
    
    # === AWS ===
    if not ConnectorTask.query.filter_by(service='aws').first():
        aws_task = ConnectorTask(
            name="AWS Governance Sync",
            service="aws",
            enabled=False,  # Disabled by default - requires credentials
            polling_interval=3600,  # 1 hour
            status="idle",
            next_run=now() + timedelta(hours=1),
            auth_config=None,  # set from Settings > API Connectors
        )
        db.session.add(aws_task)
        db.session.flush()
        
        aws_subtasks = [
            ConnectorSubtask(
                task_id=aws_task.id,
                name="Fetch IAM Users",
                endpoint="/iam/users",
                method="GET",
                pagination_type="token",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=aws_task.id,
                name="Fetch IAM Roles",
                endpoint="/iam/roles",
                method="GET",
                pagination_type="token",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=aws_task.id,
                name="Fetch S3 Buckets",
                endpoint="/s3/buckets",
                method="GET",
                pagination_type="token",
                enabled=True
            ),
            ConnectorSubtask(
                task_id=aws_task.id,
                name="Fetch Secrets",
                endpoint="/secretsmanager/secrets",
                method="GET",
                pagination_type="token",
                enabled=True
            ),
        ]
        
        for subtask in aws_subtasks:
            db.session.add(subtask)
            
        created_tasks.append(f"AWS Governance ({len(aws_subtasks)} subtasks)")
    
    # Commit all changes
    try:
        db.session.commit()
        
        if created_tasks:
            print(f"✓ Created {len(created_tasks)} connector task(s):")
            for task_info in created_tasks:
                print(f"  - {task_info}")
        else:
            print("✓ All connectors already exist, skipping...")
        
        total_tasks = ConnectorTask.query.count()
        total_subtasks = ConnectorSubtask.query.count()
        print(f"✓ Total: {total_tasks} tasks, {total_subtasks} subtasks")
        
    except Exception as e:
        db.session.rollback()
        print(f"✗ Error seeding connectors: {e}")
        raise


if __name__ == "__main__":
    from src import create_app
    app = create_app()
    with app.app_context():
        seed_all_connectors()
