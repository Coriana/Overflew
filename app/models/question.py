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
    is_deleted = db.Column(db.Boolean, default=False)
    is_answered = db.Column(db.Boolean, default=False)

    # Relationships
    # Note: No user relationship here as it's defined in the User model with backref='author'
    comments = db.relationship('Comment', backref='question', lazy='dynamic',
                              primaryjoin="Comment.question_id==Question.id")
    tags = db.relationship('QuestionTag', backref='question', lazy='dynamic', cascade='all, delete-orphan')
    votes = db.relationship('Vote', backref='question', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def answers(self):
        """Get all top-level comments (answers) for this question"""
        from app.models.comment import Comment
        return Comment.query.filter_by(
            question_id=self.id,
            parent_comment_id=None
        )
    
    # Since answers and top-level comments are now the same thing in our model,
    # we don't need a separate top_comments property

    @property
    def score(self):
        """Calculate the score based on upvotes and downvotes"""
        upvotes = sum(1 for vote in self.votes if vote.vote_type == 1)
        downvotes = sum(1 for vote in self.votes if vote.vote_type == -1)
        return upvotes - downvotes
        
    @property
    def body_html(self):
        """Convert markdown to HTML for display"""
        if self.is_deleted:
            return "<em>[This question has been deleted]</em>"
        return markdown.markdown(self.body, extensions=['extra', 'codehilite'])
    
    @property
    def answer_count(self):
        """Get the number of answers (top-level comments) for this question"""
        return self.answers.count()
    
    def increment_view(self):
        """Increment the view count for this question"""
        self.views += 1
        db.session.commit()
        
    def soft_delete(self):
        """Marks the question as deleted without removing it from the database"""
        self.is_deleted = True
        self.body = "[deleted]"
        self.title = "[deleted]"
        db.session.commit()

    def __repr__(self):
        if self.is_deleted:
            return f'<Question {self.id} [deleted]>'
        return f'<Question {self.title}>'
