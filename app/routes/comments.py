from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, abort
from flask_login import login_required, current_user
from app import db
from app.models.comment import Comment
from app.models.question import Question
from app.models.vote import Vote
from app.models.user import User
from datetime import datetime, timedelta

comments_bp = Blueprint('comments', __name__, url_prefix='/comments')


@comments_bp.route('/add', methods=['POST'])
@login_required
def add():
    """
    Add a new comment to any content (question, comment, etc.)
    """
    body = request.form.get('body')
    content_type = request.form.get('content_type')
    content_id = request.form.get('content_id')
    parent_comment_id = request.form.get('parent_comment_id')
    
    if not body:
        flash('Content cannot be empty', 'danger')
        return redirect(url_for('questions.view', question_id=content_id if content_type == 'question' else Comment.query.get(content_id).question_id))
    
    # Determine question_id based on content_type
    question_id = None
    if content_type == 'question':
        question_id = content_id
    elif content_type == 'comment':
        parent_comment = Comment.query.get_or_404(content_id)
        question_id = parent_comment.question_id
        parent_comment_id = content_id  # Set the parent_comment_id to the content_id
    
    # Create the comment with appropriate parent relationship
    comment = Comment(
        body=body,
        user_id=current_user.id,
        question_id=question_id,
        parent_comment_id=parent_comment_id if parent_comment_id else None
    )
    
    db.session.add(comment)
    db.session.commit()
    
    flash('Your comment has been posted!', 'success')
    return redirect(url_for('questions.view', question_id=question_id))


@comments_bp.route('/<int:comment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(comment_id):
    """Edit an existing comment"""
    comment = Comment.query.get_or_404(comment_id)
    
    # Check if the user is authorized to edit the comment
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)  # Forbidden
    
    if request.method == 'POST':
        body = request.form.get('body')
        
        if not body:
            flash('Content cannot be empty', 'danger')
        else:
            comment.body = body
            db.session.commit()
            flash('Your content has been updated', 'success')
        
        return redirect(url_for('questions.view', question_id=comment.question_id))
    
    return render_template('comments/edit.html', comment=comment)


@comments_bp.route('/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete(comment_id):
    """Soft delete a comment"""
    comment = Comment.query.get_or_404(comment_id)
    
    # Check if the user is authorized to delete the comment
    if comment.user_id != current_user.id and not current_user.is_admin:
        abort(403)  # Forbidden
    
    # Soft delete the comment instead of hard deleting
    comment.is_deleted = True
    db.session.commit()
    
    flash('Content deleted', 'success')
    return redirect(url_for('questions.view', question_id=comment.question_id))


@comments_bp.route('/<int:comment_id>/accept', methods=['POST'])
@login_required
def accept(comment_id):
    """Accept an answer (top-level comment with no parent)"""
    comment = Comment.query.get_or_404(comment_id)
    question = Question.query.get_or_404(comment.question_id)
    
    # Check if the user is authorized to accept the answer
    if question.user_id != current_user.id:
        abort(403)  # Forbidden
    
    # Check if this is a top-level comment (an answer)
    if comment.parent_comment_id is not None:
        flash('Only answers can be accepted', 'danger')
        return redirect(url_for('questions.view', question_id=comment.question_id))
    
    # Clear any previously accepted answers for this question
    previously_accepted = Comment.query.filter_by(
        question_id=comment.question_id,
        is_accepted=True
    ).all()
    
    for prev in previously_accepted:
        prev.is_accepted = False
    
    # Mark this answer as accepted
    comment.is_accepted = True
    db.session.commit()
    
    flash('Answer accepted', 'success')
    return redirect(url_for('questions.view', question_id=comment.question_id))


@comments_bp.route('/<int:comment_id>/vote', methods=['POST'])
@login_required
def vote(comment_id):
    """Vote on a comment or answer"""
    comment = Comment.query.get_or_404(comment_id)
    vote_type = int(request.form.get('vote_type', 0))
    
    if vote_type not in [-1, 0, 1]:
        abort(400)  # Bad request
    
    # Check if the user has already voted
    existing_vote = Vote.query.filter_by(
        user_id=current_user.id,
        comment_id=comment_id
    ).first()
    
    if existing_vote:
        if vote_type == 0:
            # Remove the vote
            db.session.delete(existing_vote)
        else:
            # Update the vote
            existing_vote.vote_type = vote_type
    elif vote_type != 0:
        # Create a new vote
        vote = Vote(
            user_id=current_user.id,
            comment_id=comment_id,
            vote_type=vote_type
        )
        db.session.add(vote)
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'score': comment.score,
        'user_vote': vote_type if vote else 0
    })
