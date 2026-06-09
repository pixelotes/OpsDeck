from datetime import datetime
from src.utils.timezone_helper import now
from ..extensions import db
from .constants import CASCADE_ALL_DELETE_ORPHAN, LAZY_DYNAMIC

class Configuration(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    
    # Ownership (Polymorphic-like)
    owner_id = db.Column(db.Integer)
    owner_type = db.Column(db.String(50)) # 'User' or 'Group'
    
    # Links to other assets (Nullable FKs)
    service_id = db.Column(db.Integer, db.ForeignKey('business_service.id'), nullable=True)
    software_id = db.Column(db.Integer, db.ForeignKey('software.id'), nullable=True)
    license_id = db.Column(db.Integer, db.ForeignKey('license.id'), nullable=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'), nullable=True)
    
    # Relationships
    versions = db.relationship('ConfigurationVersion', backref='configuration', lazy=LAZY_DYNAMIC, cascade=CASCADE_ALL_DELETE_ORPHAN)
    
    @property
    def latest_version(self):
        return self.versions.order_by(ConfigurationVersion.version_number.desc()).first()

    def get_tickets(self):
        """
        Aggregates all related tickets:
        - Changes
        Returns a sorted list (by date desc) of dicts.
        """
        tickets = []
        
        # 1. Changes
        for change in self.changes:
            tickets.append({
                'type': 'Change',
                'category': change.change_type,
                'title': change.title,
                'status': change.status,
                'date': change.created_at,
                'url': f"/changes/{change.id}",
                'tags': [t.name for t in change.tags],
                'id': change.id,
                'assignee': change.assignee.name if change.assignee else None
            })
        
        # Also include changes linked to versions?
        # The requirement says: "For CMBD, the list should be shown at the container level, not in the individual versions."
        # This implies we should aggregate changes from versions too?
        # "The list should be shown at the container level, not in the individual versions."
        # Use case: I want to see all changes affecting this config, regardless of version.
        
        for version in self.versions:
            for change in version.changes:
                # Avoid duplicates if change is linked to both (unlikely but possible)
                if not any(t['id'] == change.id for t in tickets):
                    tickets.append({
                        'type': 'Change',
                        'category': change.change_type,
                        'title': change.title,
                        'status': change.status,
                        'date': change.created_at,
                        'url': f"/changes/{change.id}",
                        'tags': [t.name for t in change.tags],
                        'id': change.id,
                        'assignee': change.assignee.name if change.assignee else None
                    })
            
        # Sort by date descending
        tickets.sort(key=lambda x: x['date'], reverse=True)
        return tickets

class ConfigurationVersion(db.Model):

    id = db.Column(db.Integer, primary_key=True)
    configuration_id = db.Column(db.Integer, db.ForeignKey('configuration.id'), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)
    data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: now())
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    commit_message = db.Column(db.String(255))
    
    created_by = db.relationship('User')
