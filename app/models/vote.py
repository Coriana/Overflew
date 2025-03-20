from datetime import datetime
from app import db


class Vote(db.Model):
    __tablename__ = 'votes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True)
    vote_type = db.Column(db.Integer, nullable=False)  # 1 for upvote, -1 for downvote
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        # User can only vote once per content
        db.UniqueConstraint('user_id', 'question_id', name='uq_user_question_vote'),
        db.UniqueConstraint('user_id', 'comment_id', name='uq_user_comment_vote'),
    )

    def __init__(self, user_id, question_id=None, comment_id=None, vote_type=1):
        self.user_id = user_id
        self.question_id = question_id
        self.comment_id = comment_id
        self.vote_type = vote_type
        
    def __repr__(self):
        if self.question_id:
            return f'<Vote by User {self.user_id} on Question {self.question_id}>'
        else:
            return f'<Vote by User {self.user_id} on Comment {self.comment_id}>'
