from datetime import datetime
from sqlalchemy import and_
from sqlalchemy.orm import foreign
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from .core import Attachment
from .security import Framework
from .onboarding import OnboardingProcess, OffboardingProcess
from src.utils.timezone_helper import now


# Association table for audit participants
audit_participants = db.Table('audit_participants',
    db.Column('audit_id', db.Integer, db.ForeignKey('compliance_audit.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True)
)

# Association table for linking audits to onboarding/offboarding processes (Evidence)
audit_evidence = db.Table('audit_evidence',
    db.Column('audit_id', db.Integer, db.ForeignKey('compliance_audit.id'), primary_key=True),
    db.Column('onboarding_id', db.Integer, db.ForeignKey('onboarding_process.id'), nullable=True),
    db.Column('offboarding_id', db.Integer, db.ForeignKey('offboarding_process.id'), nullable=True)
)

class ComplianceAudit(db.Model):
    """
    Represents a snapshot of a Framework at a specific point in time for auditing purposes.
    Acts as a "Defense Platform" container.
    """
    __tablename__ = 'compliance_audit'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=True)
    
    # Status & Outcome
    status = db.Column(db.String(50), default='Planned', nullable=False) # Planned, Prep, Auditor Review, Closed
    outcome = db.Column(db.String(50)) # Pass, Fail, Qualified
    
    # Dates
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=lambda: now())
    locked_at = db.Column(db.DateTime, nullable=True)

    # Audit type and snapshot data for drift detection
    audit_type = db.Column(db.String(50), default='manual', nullable=True)  # 'manual', 'drift_snapshot'
    snapshot_data = db.Column(db.JSON, nullable=True)  # Stores compliance snapshot for drift detection

    @property
    def is_locked(self):
        return self.locked_at is not None

    # Relationships
    framework_id = db.Column(db.Integer, db.ForeignKey('framework.id'), nullable=True)
    
    # External Auditor (Contact from CRM)
    auditor_id = db.Column(db.Integer, db.ForeignKey('contact.id'), nullable=True)
    
    # Internal Lead (User responsible for defense)
    internal_lead_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Relationships
    framework = db.relationship('Framework')
    auditor = db.relationship('Contact')
    internal_lead = db.relationship('User', foreign_keys=[internal_lead_id])
    
    participants = db.relationship('User', secondary=audit_participants, backref='audits_participating')
    
    onboardings = db.relationship('OnboardingProcess', secondary=audit_evidence, backref=db.backref('audits', overlaps="audits,onboardings,offboardings"), overlaps="audits,offboardings")
    offboardings = db.relationship('OffboardingProcess', secondary=audit_evidence, backref=db.backref('audits', overlaps="audits,onboardings,offboardings"), overlaps="audits,onboardings")
    
    audit_items = db.relationship(
        'AuditControlItem',
        backref='audit',
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        lazy=LAZY_DYNAMIC
    )

    # Polymorphic attachments (Proposal, Final Report, etc.)
    attachments = db.relationship(
        'Attachment',
        primaryjoin=lambda: and_(
            foreign(Attachment.linkable_id) == ComplianceAudit.id,
            Attachment.linkable_type == 'ComplianceAudit'
        ),
        lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="attachments"
    )

    @classmethod
    def create_snapshot(cls, framework_id, name, auditor_contact_id, internal_lead_id, 
                       copy_links=False, evidence_months=6, sample_size=None):
        """
        Creates a new ComplianceAudit and snapshots all controls from the given framework.
        If copy_links is True, it also snapshots the evidence links.
        
        Args:
            framework_id: ID of the framework to snapshot
            name: Name for the audit
            auditor_contact_id: External auditor contact ID
            internal_lead_id: Internal lead user ID
            copy_links: Whether to copy manual compliance links
            evidence_months: Number of months to look back for automated evidence (default: 6)
            sample_size: Optional limit on evidence items per control (random sample)
        """
        # 1. Get the source Framework
        framework = db.session.get(Framework, framework_id)
        if not framework:
            raise ValueError(f"Framework with id {framework_id} not found")

        # 2. Create the ComplianceAudit instance
        audit = cls(
            name=name,
            framework_id=framework_id,
            auditor_id=auditor_contact_id,
            internal_lead_id=internal_lead_id,
            status='Planned'
        )
        db.session.add(audit)
        db.session.flush() # Flush to get the audit.id

        # 3. Iterate over controls and create AuditControlItem snapshots
        controls = framework.framework_controls.all()
        
        for control in controls:
            audit_item = AuditControlItem(
                audit_id=audit.id,
                original_control_id=control.id,
                
                # Snapshot fields (Copying values)
                control_code=control.control_id,
                control_title=control.name,
                control_description=control.description,
                
                # SOA: Inherit from framework control
                is_applicable=control.is_applicable,
                justification=control.soa_justification,

                # Audit defaults
                status='Not Applicable' if not control.is_applicable else 'Pending',
            )
            db.session.add(audit_item)
            db.session.flush() # Need ID for links

            # 4. Copy Manual Links if requested
            if copy_links:
                original_links = control.compliance_links.all()
                for link in original_links:
                    audit_link = AuditControlLink(
                        audit_item_id=audit_item.id,
                        linkable_type=link.linkable_type,
                        linkable_id=link.linkable_id,
                        description=link.description,
                        is_automated=False
                    )
                    db.session.add(audit_link)

        # 5. Commit the audit structure
        db.session.commit()
        
        # 6. Populate automated evidence from compliance rules
        audit._populate_automated_evidence(evidence_months, sample_size)
        
        return audit

    def _populate_automated_evidence(self, evidence_months, sample_size=None):
        """
        Populates automated evidence for all audit items by evaluating compliance rules.
        This method should be called after the audit structure (items) has been created and committed.
        
        Args:
            evidence_months: Number of months to look back for evidence
            sample_size: Optional limit on evidence items per control (random sample)
        """
        from ..services.compliance_service import get_compliance_evaluator
        
        evaluator = get_compliance_evaluator()
        
        # Iterate over all audit items in this audit
        for audit_item in self.audit_items:
            # Get the original control to access its rules
            if not audit_item.original_control:
                continue
                
            control = audit_item.original_control
            rules = control.rules.all() if hasattr(control, 'rules') else []
            
            for rule in rules:
                if not rule.enabled:
                    continue
                    
                try:
                    # Collect historical evidence over the specified time period
                    evidence_list = evaluator.collect_evidence(rule, evidence_months, sample_size)
                    
                    # Create a link for each piece of evidence found
                    for evidence in evidence_list:
                        # Extract the relevant date from the evidence object
                        evidence_date = ComplianceAudit._extract_evidence_date(evidence, rule.target_model)
                        date_str = evidence_date.strftime('%Y-%m-%d') if evidence_date else 'N/A'
                        
                        # Determine linkable_type from target_model
                        linkable_type = rule.target_model  # e.g., 'ActivityExecution', 'Campaign'
                        
                        audit_link = AuditControlLink(
                            audit_item_id=audit_item.id,
                            linkable_type=linkable_type,
                            linkable_id=evidence.id,
                            description=f"Automated Evidence: {rule.name} - Found on {date_str}",
                            is_automated=True
                        )
                        db.session.add(audit_link)
                        
                except Exception as e:
                    # Log but don't fail the snapshot for a single rule error
                    import logging
                    logging.warning(f"Failed to capture automated evidence for rule {rule.id}: {e}")
        
        # Commit all automated evidence links
        db.session.commit()


    @staticmethod
    def _extract_evidence_date(evidence, model_type):
        """
        Extract the relevant date from an evidence object based on its model type.
        
        Args:
            evidence: The evidence object
            model_type: String identifier of the model type
            
        Returns:
            datetime or date object, or None if not found
        """
        from datetime import date
        
        date_field_map = {
            'ActivityExecution': 'execution_date',
            'Campaign': 'processed_at',
            'MaintenanceLog': 'created_at',
            'BCDRTestLog': 'test_date',
            'SecurityAssessment': 'assessment_date',
            'RiskAssessment': 'created_at'
        }
        
        field_name = date_field_map.get(model_type, 'created_at')
        evidence_date = getattr(evidence, field_name, None)
        
        # Convert date to datetime for consistency
        if evidence_date and isinstance(evidence_date, date) and not isinstance(evidence_date, datetime):
            evidence_date = datetime.combine(evidence_date, datetime.min.time())
        
        return evidence_date


    @classmethod
    def clone(cls, source_id, new_owner_id, target_date, copy_audit_extras=False, 
              evidence_months=6, sample_size=None):
        """
        Clones an existing audit for a new period (Intelligent Deep Clone).
        
        Evidence Import Strategy (Per Control):
        1. ALWAYS import framework structural evidence (Policies, Procedures)
        2. ALWAYS import manual evidence from previous audit
        3. ALWAYS regenerate automated evidence from fresh compliance rule evaluations
        4. PREVENT duplicates using tuple-based deduplication (linkable_type, linkable_id)
        
        Args:
            source_id: ID of the source audit to clone
            new_owner_id: ID of the user who will own the new audit
            target_date: Target completion date for the new audit
            copy_audit_extras: Deprecated parameter (kept for compatibility)
            evidence_months: Number of months to look back for automated evidence
            sample_size: Optional limit on evidence items per control
            
        Preserves:
            - SOA (is_applicable, justification, internal_comments)
            
        Resets:
            - Status (Compliant/Gap -> Pending)
            - Dates, Auditor
        """
        source = db.session.get(cls, source_id)
        if not source:
             raise ValueError(f"Source audit with id {source_id} not found")

        # 1. Create New Audit Header
        year = target_date.year if target_date else now().year
        new_audit = cls(
            name=f"Renewal {year}: {source.name}",
            framework_id=source.framework_id,
            internal_lead_id=new_owner_id,
            # Reset dates and auditor
            auditor_id=None,
            start_date=None,
            end_date=target_date, # Use target_date as end_date deadline
            status='Planned',
            outcome=None,
            locked_at=None
        )
        db.session.add(new_audit)
        db.session.flush() # Generate ID

        # 2. Clone Controls with Intelligent Evidence Import
        for old_item in source.audit_items:
            new_item = AuditControlItem(
                audit_id=new_audit.id,
                original_control_id=old_item.original_control_id,
                
                # --- SNAPSHOT TEXT ---
                # Copy from the OLD item to preserve the snapshot state
                control_code=old_item.control_code,
                control_title=old_item.control_title,
                control_description=old_item.control_description,

                # --- COPY SOA & TEXT DATA ---
                justification=old_item.justification,
                internal_comments=old_item.internal_comments,
                is_applicable=old_item.is_applicable
            )
            
            # --- STATUS RESET LOGIC ---
            if not old_item.is_applicable:
                new_item.status = 'Not Applicable'
            else:
                new_item.status = 'Pending' # Reset to Pending for re-validation

            db.session.add(new_item)
            db.session.flush() # Need ID for links
            
            # --- INTELLIGENT EVIDENCE IMPORT (3 PHASES) ---
            
            # Deduplication tracker: stores (linkable_type, linkable_id) tuples
            existing_links = set()
            
            # PHASE 1: Import Framework Evidence (ALWAYS)
            # This is the structural evidence defined in the live framework
            if old_item.original_control:
                framework_links = old_item.original_control.compliance_links.all()
                for link in framework_links:
                    # Create the audit link
                    new_link = AuditControlLink(
                        audit_item_id=new_item.id,
                        linkable_type=link.linkable_type,
                        linkable_id=link.linkable_id,
                        description=link.description,
                        is_automated=False
                    )
                    db.session.add(new_link)
                    
                    # Track this link to prevent duplicates
                    existing_links.add((link.linkable_type, link.linkable_id))
            
            # PHASE 2: Import Manual Evidence from Previous Audit (ALWAYS)
            # Copy all manual (non-automated) evidence from the previous audit
            for link in old_item.linked_objects:
                # Skip automated evidence (it's stale, will be regenerated in Phase 3)
                if link.is_automated:
                    continue
                
                # Skip if already imported from framework (deduplication)
                link_tuple = (link.linkable_type, link.linkable_id)
                if link_tuple in existing_links:
                    continue
                
                # This is a manual link from the previous audit
                # Import it to save auditor time
                new_link = AuditControlLink(
                    audit_item_id=new_item.id,
                    linkable_type=link.linkable_type,
                    linkable_id=link.linkable_id,
                    description=link.description,
                    is_automated=False
                )
                db.session.add(new_link)
                
                # Track to prevent duplicates (though unlikely at this point)
                existing_links.add(link_tuple)

        # 3. Commit the audit structure
        db.session.commit()
        
        # PHASE 3: Regenerate Automated Evidence (ALWAYS)
        # This ensures we have fresh, current compliance data
        new_audit._populate_automated_evidence(evidence_months, sample_size)
        
        return new_audit


class AuditControlItem(db.Model):
    """
    Represents a specific control within an audit. 
    Stores a snapshot of the original control text to preserve integrity.
    """
    __tablename__ = 'audit_control_item'

    id = db.Column(db.Integer, primary_key=True)
    audit_id = db.Column(db.Integer, db.ForeignKey('compliance_audit.id'), nullable=False)
    original_control_id = db.Column(db.Integer, db.ForeignKey('framework_control.id'), nullable=True)

    # --- Snapshot Fields (Copied from FrameworkControl) ---
    control_code = db.Column(db.String(100), nullable=False) # e.g. "A.5.1"
    control_title = db.Column(db.String(512), nullable=False)
    control_description = db.Column(db.Text)

    # --- SOA (Statement of Applicability) Fields ---
    is_applicable = db.Column(db.Boolean, default=True, nullable=False)
    justification = db.Column(db.Text) # For SOA
    
    # --- Defense & Findings ---
    internal_comments = db.Column(db.Text) # Private team chat/notes
    auditor_findings = db.Column(db.Text) # Notes from the auditor
    
    status = db.Column(db.String(50), default='Pending', nullable=False) # Pending, Compliant, Observation, Gap, Not Applicable

    # --- Relationships ---
    # audit relationship is defined in ComplianceAudit via backref
    original_control = db.relationship('FrameworkControl')

    # Linked Evidence (Snapshot of connections)
    linked_objects = db.relationship(
        'AuditControlLink',
        backref='audit_item',
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        lazy=LAZY_DYNAMIC
    )

    # Polymorphic attachments (Evidence files uploaded directly to this item)
    attachments = db.relationship(
        'Attachment',
        primaryjoin=lambda: and_(
            foreign(Attachment.linkable_id) == AuditControlItem.id,
            Attachment.linkable_type == 'AuditControlItem'
        ),
        lazy=LAZY_DYNAMIC,
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="attachments"
    )

class AuditControlLink(db.Model):
    """
    Represents a link to an evidence object (Asset, Policy, etc.) specifically for this audit item.
    Allows the audit to have its own set of evidences, independent of the live framework.
    """
    __tablename__ = 'audit_control_link'

    id = db.Column(db.Integer, primary_key=True)
    audit_item_id = db.Column(db.Integer, db.ForeignKey('audit_control_item.id'), nullable=False)
    
    # Polymorphic Target
    linkable_type = db.Column(db.String(50), nullable=False)
    linkable_id = db.Column(db.Integer, nullable=False)
    
    description = db.Column(db.Text) # Context for why this is evidence
    is_automated = db.Column(db.Boolean, default=False, nullable=False) # True if captured from ComplianceRule
    
    @property
    def display_name(self):
        """Human-readable name of the object, whatever its type."""
        obj = self.linked_object
        if not obj:
            return "Elemento no encontrado"
        
        # Special handling for automated evidence types
        
        # 1. SecurityAssessment - show supplier name and date
        if self.linkable_type == 'SecurityAssessment':
            supplier_name = obj.supplier.name if hasattr(obj, 'supplier') and obj.supplier else 'Unknown Supplier'
            date_str = obj.assessment_date.strftime('%Y-%m-%d') if hasattr(obj, 'assessment_date') else 'N/A'
            return f"Security Assessment: {supplier_name} ({date_str})"
        
        # 2. MaintenanceLog - show event type and description
        if self.linkable_type == 'MaintenanceLog':
            event_type = obj.event_type if hasattr(obj, 'event_type') else 'Maintenance'
            description = obj.description[:50] if hasattr(obj, 'description') and obj.description else ''
            if len(description) > 50:
                description = description[:47] + '...'
            return f"{event_type}: {description}" if description else event_type
        
        # 3. RiskAssessment - show name
        if self.linkable_type == 'RiskAssessment':
            return getattr(obj, 'name', 'Risk Assessment')
        
        # 4. ActivityExecution - show activity name and date
        if self.linkable_type == 'ActivityExecution':
            activity_name = obj.activity.name if hasattr(obj, 'activity') and obj.activity else 'Activity'
            date_str = obj.execution_date.strftime('%Y-%m-%d') if hasattr(obj, 'execution_date') else ''
            return f"{activity_name} ({date_str})" if date_str else activity_name
        
        # 5. BCDRTestLog - show plan name and date
        if self.linkable_type == 'BCDRTestLog':
            plan_name = obj.plan.name if hasattr(obj, 'plan') and obj.plan else 'BCDR Test'
            date_str = obj.test_date.strftime('%Y-%m-%d') if hasattr(obj, 'test_date') else ''
            return f"{plan_name} Test ({date_str})" if date_str else f"{plan_name} Test"
        
        # 6. Campaign - use title
        if self.linkable_type == 'Campaign':
            return getattr(obj, 'title', 'Campaign')
        
        # 7. Policies and courses use 'title'
        if hasattr(obj, 'title'):
            return obj.title
            
        # 8. Riesgos usan 'risk_description'
        if hasattr(obj, 'risk_description'):
            # Truncate if too long
            desc = obj.risk_description
            return desc[:50] + '...' if len(desc) > 50 else desc

        # 9. Procesos de Onboarding
        if self.linkable_type == 'Onboarding':
            return f"Onboarding: {obj.new_hire_name or (obj.user.name if obj.user else 'Unknown')}"

        # 10. Procesos de Offboarding
        if self.linkable_type == 'Offboarding':
            return f"Offboarding: {obj.user.name if obj.user else 'Unknown'}"
            
        # 11. El resto (Assets, Users, etc.) usan 'name'
        return getattr(obj, 'name', str(obj))
    
    @property
    def linked_object(self):
        """Resolves the polymorphic relationship to the linked object."""
        # Import models inside the method to avoid circular imports
        from .assets import Asset, Peripheral, Software, License, MaintenanceLog
        from .procurement import Supplier, Purchase, Budget, Subscription
        from .core import Link, Documentation
        from .policy import Policy
        from .training import Course
        from .bcdr import BCDRPlan, BCDRTestLog
        from .security import SecurityIncident, SecurityAssessment, Risk, AssetInventory
        from .services import BusinessService
        from .auth import OrgChartSnapshot
        from .activities import ActivityExecution, SecurityActivity
        from .communications import Campaign
        from .risk_assessment import RiskAssessment

        # Map types to models
        model_map = {
            'OrgChartSnapshot': OrgChartSnapshot,
            'Asset': Asset,
            'Peripheral': Peripheral,
            'Software': Software,
            'License': License,
            'MaintenanceLog': MaintenanceLog,
            'Supplier': Supplier,
            'Purchase': Purchase,
            'Budget': Budget,
            'Subscription': Subscription,
            'Link': Link,
            'Documentation': Documentation,
            'Policy': Policy,
            'Course': Course,
            'BCDRPlan': BCDRPlan,
            'BCDRTestLog': BCDRTestLog,
            'SecurityIncident': SecurityIncident,
            'SecurityAssessment': SecurityAssessment,
            'Risk': Risk,
            'RiskAssessment': RiskAssessment,
            'AssetInventory': AssetInventory,
            'BusinessService': BusinessService,
            'Onboarding': OnboardingProcess,
            'Offboarding': OffboardingProcess,
            # Automated Evidence Types
            'ActivityExecution': ActivityExecution,
            'SecurityActivity': SecurityActivity,
            'Campaign': Campaign,
        }

        model = model_map.get(self.linkable_type)
        if model:
            return db.session.get(model, self.linkable_id)
        return None

    def is_orphaned(self):
        """
        Check if this link is orphaned (linked object no longer exists).

        Returns:
            bool: True if the linked object doesn't exist
        """
        return self.linked_object is None

    @staticmethod
    def find_orphaned_links():
        """
        Find all audit control links where the linked object no longer exists.

        Returns:
            list: List of orphaned AuditControlLink objects
        """
        orphaned = []
        all_links = AuditControlLink.query.all()

        for link in all_links:
            if link.is_orphaned():
                orphaned.append(link)

        return orphaned

    @staticmethod
    def cleanup_orphaned_links():
        """
        Remove all audit control links where the linked object no longer exists.

        Returns:
            int: Number of orphaned links removed
        """
        orphaned = AuditControlLink.find_orphaned_links()
        count = len(orphaned)

        for link in orphaned:
            db.session.delete(link)

        if count > 0:
            db.session.commit()

        return count
