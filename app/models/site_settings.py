from app import db
from datetime import datetime

class SiteSettings(db.Model):
    __tablename__ = 'site_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    @classmethod
    def get(cls, key, default=None):
        """Get a setting value by key"""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            # Convert to appropriate type
            if setting.value.isdigit():
                return int(setting.value)
            elif setting.value.lower() in ('true', 'false'):
                return setting.value.lower() == 'true'
            else:
                return setting.value
        return default
    
    @classmethod
    def set(cls, key, value, description=None):
        """Set a setting value by key"""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = str(value)
            if description:
                setting.description = description
        else:
            setting = cls(key=key, value=str(value), description=description)
            db.session.add(setting)
        db.session.commit()
        return setting
    
    @classmethod
    def init_settings(cls):
        """Initialize default settings if they don't exist"""
        default_settings = {
            'ai_auto_populate_enabled': ('false', 'Enable automatic AI population of threads'),
            'ai_auto_populate_max_comments': ('150', 'Maximum number of AI comments per thread'),
            'ai_auto_populate_personalities': ('7', 'Number of AI personalities to involve per question')
        }
        
        for key, (value, description) in default_settings.items():
            setting = cls.query.filter_by(key=key).first()
            if not setting:
                setting = cls(key=key, value=value, description=description)
                db.session.add(setting)
        
        db.session.commit()
        
    def __repr__(self):
        return f'<SiteSettings {self.key}={self.value}>'
