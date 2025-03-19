from app import db


class Tag(db.Model):
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.Text)
    
    # Relationships
    questions = db.relationship('QuestionTag', backref='tag', lazy='dynamic')

    def __repr__(self):
        return f'<Tag {self.name}>'


class QuestionTag(db.Model):
    __tablename__ = 'question_tags'

    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('question_id', 'tag_id', name='uq_question_tag'),
    )

    def __repr__(self):
        return f'<QuestionTag {self.question_id}:{self.tag_id}>'
