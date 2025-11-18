from datetime import datetime
from sqlalchemy import and_
from sqlalchemy.orm import foreign
from ..extensions import db

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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

documentation_tags = db.Table('documentation_tags',
    db.Column('documentation_id', db.Integer, db.ForeignKey('documentation.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class Documentation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    external_link = db.Column(db.String(512)) # Enlace externo
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Propietario polimórfico (User o Group)
    owner_id = db.Column(db.Integer)
    owner_type = db.Column(db.String(50)) # 'User' o 'Group'
    
    # Relación con Software (opcional)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True)
    software = db.relationship('Software', backref='documentation')

    # Relación con Tags (muchos a muchos)
    tags = db.relationship('Tag', secondary=documentation_tags, backref=db.backref('documentation', lazy='dynamic'))
    
    # Relación con Attachments (polimórfica)
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(Documentation.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='Documentation')",
                            lazy=True, cascade='all, delete-orphan')

    @property
    def owner(self):
        """Devuelve el objeto User o Group basado en owner_type y owner_id."""
        from .auth import User, Group
        if self.owner_type == 'User' and self.owner_id:
            return User.query.get(self.owner_id)
        if self.owner_type == 'Group' and self.owner_id:
            return Group.query.get(self.owner_id)
        return None
