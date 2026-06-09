from ..services.permissions_service import requires_permission, has_write_permission
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
from ..extensions import db
from ..models import User, Peripheral, License, Software, Course
from ..models import Subscription, PaymentMethod, Risk, BusinessService, Location
from ..models.procurement import log_subscription_cost_change
# Importamos los modelos nuevos (asegúrate de haberlos registrado en __init__.py primero)
from ..models.onboarding import (
    OnboardingProcess, OffboardingProcess, ProcessItem, 
    OnboardingPack, PackItem, ProcessTemplate
)
from ..models.communications import EmailTemplate, PackCommunication, ScheduledCommunication
from ..utils.helpers import generate_secure_password
from ..utils.communications_manager import trigger_workflow_communications, get_process_communications
from .main import login_required
from src.utils.timezone_helper import now, today


onboarding_bp = Blueprint('onboarding', __name__)

_EP_INDEX = 'onboarding.index'
_EP_ONBOARDING = 'onboarding.onboarding_detail'
_EP_OFFBOARDING = 'onboarding.offboarding_detail'

# --- DASHBOARD PRINCIPAL ---

@onboarding_bp.route('/', methods=['GET'])
@login_required
@requires_permission('hr_people')
def index():
    """Panel principal de HR Processes."""
    active_onboardings = OnboardingProcess.query.filter(OnboardingProcess.status != 'Completed').all()
    active_offboardings = OffboardingProcess.query.filter(OffboardingProcess.status != 'Completed').all()
    packs = OnboardingPack.query.filter_by(is_active=True).all()
    
    return render_template('onboarding/dashboard.html', 
                           onboardings=active_onboardings,
                           offboardings=active_offboardings,
                           packs=packs)

# ==========================================
# GESTIÓN DE PACKS (ONBOARDING)
# ==========================================

@onboarding_bp.route('/packs/new', methods=['POST'])
@login_required
@requires_permission('hr_people')
def new_pack():
    if not has_write_permission('hr_people'):
        flash('Write access required to create packs.', 'danger')
        return redirect(url_for(_EP_INDEX))
    name = request.form.get('name')
    if name:
        pack = OnboardingPack(name=name, description=request.form.get('description'))
        db.session.add(pack)
        db.session.commit()
        flash(f'Pack "{name}" created.', 'success')
    return redirect(url_for(_EP_INDEX))

@onboarding_bp.route('/packs', methods=['GET'])
@login_required
@requires_permission('hr_people')
def list_packs():
    """Vista dedicada para gestionar packs."""
    packs = OnboardingPack.query.filter_by(is_active=True).all()
    return render_template('onboarding/packs_list.html', packs=packs)

@onboarding_bp.route('/api/packs', methods=['GET'])
@login_required
@requires_permission('hr_people')
def packs_api():
    """API to get active packs for dropdowns."""
    packs = OnboardingPack.query.filter_by(is_active=True).all()
    return jsonify([{'id': p.id, 'name': p.name} for p in packs])

@onboarding_bp.route('/api/users', methods=['GET'])
@login_required
@requires_permission('hr_people')
def users_api():
    """API to get active users for dropdowns."""
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    # Return simple JSON
    return jsonify([{'id': u.id, 'name': u.name, 'email': u.email} for u in users])

@onboarding_bp.route('/packs/<int:id>', methods=['GET', 'POST'])
@login_required
@requires_permission('hr_people')
def pack_detail(id):
    pack = db.get_or_404(OnboardingPack, id)
    
    # Añadir item al pack
    if request.method == 'POST':
        if not has_write_permission('hr_people'):
            flash('Write access required to update packs.', 'danger')
            return redirect(url_for('onboarding.pack_detail', id=id))
        item_type = request.form.get('item_type') # 'Software', 'Hardware', 'Task', 'ServiceAccess', 'Course'
        description = request.form.get('description')
        software_id = request.form.get('software_id') or None
        service_id = request.form.get('service_id') or None
        subscription_id = request.form.get('subscription_id') or None
        course_id = request.form.get('course_id') or None
        
        # Si es software, hacemos la descripción más bonita automáticamente
        if item_type == 'Software' and software_id:
            soft = db.session.get(Software,software_id)
            if not description:
                description = f"Provisionar acceso a: {soft.name}"
        elif item_type == 'ServiceAccess' and service_id:
            srv = db.session.get(BusinessService,service_id)
            if not description:
                description = f"Grant user access to {srv.category}: {srv.name}"
        elif item_type == 'Subscription' and subscription_id:
            sub = db.session.get(Subscription,subscription_id)
            if not description:
                description = f"Assign user to subscription: {sub.name}"
        elif item_type == 'Course' and course_id:
            course = db.session.get(Course,course_id)
            if not description:
                description = f"Assign user to course: {course.title}"
        
        item = PackItem(
            pack_id=pack.id, 
            item_type=item_type, 
            description=description, 
            software_id=software_id,
            service_id=service_id,
            subscription_id=subscription_id,
            course_id=course_id
        )
        db.session.add(item)
        db.session.commit()
        flash('Item added to pack.', 'success')
        return redirect(url_for('onboarding.pack_detail', id=id))

    all_software = Software.query.order_by(Software.name).all()
    all_services = BusinessService.query.order_by(BusinessService.name).all()
    all_subscriptions = Subscription.query.filter_by(is_archived=False).order_by(Subscription.name).all()
    all_courses = Course.query.order_by(Course.title).all()
    email_templates = EmailTemplate.query.filter_by(is_active=True).order_by(EmailTemplate.name).all()
    return render_template('onboarding/pack_detail.html', pack=pack, all_software=all_software, all_services=all_services, all_subscriptions=all_subscriptions, all_courses=all_courses, email_templates=email_templates)


@onboarding_bp.route('/packs/<int:pack_id>/communications/add', methods=['POST'])
@login_required
@requires_permission('hr_people')
def add_pack_communication(pack_id):
    if not has_write_permission('hr_people'):
        flash('Write access required to add communications.', 'danger')
        return redirect(url_for('onboarding.pack_detail', id=pack_id))
    """Add a communication rule to a pack."""
    pack = db.get_or_404(OnboardingPack, pack_id)
    
    template_id = request.form.get('template_id')
    offset_days = request.form.get('offset_days', 0)
    recipient_type = request.form.get('recipient_type', 'target_user')
    
    if not template_id:
        flash('Please select an email template.', 'danger')
        return redirect(url_for('onboarding.pack_detail', id=pack_id))
    
    comm = PackCommunication(
        pack_id=pack_id,
        template_id=int(template_id),
        offset_days=int(offset_days),
        recipient_type=recipient_type
    )
    db.session.add(comm)
    db.session.commit()
    
    flash('Email rule added to pack.', 'success')
    return redirect(url_for('onboarding.pack_detail', id=pack_id))


@onboarding_bp.route('/packs/<int:pack_id>/communications/<int:comm_id>/delete', methods=['POST'])
@login_required
@requires_permission('hr_people')
def delete_pack_communication(pack_id, comm_id):
    if not has_write_permission('hr_people'):
        flash('Write access required to delete communications.', 'danger')
        return redirect(url_for('onboarding.pack_detail', id=pack_id))
    """Delete a communication rule from a pack."""
    comm = db.get_or_404(PackCommunication, comm_id)
    
    if comm.pack_id != pack_id:
        flash('Invalid communication for this pack.', 'danger')
        return redirect(url_for('onboarding.pack_detail', id=pack_id))
    
    db.session.delete(comm)
    db.session.commit()
    
    flash('Email rule removed.', 'success')
    return redirect(url_for('onboarding.pack_detail', id=pack_id))


# ==========================================
# PROCESO DE ONBOARDING (ENTRADA)
# ==========================================

@onboarding_bp.route('/new', methods=['GET', 'POST'])
@login_required
@requires_permission('hr_people')
def new_onboarding():
    if request.method == 'POST':
        if not has_write_permission('hr_people'):
            flash('Write access required to start onboarding.', 'danger')
            return redirect(url_for(_EP_INDEX))
        new_hire_name = request.form['new_hire_name']
        target_email = request.form.get('target_email')
        personal_email = request.form.get('personal_email')
        pack_id = request.form.get('pack_id')
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        
        manager_id = request.form.get('manager_id')
        buddy_id = request.form.get('buddy_id')

        # 1. Crear Proceso
        process = OnboardingProcess(
            new_hire_name=new_hire_name,
            target_email=target_email,
            personal_email=personal_email,
            pack_id=pack_id,
            start_date=start_date,
            assigned_manager_id=int(manager_id) if manager_id else None,
            assigned_buddy_id=int(buddy_id) if buddy_id else None
        )
        db.session.add(process)
        db.session.commit()
        
        
        # 0. Generar Checklist: Crear Usuario (SIEMPRE PRIMERO)
        db.session.add(ProcessItem(
            onboarding_process_id=process.id,
            description="👤 Create user account (Automated)",
            item_type='CreateUser'
        ))

        # 2. Generar Checklist: Tareas Globales
        global_tasks = ProcessTemplate.query.filter_by(process_type='onboarding', is_active=True).all()
        for task in global_tasks:
            db.session.add(ProcessItem(
                onboarding_process_id=process.id,
                description=task.name,
                item_type='StaticTask'
            ))
            
        # 3. Generar Checklist: Items del Pack & Provisioning
        if pack_id:
            pack = db.session.get(OnboardingPack,pack_id)
            for p_item in pack.items:
                # Handle Service Access Provisioning
                linked_obj_id = None
                if p_item.item_type == 'ServiceAccess' and p_item.service_id:
                    linked_obj_id = p_item.service_id
                    # Note: We cannot assign to service.users here because the User record 
                    # for the new hire likely does not exist yet. 
                    # The checklist item "Provision account..." serves as the action trigger.
                elif p_item.item_type == 'Software' and p_item.software_id:
                    linked_obj_id = p_item.software_id
                elif p_item.item_type == 'Subscription' and p_item.subscription_id:
                    linked_obj_id = p_item.subscription_id
                elif p_item.item_type == 'Course' and p_item.course_id:
                    linked_obj_id = p_item.course_id

                db.session.add(ProcessItem(
                    onboarding_process_id=process.id,
                    description=p_item.description,
                    item_type=p_item.item_type,
                    linked_object_id=linked_obj_id
                ))

        # 4. Social logic (Updated)
        if process.assigned_manager_id:
            manager = db.session.get(User,process.assigned_manager_id)
            if manager:
                db.session.add(ProcessItem(
                    onboarding_process_id=process.id,
                    description=f"📅 Schedule 1:1 meeting with {manager.name} (Manager)",
                    item_type='SocialTask',
                    linked_object_id=manager.id
                ))

        if process.assigned_buddy_id:
            buddy = db.session.get(User,process.assigned_buddy_id)
            if buddy:
                db.session.add(ProcessItem(
                    onboarding_process_id=process.id,
                    description=f"☕ Schedule welcome coffee with buddy: {buddy.name}",
                    item_type='SocialTask',
                    linked_object_id=buddy.id
                ))
        
        db.session.commit()
        
        # Trigger scheduled communications from pack
        if pack_id:
            pack = db.session.get(OnboardingPack,pack_id)
            if pack:
                comm_count = trigger_workflow_communications(process, pack)
                if comm_count > 0:
                    flash(f'{comm_count} emails scheduled based on pack communications.', 'info')
        
        flash(f'Onboarding started for {new_hire_name}.', 'success')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))

    packs = OnboardingPack.query.filter_by(is_active=True).all()
    users = User.query.filter_by(is_archived=False).all() # Para asignar usuario si ya existe
    return render_template('onboarding/form_onboarding.html', packs=packs, users=users)

@onboarding_bp.route('/view/<int:id>', methods=['GET'])
@login_required
@requires_permission('hr_people')
def onboarding_detail(id):
    process = db.get_or_404(OnboardingProcess, id)
    communications = get_process_communications('onboarding', id)
    users = User.query.filter_by(is_archived=False).order_by(User.name).all() # For edit modal
    return render_template('onboarding/process_detail.html', process=process, type='onboarding', communications=communications, users=users)

@onboarding_bp.route('/process/<int:id>/update_details', methods=['POST'])
@login_required
@requires_permission('hr_people')
def update_process_details(id):
    if not has_write_permission('hr_people'):
        flash('Write access required to update process details.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=id))
    process = db.get_or_404(OnboardingProcess, id)
    
    process.target_email = request.form.get('target_email')
    process.personal_email = request.form.get('personal_email')
    process.notes = request.form.get('notes') or None

    start_date_str = request.form.get('start_date')
    if start_date_str:
        process.start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()

    manager_id = request.form.get('manager_id')
    buddy_id = request.form.get('buddy_id')

    process.assigned_manager_id = int(manager_id) if manager_id else None
    process.assigned_buddy_id = int(buddy_id) if buddy_id else None

    db.session.commit()
    flash('Process details updated.', 'success')
    return redirect(url_for(_EP_ONBOARDING, id=process.id))

@onboarding_bp.route('/offboarding/<int:id>/update_details', methods=['POST'])
@login_required
@requires_permission('hr_people')
def update_offboarding_details(id):
    if not has_write_permission('hr_people'):
        flash('Write access required to update process details.', 'danger')
        return redirect(url_for(_EP_OFFBOARDING, id=id))
    process = db.get_or_404(OffboardingProcess, id)

    departure_date_str = request.form.get('departure_date')
    if departure_date_str:
        process.departure_date = datetime.strptime(departure_date_str, '%Y-%m-%d').date()

    manager_id = request.form.get('manager_id')
    process.manager_id = int(manager_id) if manager_id else None
    process.notes = request.form.get('notes') or None

    db.session.commit()
    flash('Offboarding details updated.', 'success')
    return redirect(url_for(_EP_OFFBOARDING, id=process.id))

# ==========================================
# PROCESO DE OFFBOARDING (SALIDA)
# ==========================================

@onboarding_bp.route('/offboarding/new', methods=['GET', 'POST'])
@login_required
@requires_permission('hr_people')
def new_offboarding():
    if request.method == 'POST':
        if not has_write_permission('hr_people'):
            flash('Write access required to start offboarding.', 'danger')
            return redirect(url_for(_EP_INDEX))
        user_id = request.form['user_id']
        departure_date = datetime.strptime(request.form['departure_date'], '%Y-%m-%d').date()
        target_user = db.get_or_404(User, user_id)

        manager_id = session.get('user_id')
        transfer_to_id = request.form.get('transfer_to_id') or None
        if transfer_to_id:
            transfer_to_id = int(transfer_to_id)

        process = OffboardingProcess(
            user_id=user_id,
            manager_id=manager_id,
            departure_date=departure_date
        )
        db.session.add(process)
        db.session.commit()
        
        # 1. HARDWARE
        for assignment in target_user.assignments:
            if not assignment.checked_in_date:
                db.session.add(ProcessItem(
                    offboarding_process_id=process.id,
                    description=f"💻 Pick up Asset: {assignment.asset.name} ({assignment.asset.serial_number})",
                    item_type='Asset',
                    linked_object_id=assignment.asset.id
                ))

        peripherals = Peripheral.query.filter_by(user_id=target_user.id).all()
        for p in peripherals:
            db.session.add(ProcessItem(
                offboarding_process_id=process.id,
                description=f"⌨️ Pick up Peripheral: {p.name}",
                item_type='Peripheral',
                linked_object_id=p.id
            ))
            
        # 2. SOFTWARE
        licenses = License.query.filter_by(user_id=target_user.id).all()
        for l in licenses:
            desc = f"🔑 Revoke License: {l.name}"
            if l.software:
                desc += f" ({l.software.name})"
            db.session.add(ProcessItem(
                offboarding_process_id=process.id,
                description=desc,
                item_type='License',
                linked_object_id=l.id
            ))
            
        subscriptions = Subscription.query.filter_by(user_id=target_user.id).all()
        for sub in subscriptions:
            db.session.add(ProcessItem(
                offboarding_process_id=process.id,
                description=f"🔄 Cancel/Transfer Subscription: {sub.name}",
                item_type='Subscription'
            ))

        # 2b. Subscription Access (Revoke)
        subscriptions_access = Subscription.query.filter(Subscription.users.contains(target_user)).all()
        for sub in subscriptions_access:
             db.session.add(ProcessItem(
                offboarding_process_id=process.id,
                description=f"🛑 Revoke access to Subscription: {sub.name}",
                item_type='RevokeSubscriptionAccess',
                linked_object_id=sub.id
            ))

        # 3. COMPLIANCE & OWNERSHIP
        payment_methods = PaymentMethod.query.filter_by(user_id=target_user.id).all()
        for pm in payment_methods:
            linked_subs = len(pm.subscriptions)
            desc = f"⚠️ BLOCKING: Card '{pm.name}' has {linked_subs} subscriptions. Change before canceling." if linked_subs > 0 else f"💳 Recover/Cancel Payment Method: {pm.name}"
            db.session.add(ProcessItem(
                offboarding_process_id=process.id,
                description=desc,
                item_type='PaymentMethod',
                linked_object_id=pm.id
            ))

        # RISKS
        risks = Risk.query.filter_by(owner_id=target_user.id).all()
        for r in risks:
            short_desc = (r.risk_description[:75] + '..') if len(r.risk_description) > 75 else r.risk_description
            item = ProcessItem(
                offboarding_process_id=process.id,
                description=f"⚠️ TRANSFER RISK: {short_desc}",
                item_type='Risk',
                linked_object_id=r.id
            )
            if transfer_to_id:
                r.owner_id = transfer_to_id
                item.is_completed = True
            db.session.add(item)

        # SERVICE OWNERSHIP
        services_owned = BusinessService.query.filter_by(owner_id=target_user.id).all()
        for s in services_owned:
            item = ProcessItem(
                offboarding_process_id=process.id,
                description=f"⚠️ TRANSFER SERVICE: {s.name} (User is Owner)",
                item_type='ServiceOwnership',
                linked_object_id=s.id
            )
            if transfer_to_id:
                s.owner_id = transfer_to_id
                item.is_completed = True
            db.session.add(item)
            
        # 2. Revoke Access to Services/Applications
        # Find all services where the user is in the 'users' list
        services_access = BusinessService.query.filter(BusinessService.users.contains(target_user)).all()
        for s in services_access:
            cat_label = s.category if s.category else 'Service'
            db.session.add(ProcessItem(
                offboarding_process_id=process.id,
                description=f"🛑 Revoke access to {cat_label}: {s.name}",
                item_type='RevokeAccess',
                linked_object_id=s.id
            ))

        # CREDENTIALS
        from ..models.credentials import Credential
        credentials_owned = Credential.query.filter_by(owner_id=target_user.id, owner_type='User').all()
        for cred in credentials_owned:
            item = ProcessItem(
                offboarding_process_id=process.id,
                description=f"🔑 REASSIGN CREDENTIAL: {cred.name} ({cred.type})",
                item_type='Credential',
                linked_object_id=cred.id
            )
            if transfer_to_id:
                cred.owner_id = transfer_to_id
                item.is_completed = True
            db.session.add(item)

        # 4. TAREAS GLOBALES
        static_tasks = ProcessTemplate.query.filter_by(process_type='offboarding', is_active=True).all()
        for task in static_tasks:
            db.session.add(ProcessItem(
                offboarding_process_id=process.id,
                description=task.name,
                item_type='StaticTask'
            ))

        transfer_to_user = db.session.get(User, transfer_to_id) if transfer_to_id else None
        db.session.commit()
        if transfer_to_user:
            flash(f'Offboarding started for {target_user.name}. Ownership of risks, services and credentials auto-transferred to {transfer_to_user.name}.', 'warning')
        else:
            flash(f'Offboarding started for {target_user.name}. Checklist created.', 'warning')
        return redirect(url_for(_EP_OFFBOARDING, id=process.id))

    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    return render_template('onboarding/form_offboarding.html', users=users)

@onboarding_bp.route('/offboarding/view/<int:id>', methods=['GET'])
@login_required
@requires_permission('hr_people')
def offboarding_detail(id):
    process = db.get_or_404(OffboardingProcess, id)
    users = User.query.filter_by(is_archived=False).order_by(User.name).all()
    
    # Pre-fetch payment methods for the template
    pm_ids = [item.linked_object_id for item in process.items if item.item_type == 'PaymentMethod' and item.linked_object_id]
    payment_methods = {}
    if pm_ids:
        pms = PaymentMethod.query.filter(PaymentMethod.id.in_(pm_ids)).all()
        payment_methods = {pm.id: pm for pm in pms}
    
    # Get scheduled communications
    # Get scheduled communications
    communications = get_process_communications('offboarding', id)
    
    # Get locations for asset return
    locations = Location.query.filter_by(is_archived=False).order_by(Location.name).all()
        
    return render_template('onboarding/process_detail.html', process=process, type='offboarding', users=users, payment_methods=payment_methods, communications=communications, locations=locations)

# ==========================================
# ACCIONES COMUNES (CHECKLIST)
# ==========================================

@onboarding_bp.route('/item/<int:id>/toggle', methods=['POST'])
@login_required
@requires_permission('hr_people')
def toggle_item(id):
    if not has_write_permission('hr_people'):
        return jsonify({'status': 'error', 'message': 'Write access required to toggle items.'}), 403
    item = db.get_or_404(ProcessItem, id)
    target_state = not item.is_completed
    item.is_completed = target_state

    # Automation: If ServiceAccess item completed, link user to service
    if target_state and item.item_type == 'ServiceAccess' and item.linked_object_id and item.onboarding_process_id:
        process = item.onboarding_process
        if process and process.user: # Requires User to be created/linked first
            service = db.session.get(BusinessService,item.linked_object_id)
            if service:
                if process.user not in service.users:
                    service.users.append(process.user)
                    flash(f'User automatically added to service access list: {service.name}', 'success')
                else:
                    flash(f'User already has access to {service.name}.', 'info')

    db.session.commit()
    
    # Redirigir inteligentemente
    if item.onboarding_process_id:
        return redirect(url_for(_EP_ONBOARDING, id=item.onboarding_process_id))
    elif item.offboarding_process_id:
        return redirect(url_for(_EP_OFFBOARDING, id=item.offboarding_process_id))
    
    return redirect(url_for(_EP_INDEX))

@onboarding_bp.route('/process/<string:type>/<int:id>/complete', methods=['POST'])
@login_required
@requires_permission('hr_people')
def complete_process(type, id):
    if not has_write_permission('hr_people'):
        flash('Write access required to complete process.', 'danger')
        return redirect(request.referrer)
    """Marca el proceso entero como completado y archiva usuario si es offboarding."""
    if type == 'onboarding':
        process = db.get_or_404(OnboardingProcess, id)
        process.status = 'Completed'
        flash(f'Onboarding de {process.new_hire_name} completado.', 'success')
        
    else: # Offboarding
        process = db.get_or_404(OffboardingProcess, id)
        process.status = 'Completed'
        process.departure_date = today() # Fijar fecha real de cierre
        
        # LÓGICA DE ARCHIVADO AUTOMÁTICO
        if process.user:
            process.user.is_archived = True
            # Opcional: Limpiar su password o tokens de sesión aquí si tuvieras
        flash(f'Offboarding completado. El usuario {process.user.name} ha sido archivado.', 'warning')
        
    db.session.commit()
    return redirect(url_for(_EP_INDEX))

@onboarding_bp.route('/offboarding/<int:process_id>/revoke_service/<int:item_id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def revoke_service_access(process_id, item_id):
    if not has_write_permission('hr_people'):
        flash('Write access required to revoke access.', 'danger')
        return redirect(url_for(_EP_OFFBOARDING, id=process_id))
    process = db.get_or_404(OffboardingProcess, process_id)
    item = db.get_or_404(ProcessItem, item_id)
    
    # Validation
    # Let's check the model. ProcessItem has separate FKs or a single one?
    # Based on new_onboarding/offboarding codes:
    # db.session.add(ProcessItem(offboarding_process_id=process.id ...
    # So check offboarding_process_id
    if item.offboarding_process_id != process.id:
        flash('Invalid item for this process.', 'danger')
        return redirect(url_for(_EP_OFFBOARDING, id=process.id))

    if item.item_type != 'RevokeAccess':
        flash('Invalid item type.', 'danger')
        return redirect(url_for(_EP_OFFBOARDING, id=process.id))

    service = db.session.get(BusinessService, item.linked_object_id)
    target_user = process.user

    if service and target_user:
        if target_user in service.users:
            service.users.remove(target_user)
            flash(f'User removed from {service.name}.', 'success')
        else:
            flash(f'User was not in {service.name} (already removed?).', 'warning')

        item.is_completed = True
        item.completed_at = now()
        db.session.commit()
    else:
        flash('Service or User not found.', 'danger')

    return redirect(url_for(_EP_OFFBOARDING, id=process.id))

@onboarding_bp.route('/offboarding/<int:process_id>/revoke_subscription/<int:item_id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def revoke_subscription_access(process_id, item_id):
    if not has_write_permission('hr_people'):
        flash('Write access required to revoke access.', 'danger')
        return redirect(url_for(_EP_OFFBOARDING, id=process_id))
    process = db.get_or_404(OffboardingProcess, process_id)
    item = db.get_or_404(ProcessItem, item_id)
    
    if item.offboarding_process_id != process.id:
        flash('Invalid item for this process.', 'danger')
        return redirect(url_for(_EP_OFFBOARDING, id=process_id))

    if item.item_type != 'RevokeSubscriptionAccess':
        flash('Invalid item type.', 'danger')
        return redirect(url_for(_EP_OFFBOARDING, id=process_id))

    subscription = db.session.get(Subscription,item.linked_object_id)
    target_user = process.user
    
    if subscription and target_user:
        if target_user in subscription.users:
            subscription.users.remove(target_user)
            flash(f'User removed from {subscription.name}.', 'success')

            # Log cost change if subscription uses per-user pricing
            if subscription.pricing_model == 'per_user':
                log_subscription_cost_change(subscription, reason='user_removed')
        else:
            flash(f'User was not in {subscription.name} (already removed?).', 'warning')

        item.is_completed = True
        item.completed_at = now()
        db.session.commit()
    else:
        flash('Subscription or User not found.', 'danger')

    return redirect(url_for(_EP_OFFBOARDING, id=process.id))

@onboarding_bp.route('/process/<int:process_id>/create_user/<int:item_id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def create_user_account(process_id, item_id):
    if not has_write_permission('hr_people'):
        flash('Write access required to create user.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process_id))
    process = db.get_or_404(OnboardingProcess, process_id)
    item = db.get_or_404(ProcessItem, item_id)
    
    # Validation
    if item.onboarding_process_id != process.id:
        flash('Invalid item for this process.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process_id))

    if item.item_type != 'CreateUser':
        flash('Invalid item type.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process_id))
        
    # Check if user already linked
    if process.user_id:
        flash('Process already has a user linked.', 'warning')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))

    # Generate Email
    # Generate Email
    # Format: firstname.lastname@example.com (simplified logic)
    if process.target_email:
        email = process.target_email
    else:
        # Removing special chars, spaces to dots
        clean_name = "".join(c for c in process.new_hire_name if c.isalnum() or c.isspace()).lower()
        email_local = clean_name.replace(" ", ".")
        email = f"{email_local}@example.com"
    
    # Generate Password
    password = generate_secure_password()
    
    # Check if email exists
    if User.query.filter_by(email=email).first():
        # Fallback: append random number
        import random
        email = f"{email_local}{random.randint(10,99)}@example.com"
    
    # Create User
    new_user = User(name=process.new_hire_name, email=email, role='user', personal_email=process.personal_email, manager_id=process.assigned_manager_id, buddy_id=process.assigned_buddy_id)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.flush() # Get ID
    
    # Link to Process
    process.user_id = new_user.id
    
    # Mark item complete
    item.is_completed = True
    
    db.session.commit()
    
    flash(f"User created!\nEmail: {email}\nPassword: {password}", "success")
    return redirect(url_for(_EP_ONBOARDING, id=process.id))

@onboarding_bp.route('/process/<int:process_id>/add_to_service/<int:item_id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def add_user_to_service(process_id, item_id):
    if not has_write_permission('hr_people'):
        flash('Write access required to add user to service.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process_id))
    process = db.get_or_404(OnboardingProcess, process_id)
    item = db.get_or_404(ProcessItem, item_id)
    
    if item.item_type != 'ServiceAccess' or not item.linked_object_id:
        flash('Invalid item type.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))

    service = db.session.get(BusinessService,item.linked_object_id)
    if not service:
        flash('Service not found.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))
        
    if not process.user:
        flash('No user linked to this onboarding process yet. Create the user first.', 'warning')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))
        
    if process.user not in service.users:
        service.users.append(process.user)
        # Avoid double flash if toggle also triggers? No, toggle triggers on is_completed change.
        # This button is manual. It also marks completed.
        flash(f'User {process.user.name} added to {service.name}.', 'success')
        item.is_completed = True
        db.session.commit()
    else:
        flash(f'User already in {service.name}.', 'info')
        item.is_completed = True
        db.session.commit()
        
    return redirect(url_for(_EP_ONBOARDING, id=process.id))

@onboarding_bp.route('/process/<int:process_id>/add_to_subscription/<int:item_id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def add_user_to_subscription(process_id, item_id):
    if not has_write_permission('hr_people'):
        flash('Write access required to add user to subscription.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process_id))
    process = db.get_or_404(OnboardingProcess, process_id)
    item = db.get_or_404(ProcessItem, item_id)
    
    if item.item_type != 'Subscription' or not item.linked_object_id:
        flash('Invalid item type.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))

    subscription = db.session.get(Subscription,item.linked_object_id)
    if not subscription:
        flash('Subscription not found.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))
        
    if not process.user:
        flash('No user linked to this onboarding process yet. Create the user first.', 'warning')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))
        
    if process.user not in subscription.users:
        subscription.users.append(process.user)
        flash(f'User {process.user.name} added to subscription {subscription.name}.', 'success')
        item.is_completed = True

        # Log cost change if subscription uses per-user pricing
        if subscription.pricing_model == 'per_user':
            log_subscription_cost_change(subscription, reason='user_added')

        db.session.commit()
    else:
        flash(f'User already has access to {subscription.name}.', 'info')
        item.is_completed = True
        db.session.commit()
        
    return redirect(url_for(_EP_ONBOARDING, id=process.id))

@onboarding_bp.route('/process/<int:process_id>/add_to_course/<int:item_id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def add_user_to_course(process_id, item_id):
    if not has_write_permission('hr_people'):
        flash('Write access required to add user to course.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process_id))
    from datetime import date, timedelta
    from ..models import CourseAssignment
    
    process = db.get_or_404(OnboardingProcess, process_id)
    item = db.get_or_404(ProcessItem, item_id)
    
    if item.item_type != 'Course' or not item.linked_object_id:
        flash('Invalid item type.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))

    course = db.session.get(Course,item.linked_object_id)
    if not course:
        flash('Course not found.', 'danger')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))
        
    if not process.user:
        flash('No user linked to this onboarding process yet. Create the user first.', 'warning')
        return redirect(url_for(_EP_ONBOARDING, id=process.id))
    
    # Check if user is already assigned to this course
    existing = CourseAssignment.query.filter_by(course_id=course.id, user_id=process.user.id).first()
    if not existing:
        due_date = today() + timedelta(days=course.completion_days)
        assignment = CourseAssignment(course_id=course.id, user_id=process.user.id, due_date=due_date)
        db.session.add(assignment)
        flash(f'User {process.user.name} assigned to course {course.title}.', 'success')
        item.is_completed = True
        db.session.commit()
    else:
        flash(f'User already assigned to {course.title}.', 'info')
        item.is_completed = True
        db.session.commit()
        
    return redirect(url_for(_EP_ONBOARDING, id=process.id))

# ==========================================
# API / UTILS
# ==========================================

@onboarding_bp.route('/templates', methods=['GET'])
@login_required
@requires_permission('hr_people')
def list_templates():
    tasks = ProcessTemplate.query.all()
    return render_template('onboarding/templates_list.html', tasks=tasks)

@onboarding_bp.route('/templates/new', methods=['POST'])
@login_required
@requires_permission('hr_people')
def new_template_task():
    if not has_write_permission('hr_people'):
        flash('Write access required to create templates.', 'danger')
        return redirect(url_for('onboarding.list_templates'))
    name = request.form.get('name')
    process_type = request.form.get('process_type')
    if name and process_type:
        t = ProcessTemplate(name=name, process_type=process_type)
        db.session.add(t)
        db.session.commit()
        flash('Global task created.', 'success')
    return redirect(url_for('onboarding.list_templates'))

@onboarding_bp.route('/templates/<int:id>/toggle', methods=['POST'])
@login_required
@requires_permission('hr_people')
def toggle_template_task(id):
    if not has_write_permission('hr_people'):
        flash('Write access required to toggle templates.', 'danger')
        return redirect(url_for('onboarding.list_templates'))
    t = db.get_or_404(ProcessTemplate, id)
    t.is_active = not t.is_active
    db.session.commit()
    flash('Task status updated.', 'success')
    return redirect(url_for('onboarding.list_templates'))

# ==========================================
#  ARCHIVED PROCESSES
# ==========================================

# Histórico de Procesos (Auditoría)
@onboarding_bp.route('/history', methods=['GET'])
@login_required
def history():
    """Muestra los procesos completados para auditoría."""
    completed_onboardings = OnboardingProcess.query.filter_by(status='Completed').order_by(OnboardingProcess.id.desc()).all()
    completed_offboardings = OffboardingProcess.query.filter_by(status='Completed').order_by(OffboardingProcess.id.desc()).all()
    
    return render_template('onboarding/history.html', 
                           onboardings=completed_onboardings,
                           offboardings=completed_offboardings)

# ==========================================
#  OFFBOARDING TRANSFERS
# ==========================================

@onboarding_bp.route('/transfer/risk/<int:id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def transfer_risk(id):
    if not has_write_permission('hr_people'):
        flash('Write access required to transfer risks.', 'danger')
        return redirect(request.referrer)
    risk = db.get_or_404(Risk, id)
    new_owner_id = request.form.get('new_owner_id')
    redirect_url = request.form.get('redirect_url')
    
    # Update owner (None if empty, meaning unassigned)
    risk.owner_id = int(new_owner_id) if new_owner_id else None
    
    # Auto-complete related offboarding item if exists
    offboarding_item = ProcessItem.query.filter_by(
        item_type='Risk', 
        linked_object_id=id, 
        is_completed=False
    ).first()
    if offboarding_item and offboarding_item.offboarding_process_id:
        offboarding_item.is_completed = True
        
    db.session.commit()
    
    if risk.owner:
        flash(f'Risk "{risk.risk_description[:30]}..." transferred to {risk.owner.name}.', 'success')
    else:
        flash(f'Risk "{risk.risk_description[:30]}..." is now unassigned.', 'info')
        
    return redirect(redirect_url or request.referrer)

@onboarding_bp.route('/transfer/service/<int:id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def transfer_service(id):
    if not has_write_permission('hr_people'):
        flash('Write access required to transfer services.', 'danger')
        return redirect(request.referrer)
    service = db.get_or_404(BusinessService, id)
    new_owner_id = request.form.get('new_owner_id')
    redirect_url = request.form.get('redirect_url')
    
    # Update owner
    service.owner_id = int(new_owner_id) if new_owner_id else None
    
    # Auto-complete related offboarding item if exists
    offboarding_item = ProcessItem.query.filter_by(
        item_type='Service', 
        linked_object_id=id, 
        is_completed=False
    ).first()
    if offboarding_item and offboarding_item.offboarding_process_id:
        offboarding_item.is_completed = True
        
    db.session.commit()
    
    if service.owner:
        flash(f'Service "{service.name}" transferred to {service.owner.name}.', 'success')
    else:
        flash(f'Service "{service.name}" is now unassigned.', 'info')
        
    return redirect(redirect_url or request.referrer)

@onboarding_bp.route('/transfer/credential/<int:id>', methods=['POST'])
@login_required
@requires_permission('hr_people')
def transfer_credential(id):
    if not has_write_permission('hr_people'):
        flash('Write access required to transfer credentials.', 'danger')
        return redirect(request.referrer)
    from ..models.credentials import Credential
    
    credential = db.get_or_404(Credential, id)
    new_owner_id = request.form.get('new_owner_id')
    redirect_url = request.form.get('redirect_url')
    
    # Update owner
    if new_owner_id:
        credential.owner_id = int(new_owner_id)
        credential.owner_type = 'User'  # Ensure it's set to User
    else:
        credential.owner_id = None
    
    # Auto-complete related offboarding item if exists
    offboarding_item = ProcessItem.query.filter_by(
        item_type='Credential', 
        linked_object_id=id, 
        is_completed=False
    ).first()
    if offboarding_item and offboarding_item.offboarding_process_id:
        offboarding_item.is_completed = True
        
    db.session.commit()
    
    if credential.owner:
        flash(f'Credential "{credential.name}" transferred to {credential.owner.name}.', 'success')
    else:
        flash(f'Credential "{credential.name}" is now unassigned.', 'info')
        
    return redirect(redirect_url or request.referrer)


# ==========================================
#  COMMUNICATIONS MANAGEMENT
# ==========================================

@onboarding_bp.route('/communications/<int:id>/send_now', methods=['POST'])
@login_required
@requires_permission('hr_people')
def send_communication_now(id):
    if not has_write_permission('hr_people'):
        flash('Write access required to send communications.', 'danger')
        return redirect(request.referrer)
    """Force send a scheduled communication immediately."""
    from ..utils.communications_context import get_template_context, render_email_template
    from .. import notifications
    from flask import current_app
    
    comm = db.get_or_404(ScheduledCommunication, id)
    
    if comm.status != 'pending':
        flash(f'Communication is already {comm.status}.', 'warning')
        return redirect(request.referrer or url_for(_EP_INDEX))
    
    if not comm.recipient_email:
        flash('No recipient email configured for this communication.', 'danger')
        return redirect(request.referrer or url_for(_EP_INDEX))
    
    try:
        # Get context and render template
        context = get_template_context(comm)
        subject, body_html = render_email_template(comm.template, context)
        
        # Send email
        success = notifications.send_email(
            current_app._get_current_object(),
            subject,
            body_html,
            [comm.recipient_email]
        )
        
        if success:
            comm.status = 'sent'
            comm.sent_at = now()
            flash(f'Email "{comm.template.name}" sent successfully to {comm.recipient_email}.', 'success')
        else:
            comm.status = 'failed'
            comm.error_message = 'Email sending failed - check SMTP configuration'
            flash('Failed to send email. Check server configuration.', 'danger')
            
    except Exception as e:
        comm.status = 'failed'
        comm.error_message = str(e)
        comm.retry_count += 1
        flash(f'Error sending email: {str(e)}', 'danger')
    
    db.session.commit()
    return redirect(request.referrer or url_for(_EP_INDEX))


@onboarding_bp.route('/communications/<int:id>/cancel', methods=['POST'])
@login_required
@requires_permission('hr_people')
def cancel_communication(id):
    if not has_write_permission('hr_people'):
        flash('Write access required to cancel communications.', 'danger')
        return redirect(request.referrer)
    """Cancel a pending scheduled communication."""
    comm = db.get_or_404(ScheduledCommunication, id)
    
    if comm.status != 'pending':
        flash(f'Cannot cancel - communication is already {comm.status}.', 'warning')
        return redirect(request.referrer or url_for(_EP_INDEX))
    
    comm.status = 'cancelled'
    db.session.commit()
    
    flash(f'Communication "{comm.template.name}" cancelled.', 'info')
    return redirect(request.referrer or url_for(_EP_INDEX))