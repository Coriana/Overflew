from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.question import Question
from app.models.comment import Comment
from app.models.vote import Vote
from app.models.user import User
from app.models.ai_personality import AIPersonality
from app.services.llm_service import get_completion, queue_task
import os
import random
from datetime import datetime

# This blueprint is now just a legacy handler that redirects to the appropriate comment routes
answers_bp = Blueprint('answers', __name__, url_prefix='/answers')


@answers_bp.route('/post/<int:question_id>', methods=['POST'])
@login_required
def post(question_id):
    """Creates a new top-level comment (answer) for the question"""
    question = Question.query.get_or_404(question_id)
    answer_body = request.form.get('answer_body')
    
    if not answer_body:
        flash('Answer cannot be empty', 'danger')
        return redirect(url_for('questions.view', question_id=question_id))
    
    # Create a top-level comment instead of an answer
    comment = Comment(
        body=answer_body,
        user_id=current_user.id,
        question_id=question_id,
        parent_comment_id=None  # No parent = top-level comment (answer)
    )
    
    db.session.add(comment)
    db.session.commit()
    
    # Trigger AI responses to the new comment
    from app.routes.questions import ai_respond_to_comment
    ai_respond_to_comment(comment.id)
    
    flash('Your answer has been posted', 'success')
    return redirect(url_for('questions.view', question_id=question_id))


@answers_bp.route('/<int:answer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(answer_id):
    """Edit a top-level comment (formerly an answer)"""
    # Find the comment
    comment = Comment.query.get_or_404(answer_id)
    
    # Check if user is authorized
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    if request.method == 'POST':
        comment_body = request.form.get('body')
        
        if not comment_body:
            flash('Answer cannot be empty', 'danger')
            return redirect(url_for('questions.view', question_id=comment.question_id))
        
        comment.body = comment_body
        comment.updated_at = datetime.utcnow()
        db.session.commit()
        
        flash('Your answer has been updated', 'success')
        return redirect(url_for('questions.view', question_id=comment.question_id))
    
    return render_template('answers/edit.html', answer=comment)


@answers_bp.route('/<int:answer_id>/delete', methods=['POST'])
@login_required
def delete(answer_id):
    """Soft delete a top-level comment (answer)"""
    comment = Comment.query.get_or_404(answer_id)
    
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    comment.soft_delete()
    
    flash('Your answer has been deleted', 'success')
    return redirect(url_for('questions.view', question_id=comment.question_id))


@answers_bp.route('/<int:answer_id>/accept', methods=['POST'])
@login_required
def accept(answer_id):
    """Mark a top-level comment as the accepted answer to a question"""
    # Find the comment to be accepted
    comment = Comment.query.get_or_404(answer_id)
    question = Question.query.get_or_404(comment.question_id)
    
    # Check if user is authorized (must be the question author)
    if question.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    # Clear any previously accepted answers
    previously_accepted = Comment.query.filter_by(
        question_id=question.id,
        is_accepted=True
    ).all()
    
    for prev in previously_accepted:
        prev.is_accepted = False
    
    # Accept this answer
    comment.is_accepted = True
    db.session.commit()
    
    # Award reputation points to the answer author
    answerer = User.query.get(comment.user_id)
    if answerer:
        answerer.reputation += 15
        db.session.commit()
    
    flash('Answer accepted', 'success')
    return redirect(url_for('questions.view', question_id=question.id))


@answers_bp.route('/<int:answer_id>/vote', methods=['POST'])
@login_required
def vote(answer_id):
    """Vote on a top-level comment (answer)"""
    comment = Comment.query.get_or_404(answer_id)
    vote_type = int(request.form.get('vote_type', 0))
    
    if vote_type not in [-1, 0, 1]:
        abort(400)
    
    # Look for an existing vote
    existing_vote = Vote.query.filter_by(
        user_id=current_user.id, comment_id=answer_id
    ).first()
    
    if vote_type == 0 and existing_vote:
        # Remove vote
        db.session.delete(existing_vote)
    elif existing_vote:
        # Update vote
        existing_vote.vote_type = vote_type
    else:
        # Create new vote
        new_vote = Vote(
            user_id=current_user.id,
            comment_id=answer_id,
            vote_type=vote_type
        )
        db.session.add(new_vote)
    
    db.session.commit()
    
    # Redirect to the question page
    return redirect(url_for('questions.view', question_id=comment.question_id))


@answers_bp.route('/<int:answer_id>/comments/add', methods=['POST'])
@login_required
def add_comment(answer_id):
    """Add a reply to a top-level comment (answer)"""
    parent_comment = Comment.query.get_or_404(answer_id)
    comment_body = request.form.get('comment_body')
    
    if not comment_body:
        flash('Comment cannot be empty', 'danger')
        return redirect(url_for('questions.view', question_id=parent_comment.question_id))
    
    # Create a reply to the parent comment
    comment = Comment(
        body=comment_body,
        user_id=current_user.id,
        question_id=parent_comment.question_id,
        parent_comment_id=parent_comment.id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    # Trigger AI responses to the comment asynchronously
    from app.routes.questions import ai_respond_to_comment
    ai_respond_to_comment(comment.id)
    
    flash('Your comment has been added', 'success')
    return redirect(url_for('questions.view', question_id=parent_comment.question_id))
