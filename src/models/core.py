from src.utils.timezone_helper import now
from sqlalchemy import and_
from sqlalchemy.orm import foreign
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC

# Currency conversion rates (EUR base)
CURRENCY_RATES = {
    'EUR': 1.0,
    'USD': 0.92,
    'GBP': 1.18,
    'ZAR': 0.05
}

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    is_archived = db.Column(db.Boolean, default=False, nullable=False)

class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False) # Original filename
    secure_filename = db.Column(db.String(255), nullable=False, unique=True) # Stored filename
    created_at = db.Column(db.DateTime, default=lambda: now())

    linkable_id = db.Column(db.Integer, nullable=False)
    linkable_type = db.Column(db.String(50), nullable=False)

    __table_args__ = (
        db.Index('idx_attachment_linkable', 'linkable_id', 'linkable_type'),
    )

class NotificationSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email_enabled = db.Column(db.Boolean, default=False)
    email_recipient = db.Column(db.String(120))
    webhook_enabled = db.Column(db.Boolean, default=False)
    webhook_url = db.Column(db.String(255))
    # We'll store the days as a comma-separated string, e.g., "30,14,7"
    notify_days_before = db.Column(db.String(100), default="30,14,7")

link_tags = db.Table('link_tags',
    db.Column('link_id', db.Integer, db.ForeignKey('link.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True),
    db.Index('ix_link_tags_tag_id', 'tag_id')
)

class Link(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    url = db.Column(db.String(512), nullable=False) # Mandatory URL
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    # Polymorphic owner (User or Group)
    owner_id = db.Column(db.Integer)
    owner_type = db.Column(db.String(50)) # 'User' o 'Group'
    
    # Optional link to Software
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True, index=True)
    software = db.relationship('Software', backref='links')

    # Tags (many to many)
    tags = db.relationship('Tag', secondary=link_tags, backref=db.backref('links', lazy=LAZY_DYNAMIC))

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Link.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Link'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

    @property
    def owner(self):
        """The User or Group referenced by owner_type and owner_id."""
        from .auth import User, Group
        if self.owner_type == 'User' and self.owner_id:
            return db.session.get(User, self.owner_id)
        if self.owner_type == 'Group' and self.owner_id:
            return db.session.get(Group, self.owner_id)
        return None

documentation_tags = db.Table('documentation_tags',
    db.Column('documentation_id', db.Integer, db.ForeignKey('documentation.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True),
    db.Index('ix_documentation_tags_tag_id', 'tag_id')
)

class Documentation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    external_link = db.Column(db.String(512)) # Enlace externo
    created_at = db.Column(db.DateTime, default=lambda: now())
    
    # Polymorphic owner (User or Group)
    owner_id = db.Column(db.Integer)
    owner_type = db.Column(db.String(50)) # 'User' o 'Group'
    
    # Optional link to Software
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True, index=True)
    software = db.relationship('Software', backref='documentation')

    # Tags (many to many)
    tags = db.relationship('Tag', secondary=documentation_tags, backref=db.backref('documentation', lazy=LAZY_DYNAMIC))
    
    # Attachments (polymorphic)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Documentation.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Documentation')",
                            lazy=True, cascade=CASCADE_ALL_DELETE_ORPHAN,
                            overlaps="attachments")

    compliance_links = db.relationship('ComplianceLink',
        primaryjoin=lambda: and_(
            foreign(__import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_id) == Documentation.id,
            __import__('src.models.security', fromlist=['ComplianceLink']).ComplianceLink.linkable_type == 'Documentation'
        ),
        lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN,
        overlaps="compliance_links"
    )

    @property
    def owner(self):
        """The User or Group referenced by owner_type and owner_id."""
        from .auth import User, Group
        if self.owner_type == 'User' and self.owner_id:
            return db.session.get(User, self.owner_id)
        if self.owner_type == 'Group' and self.owner_id:
            return db.session.get(Group, self.owner_id)
        return None


class CostCenter(db.Model):
    """Cost Center for service financial tracking."""
    __tablename__ = 'cost_center'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, index=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: now())
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())
    
    def __repr__(self):
        return f'<CostCenter {self.code}>'


# Association table for Service-Documentation Many-to-Many
service_documentation = db.Table('service_documentation',
    db.Column('service_id', db.Integer, db.ForeignKey('business_service.id'), primary_key=True),
    db.Column('documentation_id', db.Integer, db.ForeignKey('documentation.id'), primary_key=True),
    db.Index('ix_service_documentation_documentation_id', 'documentation_id')
)

# Association table for Service-Policy Many-to-Many
service_policies = db.Table('service_policies',
    db.Column('service_id', db.Integer, db.ForeignKey('business_service.id'), primary_key=True),
    db.Column('policy_id', db.Integer, db.ForeignKey('policy.id'), primary_key=True),
    db.Index('ix_service_policies_policy_id', 'policy_id')
)

# Association table for Service-SecurityActivity Many-to-Many
service_activities = db.Table('service_activities',
    db.Column('service_id', db.Integer, db.ForeignKey('business_service.id'), primary_key=True),
    db.Column('activity_id', db.Integer, db.ForeignKey('security_activity.id'), primary_key=True),
    db.Index('ix_service_activities_activity_id', 'activity_id')
)


class OrganizationSettings(db.Model):
    """Singleton for global organization configuration."""
    __tablename__ = 'organization_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    legal_name = db.Column(db.String(255))           # "OpsDeck S.L."
    tax_id = db.Column(db.String(50))                # CIF/NIF
    primary_domain = db.Column(db.String(255))       # "opsdeck.com"
    logo_filename = db.Column(db.String(255))        # For PDF reports
    email_domains = db.Column(db.String(500))        # Comma-separated: "empresa.com,empresa.es"
    updated_at = db.Column(db.DateTime, default=lambda: now(), onupdate=lambda: now())
    
    def __repr__(self):
        return f'<OrganizationSettings {self.legal_name}>'
    
    @property
    def email_domains_list(self):
        """Returns email_domains as a list."""
        if self.email_domains:
            return [d.strip() for d in self.email_domains.split(',') if d.strip()]
        return []

class CustomFieldDefinition(db.Model):
    __tablename__ = 'custom_field_definition'
    
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(50), nullable=False) # 'User', 'Asset', 'Peripheral'
    label = db.Column(db.String(100), nullable=False)
    name = db.Column(db.String(100), nullable=False) # slug
    field_type = db.Column(db.String(20), nullable=False, default='text') # text, number, date, boolean
    is_required = db.Column(db.Boolean, default=False)
    
    __table_args__ = (
        db.UniqueConstraint('entity_type', 'name', name='uq_entity_field_name'),
    )

class CustomFieldValue(db.Model):
    __tablename__ = 'custom_field_value'
    
    id = db.Column(db.Integer, primary_key=True)
    field_definition_id = db.Column(db.Integer, db.ForeignKey('custom_field_definition.id'), nullable=False, index=True)
    
    linkable_id = db.Column(db.Integer, nullable=False)
    linkable_type = db.Column(db.String(50), nullable=False)
    
    value = db.Column(db.Text)
    
    definition = db.relationship('CustomFieldDefinition', backref='values')
    
    __table_args__ = (
        db.Index('idx_custom_value_linkable', 'linkable_type', 'linkable_id'),
    )

class CustomPropertiesMixin:
    """
    Mixin to add dynamic custom properties to any model.
    Requires the model to define __tablename__ or be able to derive a type name.
    """
    
    @property
    def custom_properties(self):
        """
        Returns a dict of {field_name: value} for this object.
        Optimized to fetch all values reasonably.
        """
        # We need to know our type.
        # Assuming the class name matches entity_type usage (User, Asset, Peripheral)
        my_type = self.__class__.__name__
        
        # Query all definitions for this type
        definitions = CustomFieldDefinition.query.filter_by(entity_type=my_type).all()
        
        # Query existing values for this object
        # We use a fresh query to avoid stallness, but could be optimized with relationship if we added one
        values = CustomFieldValue.query.filter_by(
            linkable_type=my_type,
            linkable_id=self.id
        ).all()
        
        val_map = {v.definition.name: v.value for v in values if v.definition}
        
        # Return all definitions, with None/Empty if value doesn't exist
        props = {}
        for d in definitions:
            props[d.name] = val_map.get(d.name)
            
        return props

    def get_custom_property_object(self, field_name):
        """Helper to get the actual CustomFieldValue object if needed."""
        my_type = self.__class__.__name__
        definition = CustomFieldDefinition.query.filter_by(entity_type=my_type, name=field_name).first()
        if not definition:
            return None
        
        return CustomFieldValue.query.filter_by(
            field_definition_id=definition.id,
            linkable_type=my_type,
            linkable_id=self.id
        ).first()

    def save_custom_properties(self, form_data, prefix='custom_field_'):
        """
        Iterates over form_data and saves values for keys starting with prefix.
        Expects keys like 'custom_field_github_user'.
        """
        my_type = self.__class__.__name__
        with db.session.no_autoflush:
            definitions = CustomFieldDefinition.query.filter_by(entity_type=my_type).all()

            for d in definitions:
                form_key = f"{prefix}{d.name}"
                if form_key in form_data:
                    new_val = form_data.get(form_key)

                    # Check for existing value
                    existing = CustomFieldValue.query.filter_by(
                        field_definition_id=d.id,
                        linkable_type=my_type,
                        linkable_id=self.id
                    ).first()

                    if existing:
                        existing.value = new_val
                    else:
                        cv = CustomFieldValue(
                            field_definition_id=d.id,
                            linkable_type=my_type,
                            linkable_id=self.id,
                            value=new_val
                        )
                        db.session.add(cv)

