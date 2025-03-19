from datetime import datetime
import markdown
from app import db


class Question(db.Model):
    __tablename__ = 'questions'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    body = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    views = db.Column(db.Integer, default=0)
    is_closed = db.Column(db.Boolean, default=False)
    close_reason = db.Column(db.String(120))

    # Relationships
    answers = db.relationship('Answer', backref='question', lazy='dynamic', cascade='all, delete-orphan')
    comments = db.relationship('Comment', backref='question', lazy='dynamic', cascade='all, delete-orphan')
    tags = db.relationship('QuestionTag', backref='question', lazy='dynamic', cascade='all, delete-orphan')
    votes = db.relationship('Vote', backref='question', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def score(self):
        """Calculate the score based on upvotes and downvotes"""
        upvotes = sum(1 for vote in self.votes if vote.vote_type == 1)
        downvotes = sum(1 for vote in self.votes if vote.vote_type == -1)
        return upvotes - downvotes
        
    @property
    def body_html(self):
        """Convert markdown to HTML for display"""
        return markdown.markdown(self.body, extensions=['extra', 'codehilite'])

    @property
    def html_content(self):
        """Convert markdown to HTML for display"""
        return markdown.markdown(self.body, extensions=['fenced_code', 'codehilite'])

    def increment_view(self):
        """Increment the view count of the question"""
        self.views += 1
        db.session.commit()

    def __repr__(self):
        return f'<Question {self.title}>'
