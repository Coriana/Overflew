from flask import Blueprint, render_template, flash, redirect, url_for, request, current_app
from flask_login import login_required, current_user
from app import db
from app.models.user import User
from app.models.question import Question
from app.models.comment import Comment
from app.models.tag import Tag
from functools import wraps
from datetime import datetime, timedelta
import random

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Admin required decorator
def admin_required(f):
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            current_app.logger.warning('Unauthorized access attempt')
            return current_app.login_manager.unauthorized()
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function


@admin_bp.route('/')
@login_required
@admin_required
def index():
    from datetime import datetime, timedelta
    
    # Calculate today's date (start of day)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Get counts for various entities
    stats = {
        'question_count': Question.query.count(),
        'question_today_count': Question.query.filter(Question.created_at >= today).count(),
        'user_count': User.query.count(),
        'comment_count': Comment.query.count()
    }
    
    return render_template('admin/index.html', stats=stats)



@admin_bp.route('/users')
@login_required
@admin_required
def users():
    users = User.query.all()
    return render_template('admin/users.html', users=users)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    # Don't allow deleting self
    if user_id == current_user.id:
        flash('You cannot delete your own account', 'danger')
        return redirect(url_for('admin.users'))
    
    user = User.query.get_or_404(user_id)
    
    # Don't delete admins for safety
    if user.is_admin:
        flash('Cannot delete admin users', 'danger')
        return redirect(url_for('admin.users'))
    
    try:
        # Soft delete user's content instead of hard deleting it
        for comment in user.comments:
            comment.soft_delete()
            
        for answer in user.answers:
            answer.soft_delete()
            
        for question in user.questions:
            question.soft_delete()
            
        # Still delete votes as they don't need to maintain the structure
        db.session.query(Vote).filter_by(user_id=user_id).delete()
        
        # Delete the user
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    
    return redirect(url_for('admin.users'))


@admin_bp.route('/questions')
@login_required
@admin_required
def questions():
    # Get search parameters
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    sort_by = request.args.get('sort', 'newest')
    
    # Build query
    query = Question.query
    
    # Apply search filter
    if search:
        query = query.filter(db.or_(
            Question.title.ilike(f'%{search}%'),
            Question.content.ilike(f'%{search}%')
        ))
    
    # Apply status filter
    if status == 'answered':
        query = query.filter(Question.answers.any())
    elif status == 'unanswered':
        query = query.filter(~Question.answers.any())
    
    # Apply sorting
    if sort_by == 'newest':
        query = query.order_by(Question.created_at.desc())
    elif sort_by == 'oldest':
        query = query.order_by(Question.created_at.asc())
    elif sort_by == 'votes':
        query = query.order_by(Question.upvotes.desc())
    elif sort_by == 'views':
        query = query.order_by(Question.view_count.desc())
    
    # Get questions and pagination
    questions = query.all()
    
    # Create a dictionary to store metadata for each question
    question_meta = {}
    
    # Process each question to convert lazy-loaded relationships to actual counts
    for question in questions:
        # Store answer count and has_accepted_answer in the metadata dictionary
        question_meta[question.id] = {
            'answer_count': question.answers.count(),
            'has_accepted_answer': any(answer.is_accepted for answer in question.answers)
        }
    
    return render_template('admin/questions.html', questions=questions, question_meta=question_meta)


@admin_bp.route('/questions/<int:question_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)
    
    # Soft delete the question
    question.soft_delete()
    
    flash('Question deleted successfully', 'success')
    return redirect(url_for('admin.questions'))


@admin_bp.route('/tags')
@login_required
@admin_required
def tags():
    from datetime import datetime
    
    tags = Tag.query.all()
    
    # Add missing attributes for template rendering
    for tag in tags:
        # If there's no created_at field, set a default value
        if not hasattr(tag, 'created_at'):
            tag.created_at = datetime.now()  # Default to current time
        
        # Add question count for each tag
        tag.question_count = tag.questions.count()
    
    return render_template('admin/tags.html', tags=tags)


# AI features have been removed from this application

@admin_bp.route('/users/toggle_admin/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    
    # Prevent removing admin from yourself
    if user.id == current_user.id:
        flash('You cannot change your own admin status.', 'danger')
        return redirect(url_for('admin.users'))
    
    user.is_admin = not user.is_admin
    db.session.commit()
    
    action = 'granted' if user.is_admin else 'revoked'
    flash(f'Admin privileges {action} for {user.username}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/tags/edit/<string:tag_name>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_tag(tag_name):
    tag = Tag.query.filter_by(name=tag_name).first_or_404()
    
    if request.method == 'POST':
        tag.name = request.form.get('name')
        tag.description = request.form.get('description')
        try:
            db.session.commit()
            flash('Tag updated successfully.', 'success')
            return redirect(url_for('admin.tags'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating tag: {str(e)}', 'danger')
    
    return render_template('admin/edit_tag.html', tag=tag)


@admin_bp.route('/tags/merge', methods=['GET', 'POST'])
@login_required
@admin_required
def merge_tags():
    if request.method == 'POST':
        source_tag_name = request.form.get('source_tag')
        target_tag_name = request.form.get('target_tag')
        
        source_tag = Tag.query.filter_by(name=source_tag_name).first()
        target_tag = Tag.query.filter_by(name=target_tag_name).first()
        
        if not source_tag or not target_tag:
            flash('One or both tags not found.', 'danger')
            return redirect(url_for('admin.tags'))
        
        if source_tag.id == target_tag.id:
            flash('Cannot merge a tag with itself.', 'danger')
            return redirect(url_for('admin.tags'))
        
        # Get all question_tags for the source tag
        question_tags = QuestionTag.query.filter_by(tag_id=source_tag.id).all()
        
        for qt in question_tags:
            # Check if the question already has the target tag
            existing = QuestionTag.query.filter_by(
                question_id=qt.question_id, 
                tag_id=target_tag.id
            ).first()
            
            if not existing:
                # Update this question_tag to point to target tag
                qt.tag_id = target_tag.id
            else:
                # Remove duplicate
                db.session.delete(qt)
        
        # Delete the source tag
        db.session.delete(source_tag)
        
        try:
            db.session.commit()
            flash(f'Successfully merged "{source_tag_name}" into "{target_tag_name}".', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Error merging tags: {str(e)}', 'danger')
            
        return redirect(url_for('admin.tags'))
    
    # GET request - show merge form
    source = request.args.get('source')
    tags = Tag.query.order_by(Tag.name).all()
    return render_template('admin/merge_tags.html', tags=tags, source=source)


@admin_bp.route('/questions/toggle_closed/<int:question_id>', methods=['POST'])
@login_required
@admin_required
def toggle_question_closed(question_id):
    question = Question.query.get_or_404(question_id)
    question.is_closed = not question.is_closed
    db.session.commit()
    
    status = 'closed' if question.is_closed else 'reopened'
    flash(f'Question has been {status}.', 'success')
    return redirect(url_for('admin.questions'))


@admin_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@admin_required
def settings():
    from app.models.site_settings import SiteSettings
    from flask_wtf import FlaskForm
    
    # Create a simple form for CSRF protection
    class SettingsForm(FlaskForm):
        pass
        
    form = SettingsForm()
    
    if request.method == 'POST' and form.validate_on_submit():
        # No AI settings to update
        flash('Settings updated successfully', 'success')
        return redirect(url_for('admin.settings'))
    
    # No settings to retrieve
    settings = {}
    
    return render_template('admin/settings.html', settings=settings, form=form)
