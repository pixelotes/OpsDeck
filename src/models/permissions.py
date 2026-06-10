from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC

import enum

class Module(db.Model):
    """
    Represents a logical module/section of the OpsDeck application.
    Used for assigning granular permissions in the future.
    """
    __tablename__ = 'module'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<Module {self.slug}>'

class AccessLevel(enum.Enum):
    READ_ONLY = "READ_ONLY"
    WRITE = "WRITE"

class Permission(db.Model):
    """
    Links a Module to a User or a Group to grant access.
    Can be assigned to either user_id or group_id.
    """
    __tablename__ = 'permission'
    
    id = db.Column(db.Integer, primary_key=True)
    module_id = db.Column(db.Integer, db.ForeignKey('module.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    access_level = db.Column(db.Enum(AccessLevel), nullable=False, default=AccessLevel.WRITE)
    
    # Relationships
    module = db.relationship('Module', backref=db.backref('permissions', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN))
    user = db.relationship('User', backref=db.backref('direct_permissions', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN))
    group = db.relationship('Group', backref=db.backref('permissions', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN))
    
    # Ensure one permission per module/user or module/group
    __table_args__ = (
        db.UniqueConstraint('module_id', 'user_id', name='uq_module_user'),
        db.UniqueConstraint('module_id', 'group_id', name='uq_module_group'),
    )

    def __repr__(self):
        target = f"User:{self.user_id}" if self.user_id else f"Group:{self.group_id}"
        return f'<Permission Module:{self.module_id} -> {target}>'
