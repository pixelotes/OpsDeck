import logging
from flask import current_app, request, has_request_context

def log_audit(event_type, action, target_object=None, outcome='success', **kwargs):
    """
    Write a structured audit log entry in ECS format.
    
    Args:
        event_type (str): Event category, e.g. 'user.created' or 'security.login'.
        action (str): The specific action, e.g. 'create', 'update' or 'delete'.
        target_object (str, optional): Identificador del objeto afectado (ej: 'User:123').
        outcome (str): Result of the action, 'success' or 'failure'.
        **kwargs: Arbitrary extra fields, merged into the JSON object.
    """
    if not current_app:
        return

    # Base context
    extra = {
        "event.dataset": "renewal_guard.audit",
        "event.kind": "event",
        "event.category": event_type.split('.')[0] if '.' in event_type else "web",
        "event.action": action,
        "event.outcome": outcome
    }
    
    # Add target info if present
    if target_object:
        extra["related.resource"] = target_object

    # Add Request Context (User, IP, URL)
    if has_request_context():
        # Source IP
        extra["source.ip"] = request.remote_addr
        extra["url.path"] = request.path
        extra["http.request.method"] = request.method
        extra["user_agent.original"] = request.user_agent.string
        
        # User Context (try to get from Flask-Login's current_user via template context or session)
        # Note: 'current_user' is usually available in the request context if Flask-Login is set up.
        # However, accessing it directly requires importing it from flask_login, 
        # but to avoid circular imports or issues if not present, we can check extensions or kwargs.
        
        # Common pattern: try to import current_user
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                extra["user.email"] = current_user.email
                extra["user.id"] = str(current_user.id)
                # Add role if available
                if hasattr(current_user, 'role'):
                    extra["user.roles"] = [current_user.role]
        except ImportError:
            pass
            
    # Merge custom kwargs
    extra.update(kwargs)
    
    # Choose level based on outcome or importance
    level = logging.INFO
    if outcome == 'failure':
        level = logging.WARNING
    
    # Log it
    current_app.logger.log(level, f"{event_type}: {action}", extra=extra)
