"""What has to happen when a person leaves, derived from what they hold.

An offboarding checklist is not typed in: it is read off the inventory. Every asset
still checked out to the person, every license and subscription in their name, every
risk, service and credential they own, every service they can log in to, plus the
organisation's standing exit tasks — each becomes a ProcessItem on the process. When a
successor is named, ownership of risks, services and credentials moves to them on the
spot and those items are created already ticked.

This used to be the body of the route that handled the form. It is a service because
the rule "what does leaving entail" is the module's actual domain logic, and a route is
the wrong place to test it from.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import BusinessService, License, PaymentMethod, Peripheral, Risk, Subscription, User
from ..models.assets import AssetAssignment
from ..models.credentials import Credential
from ..models.onboarding import OffboardingProcess, ProcessItem, ProcessTemplate

#: Longest a risk's wording is shown in its checklist line before it is cut.
RISK_DESCRIPTION_PREVIEW = 75


@dataclass
class Checklist:
    """The items created for one process, and what was transferred along the way."""
    items: List[ProcessItem] = field(default_factory=list)
    transferred_to: Optional[User] = None

    def add(self, process, description, item_type, linked_object_id=None, is_completed=False):
        item = ProcessItem(
            offboarding_process_id=process.id,
            description=description,
            item_type=item_type,
            linked_object_id=linked_object_id,
            is_completed=is_completed,
        )
        db.session.add(item)
        self.items.append(item)
        return item


def build_offboarding_checklist(process: OffboardingProcess, target_user: User,
                                transfer_to: Optional[User] = None) -> Checklist:
    """Populate `process` with everything `target_user` holds. Does not commit.

    `process` must already have an id (be flushed or committed) so the items can point
    at it. When `transfer_to` is given, the risks, services and credentials the person
    owns are reassigned to them immediately and their items are created completed.
    """
    checklist = Checklist(transferred_to=transfer_to)
    transfer_to_id = transfer_to.id if transfer_to else None

    # --- Hardware -------------------------------------------------------------------
    open_assignments = AssetAssignment.query.options(joinedload(AssetAssignment.asset)).filter(
        AssetAssignment.user_id == target_user.id,
        AssetAssignment.checked_in_date.is_(None),
    ).all()
    for assignment in open_assignments:
        checklist.add(process, f"💻 Pick up Asset: {assignment.asset.name} ({assignment.asset.serial_number})",
                      'Asset', assignment.asset.id)

    for peripheral in Peripheral.query.filter_by(user_id=target_user.id).all():
        checklist.add(process, f"⌨️ Pick up Peripheral: {peripheral.name}", 'Peripheral', peripheral.id)

    # --- Software -------------------------------------------------------------------
    licenses = License.query.options(joinedload(License.software)).filter_by(user_id=target_user.id).all()
    for lic in licenses:
        desc = f"🔑 Revoke License: {lic.name}"
        if lic.software:
            desc += f" ({lic.software.name})"
        checklist.add(process, desc, 'License', lic.id)

    for sub in Subscription.query.filter_by(user_id=target_user.id).all():
        checklist.add(process, f"🔄 Cancel/Transfer Subscription: {sub.name}", 'Subscription')

    for sub in Subscription.query.filter(Subscription.users.contains(target_user)).all():
        checklist.add(process, f"🛑 Revoke access to Subscription: {sub.name}", 'RevokeSubscriptionAccess', sub.id)

    # --- Finance --------------------------------------------------------------------
    payment_methods = PaymentMethod.query.options(joinedload(PaymentMethod.subscriptions)).filter_by(
        user_id=target_user.id).all()
    for pm in payment_methods:
        linked = len(pm.subscriptions)
        if linked:
            desc = f"⚠️ BLOCKING: Card '{pm.name}' has {linked} subscriptions. Change before canceling."
        else:
            desc = f"💳 Recover/Cancel Payment Method: {pm.name}"
        checklist.add(process, desc, 'PaymentMethod', pm.id)

    # --- Ownership: transferred on the spot when a successor is named ---------------
    for risk in Risk.query.filter_by(owner_id=target_user.id).all():
        wording = risk.risk_description
        if len(wording) > RISK_DESCRIPTION_PREVIEW:
            wording = wording[:RISK_DESCRIPTION_PREVIEW] + '..'
        if transfer_to_id:
            risk.owner_id = transfer_to_id
        checklist.add(process, f"⚠️ TRANSFER RISK: {wording}", 'Risk', risk.id, is_completed=bool(transfer_to_id))

    for service in BusinessService.query.filter_by(owner_id=target_user.id).all():
        if transfer_to_id:
            service.owner_id = transfer_to_id
        checklist.add(process, f"⚠️ TRANSFER SERVICE: {service.name} (User is Owner)", 'ServiceOwnership',
                      service.id, is_completed=bool(transfer_to_id))

    for service in BusinessService.query.filter(BusinessService.users.contains(target_user)).all():
        checklist.add(process, f"🛑 Revoke access to {service.category or 'Service'}: {service.name}",
                      'RevokeAccess', service.id)

    for cred in Credential.query.filter_by(owner_id=target_user.id, owner_type='User').all():
        if transfer_to_id:
            cred.owner_id = transfer_to_id
        checklist.add(process, f"🔑 REASSIGN CREDENTIAL: {cred.name} ({cred.type})", 'Credential',
                      cred.id, is_completed=bool(transfer_to_id))

    # --- The organisation's standing exit tasks -------------------------------------
    for task in ProcessTemplate.query.filter_by(process_type='offboarding', is_active=True).all():
        checklist.add(process, task.name, 'StaticTask')

    return checklist
