from datetime import datetime
import markdown
from app import db


class Answer(db.Model):
    __tablename__ = 'answers'

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_accepted = db.Column(db.Boolean, default=False)

    # Relationships
    comments = db.relationship('Comment', backref='answer', lazy='dynamic', cascade='all, delete-orphan')
    votes = db.relationship('Vote', backref='answer', lazy='dynamic', cascade='all, delete-orphan')

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

    def accept(self):
        """Mark this answer as accepted"""
        # First unaccept any previously accepted answers
        for answer in self.question.answers:
            if answer.is_accepted:
                answer.is_accepted = False
        
        # Then accept this answer
        self.is_accepted = True
        db.session.commit()

    def __repr__(self):
        return f'<Answer {self.id} for Question {self.question_id}>'
