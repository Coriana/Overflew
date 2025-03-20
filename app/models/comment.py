from datetime import datetime
import markdown
from app import db


class Comment(db.Model):
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True)
    answer_id = db.Column(db.Integer, db.ForeignKey('answers.id'), nullable=True)  # Temporary field for migration
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)
    is_accepted = db.Column(db.Boolean, default=False)  # True if this comment is accepted by the question author

    # Relationships
    votes = db.relationship('Vote', backref='comment', lazy='dynamic', cascade='all, delete-orphan')
    replies = db.relationship('Comment', backref=db.backref('parent_comment', remote_side=[id]), 
                             lazy='dynamic')
    # The User model defines the relationship with backref='author', so we need to access it that way
    # The Question model defines the relationship with backref='question', so no need to define it here

    def __init__(self, body, user_id, question_id=None, parent_comment_id=None, answer_id=None):
        self.body = body
        self.user_id = user_id
        self.question_id = question_id
        self.parent_comment_id = parent_comment_id
        self.answer_id = answer_id
        self.is_deleted = False
        self.is_accepted = False

    @property
    def score(self):
        """Calculate the score based on upvotes and downvotes"""
        upvotes = sum(1 for vote in self.votes if vote.vote_type == 1)
        downvotes = sum(1 for vote in self.votes if vote.vote_type == -1)
        return upvotes - downvotes

    @property
    def html_content(self):
        """Convert markdown to HTML for display"""
        if self.is_deleted:
            return "<em>[This content has been deleted]</em>"
        return markdown.markdown(self.body, extensions=['fenced_code', 'codehilite'])
    
    @property
    def is_answer(self):
        """A comment is an answer if it's a top-level comment (no parent)"""
        return self.parent_comment_id is None

    def soft_delete(self):
        """Marks the comment as deleted without removing it from the database"""
        self.is_deleted = True
        self.body = "[deleted]"
        db.session.commit()

    def __repr__(self):
        if self.parent_comment_id is None:
            return f'<Answer {self.id} for Question {self.question_id}>'
        else:
            return f'<Comment {self.id} replying to {self.parent_comment_id}>'
