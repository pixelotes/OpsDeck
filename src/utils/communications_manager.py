"""
Communications Manager Utility

Functions for generating and managing scheduled communications
based on pack communication rules.
"""
from datetime import timedelta
from ..extensions import db
from ..models.communications import ScheduledCommunication
from ..models.onboarding import OnboardingProcess, OffboardingProcess


def trigger_workflow_communications(process, pack):
    """
    Generate ScheduledCommunication records from PackCommunication rules.
    
    Args:
        process: OnboardingProcess or OffboardingProcess instance
        pack: OnboardingPack instance with communications
    
    Returns:
        int: Number of communications scheduled
    """
    if not pack or not pack.communications:
        return 0
    
    # Determine target type and key date based on process type
    if isinstance(process, OnboardingProcess):
        target_type = 'onboarding'
        key_date = process.start_date
    elif isinstance(process, OffboardingProcess):
        target_type = 'offboarding'
        key_date = process.departure_date
    else:
        return 0
    
    scheduled_count = 0
    
    for pack_comm in pack.communications:
        if not pack_comm.is_active or not pack_comm.template.is_active:
            continue
        
        # Calculate scheduled date
        scheduled_date = key_date + timedelta(days=pack_comm.offset_days)
        
        # Resolve recipient email
        recipient_email, recipient_name = resolve_recipient_email(process, pack_comm.recipient_type)
        
        if not recipient_email:
            # Skip if we can't determine recipient
            continue
        
        # Create the scheduled communication
        scheduled_comm = ScheduledCommunication(
            template_id=pack_comm.template_id,
            scheduled_date=scheduled_date,
            target_type=target_type,
            target_id=process.id,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            recipient_type=pack_comm.recipient_type
        )
        
        db.session.add(scheduled_comm)
        scheduled_count += 1
    
    return scheduled_count


def resolve_recipient_email(process, recipient_type):
    """
    Get email and name based on recipient_type for given process.
    
    Args:
        process: OnboardingProcess or OffboardingProcess instance
        recipient_type: String - 'target_user', 'manager', 'buddy', 'personal_email'
    
    Returns:
        tuple: (email, name) or (None, None) if not resolvable
    """
    if isinstance(process, OnboardingProcess):
        if recipient_type == 'target_user':
            # For onboarding, the user might not exist yet
            if process.user:
                return process.user.email, process.user.name
            elif process.target_email:
                return process.target_email, process.new_hire_name
            elif process.personal_email:
                 # Fallback to personal email if no corporate email yet
                return process.personal_email, process.new_hire_name
            else:
                # Cannot determine email yet
                return None, process.new_hire_name
        elif recipient_type == 'manager':
            if process.assigned_manager:
                return process.assigned_manager.email, process.assigned_manager.name
        elif recipient_type == 'buddy':
            if process.assigned_buddy:
                return process.assigned_buddy.email, process.assigned_buddy.name
        elif recipient_type == 'personal_email':
             if process.personal_email:
                 return process.personal_email, process.new_hire_name
                
    elif isinstance(process, OffboardingProcess):
        if recipient_type == 'target_user':
            if process.user:
                return process.user.email, process.user.name
        elif recipient_type == 'manager':
            if process.manager:
                return process.manager.email, process.manager.name
        elif recipient_type == 'personal_email':
             if process.user and process.user.personal_email:
                 return process.user.personal_email, process.user.name
        # Offboarding doesn't typically have a buddy reference
    
    return None, None


def cancel_workflow_communications(target_type, target_id):
    """
    Cancel all pending communications for a process.
    Useful when a process is cancelled or deleted.
    
    Args:
        target_type: 'onboarding' or 'offboarding'
        target_id: Process ID
    
    Returns:
        int: Number of communications cancelled
    """
    pending_comms = ScheduledCommunication.query.filter_by(
        target_type=target_type,
        target_id=target_id,
        status='pending'
    ).all()
    
    for comm in pending_comms:
        comm.status = 'cancelled'
    
    return len(pending_comms)


def get_process_communications(target_type, target_id):
    """
    Get all scheduled communications for a process.
    
    Args:
        target_type: 'onboarding' or 'offboarding'
        target_id: Process ID
    
    Returns:
        list: ScheduledCommunication objects ordered by scheduled_date
    """
    return ScheduledCommunication.query.filter_by(
        target_type=target_type,
        target_id=target_id
    ).order_by(ScheduledCommunication.scheduled_date).all()
