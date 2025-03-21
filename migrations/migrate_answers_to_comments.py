"""
Migration script to convert the existing Answers to top-level Comments 
in our new unified comment system.
"""

from app import create_app, db
from app.models.question import Question
from app.models.answer import Answer
from app.models.comment import Comment
from app.models.vote import Vote
from app.models.user import User
from flask_migrate import Migrate
import sys

def migrate_answers_to_comments():
    # Create application context
    app = create_app()
    with app.app_context():
        print("Starting migration of Answers to Comments...")
        
        # Get all existing answers
        answers = Answer.query.all()
        print(f"Found {len(answers)} answers to migrate")
        
        # Track mapping of answer IDs to new comment IDs
        answer_to_comment_map = {}
        
        # For each answer, create a new top-level Comment
        for answer in answers:
            # Create a new comment from the answer
            new_comment = Comment(
                body=answer.body,
                user_id=answer.user_id,
                question_id=answer.question_id,
                parent_comment_id=None,  # No parent = top-level comment (answer)
                created_at=answer.created_at,
                updated_at=answer.updated_at,
                is_deleted=answer.is_deleted if hasattr(answer, 'is_deleted') else False,
                is_accepted=answer.is_accepted if hasattr(answer, 'is_accepted') else False
            )
            
            # Add the new comment to the session
            db.session.add(new_comment)
            print(f"Migrating Answer ID {answer.id} to a top-level Comment")
            
            # Commit to get the new comment ID
            db.session.commit()
            
            # Store the mapping for later use
            answer_to_comment_map[answer.id] = new_comment.id
            
            # Migrate any votes for this answer
            votes = Vote.query.filter_by(answer_id=answer.id).all()
            for vote in votes:
                vote.comment_id = new_comment.id
                vote.answer_id = None
                print(f"Migrated Vote ID {vote.id} from Answer to Comment")
            
            # Migrate any comments on this answer to be replies to the new comment
            answer_comments = Comment.query.filter_by(answer_id=answer.id).all()
            for comment in answer_comments:
                comment.parent_comment_id = new_comment.id
                comment.answer_id = None
                print(f"Migrated Comment ID {comment.id} to be a reply to the new Comment ID {new_comment.id}")
                
            # Update user reputation to account for votes on this answer
            if answer.user and hasattr(answer, 'score'):
                user = User.query.get(answer.user_id)
                if user:
                    # Calculate reputation from votes on the answer
                    score = answer.score
                    # 10 points per upvote for answers
                    user_rep_change = score * 10
                    print(f"Adjusting user {user.username} reputation by {user_rep_change} points")
                    user.reputation += user_rep_change
        
        # Commit all remaining changes
        db.session.commit()
        print("Migration complete.")

        # Verify migration results
        top_level_comments = Comment.query.filter_by(parent_comment_id=None).count()
        print(f"Total top-level comments after migration: {top_level_comments}")
        
if __name__ == "__main__":
    migrate_answers_to_comments()
