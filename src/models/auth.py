from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import foreign
from sqlalchemy import and_
from ..extensions import db
from .core import Attachment

user_groups = db.Table('user_groups',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True)
)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    users = db.relationship('User', secondary=user_groups, back_populates='groups')
    policy_versions_to_acknowledge = db.relationship('PolicyVersion', secondary='policy_version_groups', back_populates='groups_to_acknowledge')

class User(db.Model): # Add UserMixin here if using Flask-Login
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False) # Make email unique and required for login
    password_hash = db.Column(db.String(120)) # Can be nullable for users who don't log in
    role = db.Column(db.String(50), default='user') # e.g., 'user', 'editor', 'admin'
    department = db.Column(db.String(100))
    job_title = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    assets = db.relationship('Asset', backref='user', lazy=True)
    peripherals = db.relationship('Peripheral', backref='user', lazy=True)
    licenses = db.relationship('License', backref='user', lazy=True)
    
    is_archived = db.Column(db.Boolean, default=False, nullable=False)
    
    acknowledgements = db.relationship('PolicyAcknowledgement', backref='user', lazy=True, cascade='all, delete-orphan')
    
    groups = db.relationship('Group', secondary=user_groups, back_populates='users')
    
    policy_versions_to_acknowledge = db.relationship('PolicyVersion', secondary='policy_version_users', back_populates='users_to_acknowledge')
    
    course_assignments = db.relationship('CourseAssignment', backref='user', lazy=True, cascade='all, delete-orphan')
    
    attachments = db.relationship('Attachment',
                            primaryjoin="and_(User.id==foreign(Attachment.linkable_id), "
                                        "Attachment.linkable_type=='User')",
                            lazy=True, cascade='all, delete-orphan')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        # Only check password if one is set
        if self.password_hash:
            return check_password_hash(self.password_hash, password)
        return False
