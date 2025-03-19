from datetime import datetime
from app import db


class Vote(db.Model):
    __tablename__ = 'votes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=True)
    answer_id = db.Column(db.Integer, db.ForeignKey('answers.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True)
    vote_type = db.Column(db.Integer, nullable=False)  # 1 for upvote, -1 for downvote
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        # User can only vote once per content
        db.UniqueConstraint('user_id', 'question_id', name='uq_user_question_vote'),
        db.UniqueConstraint('user_id', 'answer_id', name='uq_user_answer_vote'),
        db.UniqueConstraint('user_id', 'comment_id', name='uq_user_comment_vote'),
    )

    def __repr__(self):
        if self.question_id:
            return f'<Vote by User {self.user_id} on Question {self.question_id}>'
        elif self.answer_id:
            return f'<Vote by User {self.user_id} on Answer {self.answer_id}>'
        else:
            return f'<Vote by User {self.user_id} on Comment {self.comment_id}>'
