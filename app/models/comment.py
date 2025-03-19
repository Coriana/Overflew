from datetime import datetime
import markdown
from app import db


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=True)
    answer_id = db.Column(db.Integer, db.ForeignKey('answers.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    votes = db.relationship('Vote', backref='comment', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def score(self):
        """Calculate the score based on upvotes and downvotes"""
        upvotes = sum(1 for vote in self.votes if vote.vote_type == 1)
        downvotes = sum(1 for vote in self.votes if vote.vote_type == -1)
        return upvotes - downvotes

    @property
    def html_content(self):
        """Convert markdown to HTML for display"""
        return markdown.markdown(self.body, extensions=['fenced_code', 'codehilite'])

    def __repr__(self):
        if self.question_id:
            return f'<Comment {self.id} for Question {self.question_id}>'
        else:
            return f'<Comment {self.id} for Answer {self.answer_id}>'
