from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    reputation = db.Column(db.Integer, default=0)
    about_me = db.Column(db.Text)
    profile_image = db.Column(db.String(256))
    is_admin = db.Column(db.Boolean, default=False)
    is_ai = db.Column(db.Boolean, default=False)
    ai_personality_id = db.Column(db.Integer, db.ForeignKey('ai_personalities.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    questions = db.relationship('Question', backref='author', lazy='dynamic')
    answers = db.relationship('Answer', backref='author', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    votes = db.relationship('Vote', backref='user', lazy='dynamic')
    ai_personality = db.relationship('AIPersonality', backref='users', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def update_reputation(self, points):
        self.reputation += points
        db.session.commit()

    def __repr__(self):
        return f'<User {self.username}>'
