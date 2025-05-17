from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models.question import Question
from app.models.comment import Comment
from app.models.tag import Tag, QuestionTag
from app.models.vote import Vote
from app.models.user import User

questions_bp = Blueprint('questions', __name__, url_prefix='/questions')


@questions_bp.route('/ask', methods=['GET', 'POST'])
@login_required
def ask():
    if request.method == 'POST':
        title = request.form.get('title')
        body = request.form.get('body')
        tags_string = request.form.get('tags')
        
        # Validate input
        if not title or not body:
            flash('Title and body are required', 'danger')
            return render_template('questions/ask.html')
        
        # Create new question
        question = Question(title=title, body=body, user_id=current_user.id)
        db.session.add(question)
        db.session.flush()  # This gives us the question ID
        
        # Process tags
        if tags_string:
            tags = [tag.strip() for tag in tags_string.split(',')]
            for tag_name in tags:
                # Check if tag exists, create if not
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                    db.session.flush()
                
                # Create question-tag association
                question_tag = QuestionTag(question_id=question.id, tag_id=tag.id)
                db.session.add(question_tag)
        
        db.session.commit()
        
        flash('Your question has been posted.', 'success')
        return redirect(url_for('questions.view', question_id=question.id))
    
    return render_template('questions/ask.html')


@questions_bp.route('/<int:question_id>')
def view(question_id):
    question = Question.query.get_or_404(question_id)
    question.increment_view()  # Increment view count
    
    # Get all top-level comments (both answers and comments) for this question
    top_level_comments = Comment.query.filter_by(
        question_id=question_id, 
        parent_comment_id=None
    ).all()
    
    # Attach user vote information to question and comments if user is logged in
    if current_user.is_authenticated:
        # Get user's vote on the question if any
        question_vote = Vote.query.filter_by(
            user_id=current_user.id,
            question_id=question_id,
            comment_id=None
        ).first()
        question.user_vote = question_vote.vote_type if question_vote else 0
        
        # Get all comment IDs for this question to fetch votes in a single query
        comment_ids = []
        
        def collect_comment_ids(comments):
            for comment in comments:
                comment_ids.append(comment.id)
                if comment.replies:
                    collect_comment_ids(comment.replies.all())
        
        collect_comment_ids(top_level_comments)
        
        # Fetch all votes by this user for these comments in a single query
        if comment_ids:
            comment_votes = Vote.query.filter(
                Vote.user_id == current_user.id,
                Vote.comment_id.in_(comment_ids)
            ).all()
            
            # Create a mapping of comment_id to vote_type
            vote_map = {vote.comment_id: vote.vote_type for vote in comment_votes}
            
            # Attach vote information to each comment
            def attach_vote_info(comments):
                for comment in comments:
                    comment.user_vote = vote_map.get(comment.id, 0)
                    if comment.replies:
                        attach_vote_info(comment.replies.all())
            
            attach_vote_info(top_level_comments)
    
    return render_template('questions/view.html', 
                         question=question, 
                         comments=top_level_comments)


@questions_bp.route('/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(question_id):
    question = Question.query.get_or_404(question_id)
    
    # Check if user is author or admin
    if question.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    if request.method == 'POST':
        title = request.form.get('title')
        body = request.form.get('body')
        tags_string = request.form.get('tags')
        
        # Validate input
        if not title or not body:
            flash('Title and body are required', 'danger')
            return render_template('questions/edit.html', question=question)
        
        # Update question
        question.title = title
        question.body = body
        question.updated_at = datetime.utcnow()
        
        # Update tags
        if tags_string:
            # Remove existing tags
            QuestionTag.query.filter_by(question_id=question_id).delete()
            
            # Add new tags
            tags = [tag.strip() for tag in tags_string.split(',')]
            for tag_name in tags:
                tag = Tag.query.filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    db.session.add(tag)
                    db.session.flush()
                
                question_tag = QuestionTag(question_id=question.id, tag_id=tag.id)
                db.session.add(question_tag)
        
        db.session.commit()
        flash('Question updated successfully.', 'success')
        return redirect(url_for('questions.view', question_id=question_id))
    
    # For GET request, prepare the tags string
    tags = [tag.tag.name for tag in question.tags]
    tags_string = ', '.join(tags)
    
    return render_template('questions/edit.html', question=question, tags_string=tags_string)


@questions_bp.route('/<int:question_id>/delete', methods=['POST'])
@login_required
def delete(question_id):
    question = Question.query.get_or_404(question_id)
    
    # Check if user is author or admin
    if question.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    question.soft_delete()
    
    flash('Your question has been deleted', 'success')
    return redirect(url_for('main.index'))


@questions_bp.route('/<int:question_id>/vote', methods=['POST'])
@login_required
def vote(question_id):
    question = Question.query.get_or_404(question_id)
    vote_type = int(request.form.get('vote_type', 0))
    
    if vote_type not in [1, -1]:
        flash('Invalid vote type', 'danger')
        return redirect(url_for('questions.view', question_id=question_id))
    
    # Check if user has already voted
    existing_vote = Vote.query.filter_by(
        user_id=current_user.id, question_id=question_id
    ).first()
    
    if existing_vote:
        if existing_vote.vote_type == vote_type:
            # Remove vote if clicking the same button
            db.session.delete(existing_vote)
            # Update author reputation
            author = User.query.get(question.user_id)
            author.update_reputation(-vote_type)
        else:
            # Change vote
            existing_vote.vote_type = vote_type
            # Update author reputation (double the effect since reversing)
            author = User.query.get(question.user_id)
            author.update_reputation(vote_type * 2)
    else:
        # New vote
        vote = Vote(
            user_id=current_user.id,
            question_id=question_id,
            vote_type=vote_type
        )
        db.session.add(vote)
        
        # Update author reputation
        author = User.query.get(question.user_id)
        author.update_reputation(vote_type)
    
    db.session.commit()
    
    return redirect(url_for('questions.view', question_id=question_id))


@questions_bp.route('/<int:question_id>/comments/add', methods=['POST'])
@login_required
def add_comment(question_id):
    body = request.form.get('body')
    parent_comment_id = request.form.get('parent_comment_id')
    
    if not body:
        flash('Comment body cannot be empty', 'danger')
        return redirect(url_for('questions.view', question_id=question_id))
    
    # Create new comment
    comment = Comment(
        body=body,
        user_id=current_user.id,
        question_id=question_id,
        parent_comment_id=parent_comment_id if parent_comment_id else None
    )
    
    db.session.add(comment)
    db.session.commit()
    
    flash('Your comment has been added', 'success')
    return redirect(url_for('questions.view', question_id=question_id))


@questions_bp.route('/<int:question_id>/mark_answered', methods=['POST'])
@login_required
def mark_answered(question_id):
    """Mark a question as answered"""
    question = Question.query.get_or_404(question_id)
    
    # Check if user is authorized to mark as answered (author or admin)
    if current_user.id != question.user_id and not current_user.is_admin:
        flash('You are not authorized to mark this question as answered.', 'danger')
        return redirect(url_for('questions.view', question_id=question_id))
    
    question.is_answered = True
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Question marked as answered'})
    
    flash('Question marked as answered.', 'success')
    return redirect(url_for('questions.view', question_id=question_id))


@questions_bp.route('/<int:question_id>/mark_unanswered', methods=['POST'])
@login_required
def mark_unanswered(question_id):
    """Unmark a question as answered"""
    question = Question.query.get_or_404(question_id)
    
    # Check if user is authorized to unmark as answered (author or admin)
    if current_user.id != question.user_id and not current_user.is_admin:
        flash('You are not authorized to unmark this question as answered.', 'danger')
        return redirect(url_for('questions.view', question_id=question_id))
    
    question.is_answered = False
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'Question unmarked as answered'})
    
    flash('Question unmarked as answered.', 'success')
    return redirect(url_for('questions.view', question_id=question_id))
