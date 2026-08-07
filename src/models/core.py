from src.utils.timezone_helper import now
from sqlalchemy import and_
from sqlalchemy.orm import foreign
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC
from ..services.risk_scale import (DEFAULT_CRITICAL_FROM as RISK_DEFAULT_CRITICAL,
                                   DEFAULT_HIGH_FROM as RISK_DEFAULT_HIGH,
                                   DEFAULT_LEVELS as RISK_DEFAULT_LEVELS,
                                   DEFAULT_MEDIUM_FROM as RISK_DEFAULT_MEDIUM)

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

    # Size of the risk matrix new assessments are scored against. Rectangular is allowed:
    # more granularity on impact than on likelihood is a normal way to run this.
    #
    # Changing these does not touch existing risks — each one records the matrix it was
    # scored on, so a change applies to what is assessed from then on. See
    # services/risk_scale.py.
    risk_impact_levels = db.Column(db.Integer, default=RISK_DEFAULT_LEVELS,
                                   nullable=False,
                                   server_default=str(RISK_DEFAULT_LEVELS))
    risk_likelihood_levels = db.Column(db.Integer, default=RISK_DEFAULT_LEVELS,
                                       nullable=False,
                                       server_default=str(RISK_DEFAULT_LEVELS))

    # Risk appetite: where green becomes amber and amber becomes red, as percentages of
    # the maximum score on whatever matrix a risk was assessed with.
    #
    # Unlike the matrix size, this is NOT stamped per risk and applies immediately to
    # everything already in the register. The size is how you measured, and rewriting it
    # would falsify old assessments; the appetite is what you are prepared to tolerate
    # today, and re-judging the register against it is the reason to change it.
    risk_appetite_medium_from = db.Column(db.Integer, default=RISK_DEFAULT_MEDIUM,
                                          nullable=False,
                                          server_default=str(RISK_DEFAULT_MEDIUM))
    risk_appetite_high_from = db.Column(db.Integer, default=RISK_DEFAULT_HIGH,
                                        nullable=False,
                                        server_default=str(RISK_DEFAULT_HIGH))
    risk_appetite_critical_from = db.Column(db.Integer, default=RISK_DEFAULT_CRITICAL,
                                            nullable=False,
                                            server_default=str(RISK_DEFAULT_CRITICAL))

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

#: Ids per IN clause when preloading. SQLite caps bound parameters (999 on the builds
#: this runs against in tests), and a UAR export can span every user in the database.
_PRELOAD_CHUNK = 500


class CustomPropertiesMixin:
    """
    Mixin to add dynamic custom properties to any model.
    Requires the model to define __tablename__ or be able to derive a type name.
    """

    #: Cache attribute name. Not a mapped column, so SQLAlchemy leaves it alone —
    #: including on commit, which is why the writer below has to clear it explicitly.
    _CACHE_ATTR = '_custom_properties_cache'

    @property
    def custom_properties(self):
        """
        Returns a dict of {field_name: value} for this object.

        Memoised per instance. Every template that renders custom fields does
        ``custom_properties.get(field.name)`` inside a loop over the definitions, so
        without this the two queries below run once per field: an asset with eight
        custom fields cost sixteen queries to display them. Instances live for one
        request, so the cache does too.

        Use preload_custom_properties for a list of objects — this still costs two
        queries the first time it is touched on each one.
        """
        cached = getattr(self, self._CACHE_ATTR, None)
        if cached is not None:
            return cached

        my_type = self.__class__.__name__
        definitions = CustomFieldDefinition.query.filter_by(entity_type=my_type).all()
        values = CustomFieldValue.query.filter_by(
            linkable_type=my_type,
            linkable_id=self.id
        ).all()

        # Keyed off field_definition_id rather than value.definition.name: traversing the
        # relationship lazy-loads each definition one at a time whenever the identity map
        # does not already hold it.
        names_by_id = {d.id: d.name for d in definitions}
        val_map = {}
        for value in values:
            name = names_by_id.get(value.field_definition_id)
            if name is not None:
                val_map[name] = value.value

        props = {d.name: val_map.get(d.name) for d in definitions}
        setattr(self, self._CACHE_ATTR, props)
        return props

    @classmethod
    def preload_custom_properties(cls, instances):
        """Fill the cache for many objects in two queries, not two per object.

        For the loops that read custom properties across a whole collection — the UAR
        user export reads them for every user in the database — the per-instance cache
        does not help, because each instance is touched once.
        """
        instances = [i for i in instances if i is not None and i.id is not None]
        if not instances:
            return

        my_type = cls.__name__
        definitions = CustomFieldDefinition.query.filter_by(entity_type=my_type).all()
        names_by_id = {d.id: d.name for d in definitions}
        field_names = [d.name for d in definitions]

        ids = [i.id for i in instances]
        grouped = {}
        for start in range(0, len(ids), _PRELOAD_CHUNK):
            chunk = ids[start:start + _PRELOAD_CHUNK]
            rows = CustomFieldValue.query.filter(
                CustomFieldValue.linkable_type == my_type,
                CustomFieldValue.linkable_id.in_(chunk)
            ).all()
            for row in rows:
                name = names_by_id.get(row.field_definition_id)
                if name is not None:
                    grouped.setdefault(row.linkable_id, {})[name] = row.value

        for instance in instances:
            values = grouped.get(instance.id, {})
            setattr(instance, cls._CACHE_ATTR,
                    {name: values.get(name) for name in field_names})

    def invalidate_custom_properties(self):
        """Drop the memoised dict, so the next read reflects what was just written."""
        if hasattr(self, self._CACHE_ATTR):
            delattr(self, self._CACHE_ATTR)

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

            # All of this object's existing values up front. This was one SELECT per
            # definition present in the form, which on the asset form meant a query per
            # custom field on every save.
            existing_by_def = {
                value.field_definition_id: value
                for value in CustomFieldValue.query.filter_by(
                    linkable_type=my_type,
                    linkable_id=self.id
                ).all()
            }

            for d in definitions:
                form_key = f"{prefix}{d.name}"
                if form_key in form_data:
                    new_val = form_data.get(form_key)

                    existing = existing_by_def.get(d.id)
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

        # The memoised dict predates these writes, and nothing else clears it: the
        # attribute is not mapped, so a commit does not expire it.
        self.invalidate_custom_properties()

