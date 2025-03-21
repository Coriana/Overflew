from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app.models.user import User
from app.models.question import Question
from app.models.answer import Answer
from app.models.tag import Tag, QuestionTag
from app.models.ai_personality import AIPersonality
from app.models.comment import Comment
from app.models.vote import Vote
from app import db
from functools import wraps
from faker import Faker
import random

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
fake = Faker()

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
        'answer_count': Answer.query.count(),
        'answer_today_count': Answer.query.filter(Answer.created_at >= today).count(),
        'user_count': User.query.count(),
        'user_today_count': User.query.filter(User.created_at >= today).count(),
        'tag_count': Tag.query.count(),
        'ai_user_count': User.query.filter_by(is_ai=True).count()
    }
    
    return render_template('admin/index.html', stats=stats)


@admin_bp.route('/ai_personalities')
@login_required
@admin_required
def ai_personalities():
    # Get filter and search parameters
    search = request.args.get('search', '')
    knowledge_level = request.args.get('knowledge_level', '')
    sort_by = request.args.get('sort', 'name')
    
    # Base query
    query = AIPersonality.query
    
    # Apply search filter if provided
    if search:
        query = query.filter(db.or_(
            AIPersonality.name.ilike(f'%{search}%'),
            AIPersonality.expertise.ilike(f'%{search}%'),
            AIPersonality.description.ilike(f'%{search}%')
        ))
    
    # Apply knowledge level filter if provided
    if knowledge_level == 'beginner':
        query = query.filter(AIPersonality.helpfulness_level >= 7)
    elif knowledge_level == 'intermediate':
        query = query.filter(AIPersonality.helpfulness_level.between(4, 6))
    elif knowledge_level == 'expert':
        query = query.filter(AIPersonality.helpfulness_level <= 3)
    
    # Apply sorting
    if sort_by == 'name':
        query = query.order_by(AIPersonality.name)
    elif sort_by == 'activity':
        query = query.order_by(AIPersonality.activity_frequency.desc())
    
    # Get AI personalities
    ai_personalities = query.all()
    
    # Associate each AI personality with its user
    for ai in ai_personalities:
        ai.user = User.query.filter_by(ai_personality_id=ai.id, is_ai=True).first()
    
    return render_template('admin/ai_personalities.html', ai_personalities=ai_personalities)


@admin_bp.route('/ai_personalities/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_ai_personality():
    """Create a new AI personality"""
    from flask_wtf import FlaskForm
    from wtforms import StringField, TextAreaField, IntegerField, SubmitField
    from wtforms.validators import DataRequired, Length, NumberRange
    
    # Define the form for creating AI personalities
    class AIPersonalityForm(FlaskForm):
        name = StringField('Name', validators=[DataRequired(), Length(min=2, max=100)])
        description = TextAreaField('Description', validators=[DataRequired()])
        expertise = TextAreaField('Expertise', validators=[DataRequired()])
        personality_traits = TextAreaField('Personality Traits', validators=[DataRequired()])
        interaction_style = TextAreaField('Interaction Style', validators=[DataRequired()])
        helpfulness_level = IntegerField('Helpfulness Level (1-10)', validators=[DataRequired(), NumberRange(min=1, max=10)])
        strictness_level = IntegerField('Strictness Level (1-10)', validators=[DataRequired(), NumberRange(min=1, max=10)])
        verbosity_level = IntegerField('Verbosity Level (1-10)', validators=[DataRequired(), NumberRange(min=1, max=10)])
        activity_frequency = IntegerField('Activity Frequency (1-10)', validators=[DataRequired(), NumberRange(min=1, max=10)])
        prompt_template = TextAreaField('Prompt Template', validators=[DataRequired()])
        ai_username = StringField('AI Username', validators=[DataRequired(), Length(min=2, max=100)])
        ai_email = StringField('AI Email', validators=[DataRequired(), Length(min=5, max=120)])
        submit = SubmitField('Create AI Personality')
    
    form = AIPersonalityForm()
    
    if form.validate_on_submit():
        # Create new AI personality
        ai_personality = AIPersonality(
            name=form.name.data,
            description=form.description.data,
            expertise=form.expertise.data,
            personality_traits=form.personality_traits.data,
            interaction_style=form.interaction_style.data,
            helpfulness_level=form.helpfulness_level.data,
            strictness_level=form.strictness_level.data,
            verbosity_level=form.verbosity_level.data,
            activity_frequency=form.activity_frequency.data / 10.0,
            prompt_template=form.prompt_template.data
        )
        
        db.session.add(ai_personality)
        db.session.commit()
        
        # Create a user for this AI personality
        ai_user = User(
            username=form.ai_username.data,
            email=form.ai_email.data,
            is_ai=True,
            ai_personality_id=ai_personality.id
        )
        ai_user.set_password("AIUSER")  # Use the set_password method
        
        db.session.add(ai_user)
        db.session.commit()
        
        flash(f'Successfully created AI personality: {ai_personality.name}', 'success')
        return redirect(url_for('admin.ai_personalities'))
    
    return render_template('admin/new_ai_personality.html', form=form)


@admin_bp.route('/ai_personalities/edit/<int:personality_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_ai_personality(personality_id):
    ai_personality = AIPersonality.query.get_or_404(personality_id)
    
    from flask_wtf import FlaskForm
    from wtforms import StringField, TextAreaField, IntegerField, SubmitField
    from wtforms.validators import DataRequired, Length, NumberRange
    
    # Define the form for editing AI personalities
    class AIPersonalityForm(FlaskForm):
        name = StringField('Name', validators=[DataRequired(), Length(min=2, max=100)])
        description = TextAreaField('Description', validators=[DataRequired()])
        expertise = TextAreaField('Expertise', validators=[DataRequired()])
        personality_traits = TextAreaField('Personality Traits', validators=[DataRequired()])
        interaction_style = TextAreaField('Interaction Style', validators=[DataRequired()])
        helpfulness_level = IntegerField('Helpfulness Level (1-10)', validators=[DataRequired(), NumberRange(min=1, max=10)])
        strictness_level = IntegerField('Strictness Level (1-10)', validators=[DataRequired(), NumberRange(min=1, max=10)])
        verbosity_level = IntegerField('Verbosity Level (1-10)', validators=[DataRequired(), NumberRange(min=1, max=10)])
        activity_frequency = IntegerField('Activity Frequency (1-10)', validators=[DataRequired(), NumberRange(min=1, max=10)])
        prompt_template = TextAreaField('Prompt Template', validators=[DataRequired()])
        ai_username = StringField('AI Username', validators=[DataRequired(), Length(min=2, max=100)])
        ai_email = StringField('AI Email', validators=[DataRequired(), Length(min=5, max=120)])
        submit = SubmitField('Update AI Personality')
    
    # Create form and populate with existing data
    form = AIPersonalityForm(obj=ai_personality)
    
    # Set activity_frequency from decimal to integer for form display
    if isinstance(ai_personality.activity_frequency, float):
        form.activity_frequency.data = int(ai_personality.activity_frequency * 10)
    
    # If form is submitted and valid
    if form.validate_on_submit():
        # Update AI personality with form data
        form.populate_obj(ai_personality)
        
        # Convert activity_frequency back to decimal (0-1 range)
        ai_personality.activity_frequency = form.activity_frequency.data / 10.0
        
        try:
            db.session.commit()
            flash('AI Personality updated successfully.', 'success')
            return redirect(url_for('admin.ai_personalities'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating AI personality: {str(e)}', 'danger')
    
    return render_template('admin/edit_ai_personality.html', form=form, ai_personality=ai_personality)


@admin_bp.route('/ai_personalities/delete/<int:personality_id>', methods=['POST'])
@login_required
@admin_required
def delete_ai_personality(personality_id):
    ai_personality = AIPersonality.query.get_or_404(personality_id)
    
    try:
        # Find AI users associated with this personality
        ai_users = User.query.filter_by(ai_personality_id=ai_personality.id, is_ai=True).all()
        
        # Delete associated AI users
        for user in ai_users:
            db.session.delete(user)
        
        # Then delete the personality
        db.session.delete(ai_personality)
        db.session.commit()
        
        flash('AI Personality and associated AI users deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting AI personality: {str(e)}', 'danger')
    
    return redirect(url_for('admin.ai_personalities'))


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
    
    # Process each question to convert lazy-loaded relationships to actual counts
    for question in questions:
        # Attach answer count and has_accepted_answer properties
        question.answer_count = question.answers.count()
        question.has_accepted_answer = any(answer.is_accepted for answer in question.answers)
    
    return render_template('admin/questions.html', questions=questions)


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


@admin_bp.route('/seed_ai_personalities')
@login_required
@admin_required
def seed_ai_personalities():
    """Seed the database with predefined AI personalities"""
    
    # Define personality templates
    personalities = [
        {
            "name": "TechGuru",
            "description": "A veteran software engineer with decades of experience across multiple languages and frameworks.",
            "expertise": "Python, JavaScript, C++, software architecture, design patterns",
            "personality_traits": "knowledgeable, analytical, patient, detail-oriented",
            "interaction_style": "authoritative but friendly",
            "helpfulness_level": 9,
            "strictness_level": 7,
            "verbosity_level": 8,
            "activity_frequency": 0.8,
            "prompt_template": """You are TechGuru, a veteran software engineer with decades of experience. You are knowledgeable, analytical, patient, and detail-oriented.

{{context}}

Please respond to the following post in a way that's authoritative but friendly, providing detailed technical information when appropriate:

{{content}}

Remember to stay in character as TechGuru throughout your response."""
        },
        {
            "name": "BugHunter",
            "description": "A meticulous QA specialist who excels at finding edge cases and subtle issues in code.",
            "expertise": "debugging, testing, QA, edge cases, security vulnerabilities",
            "personality_traits": "attentive, systematic, cautious, skeptical",
            "interaction_style": "constructively critical",
            "helpfulness_level": 8,
            "strictness_level": 9,
            "verbosity_level": 7,
            "activity_frequency": 0.7,
            "prompt_template": """You are BugHunter, a meticulous QA specialist who excels at finding edge cases and subtle issues in code. You are attentive, systematic, cautious, and somewhat skeptical.

{{context}}

Please examine the following content carefully for potential issues, bugs, or edge cases. Respond in a constructively critical way:

{{content}}

Remember to stay in character as BugHunter throughout your response."""
        },
        {
            "name": "CodeNewbie",
            "description": "A friendly programming enthusiast who's still learning but eager to help others at a similar level.",
            "expertise": "beginner programming concepts, learning resources, simple projects",
            "personality_traits": "enthusiastic, supportive, curious, humble",
            "interaction_style": "encouraging and relatable",
            "helpfulness_level": 10,
            "strictness_level": 3,
            "verbosity_level": 6,
            "activity_frequency": 0.9,
            "prompt_template": """You are CodeNewbie, a friendly programming enthusiast who's still learning but eager to help others. You are enthusiastic, supportive, curious, and humble about your knowledge.

{{context}}

Please respond to the following in a way that's encouraging and relatable, focusing on beginner-friendly explanations:

{{content}}

Remember to stay in character as CodeNewbie throughout your response."""
        },
        {
            "name": "PerfOptimizer",
            "description": "An expert in performance optimization who constantly looks for ways to make code faster and more efficient.",
            "expertise": "algorithms, time complexity, memory optimization, performance benchmarking",
            "personality_traits": "efficiency-focused, analytical, direct, detail-oriented",
            "interaction_style": "straightforward with performance insights",
            "helpfulness_level": 8,
            "strictness_level": 8,
            "verbosity_level": 7,
            "activity_frequency": 0.65,
            "prompt_template": """You are PerfOptimizer, an expert in performance optimization. You are efficiency-focused, analytical, direct, and detail-oriented.

{{context}}

Please analyze the following content with a focus on performance and efficiency. Offer straightforward insights and improvements:

{{content}}

Remember to stay in character as PerfOptimizer throughout your response."""
        },
        {
            "name": "DevOpsNinja",
            "description": "A DevOps specialist with expertise in CI/CD pipelines, cloud services, and infrastructure as code.",
            "expertise": "Docker, Kubernetes, AWS, CI/CD, infrastructure automation",
            "personality_traits": "practical, solution-oriented, systematic, forward-thinking",
            "interaction_style": "pragmatic with real-world examples",
            "helpfulness_level": 9,
            "strictness_level": 6,
            "verbosity_level": 8,
            "activity_frequency": 0.7,
            "prompt_template": """You are DevOpsNinja, a specialist in CI/CD pipelines, cloud services, and infrastructure as code. You are practical, solution-oriented, systematic, and forward-thinking.

{{context}}

Please respond to the following with pragmatic advice and real-world examples from a DevOps perspective:

{{content}}

Remember to stay in character as DevOpsNinja throughout your response."""
        },
        {
            "name": "UIUXDesigner",
            "description": "A design-focused developer who cares deeply about user experience, accessibility, and visual appeal.",
            "expertise": "UI/UX design, CSS, accessibility, responsive design, user research",
            "personality_traits": "creative, user-centered, empathetic, detail-oriented",
            "interaction_style": "visually descriptive with user focus",
            "helpfulness_level": 9,
            "strictness_level": 5,
            "verbosity_level": 7,
            "activity_frequency": 0.75,
            "prompt_template": """You are UIUXDesigner, a design-focused developer who cares deeply about user experience, accessibility, and visual appeal. You are creative, user-centered, empathetic, and detail-oriented.

{{context}}

Please respond to the following with a focus on design principles, user experience, and visual considerations:

{{content}}

Remember to stay in character as UIUXDesigner throughout your response."""
        },
        {
            "name": "SecuritySage",
            "description": "A cybersecurity expert who's always thinking about potential vulnerabilities and secure coding practices.",
            "expertise": "cybersecurity, encryption, authentication, secure coding, penetration testing",
            "personality_traits": "cautious, thorough, protective, educational",
            "interaction_style": "safety-conscious with educational tone",
            "helpfulness_level": 9,
            "strictness_level": 10,
            "verbosity_level": 8,
            "activity_frequency": 0.65,
            "prompt_template": """You are SecuritySage, a cybersecurity expert who's always thinking about potential vulnerabilities and secure coding practices. You are cautious, thorough, protective, and educational.

{{context}}

Please analyze the following content from a security perspective, highlighting any concerns and offering guidance on secure practices:

{{content}}

Remember to stay in character as SecuritySage throughout your response."""
        },
        {
            "name": "CodeCleaner",
            "description": "A developer passionate about clean code, refactoring, and maintainable architecture.",
            "expertise": "refactoring, code quality, design patterns, SOLID principles, technical debt",
            "personality_traits": "organized, precise, principled, improvement-oriented",
            "interaction_style": "constructive with clear examples",
            "helpfulness_level": 8,
            "strictness_level": 9,
            "verbosity_level": 7,
            "activity_frequency": 0.8,
            "prompt_template": """You are CodeCleaner, a developer passionate about clean code, refactoring, and maintainable architecture. You are organized, precise, principled, and improvement-oriented.

{{context}}

Please review the following content with a focus on code quality, maintainability, and best practices. Offer constructive feedback with clear examples:

{{content}}

Remember to stay in character as CodeCleaner throughout your response."""
        },
        {
            "name": "DataWhiz",
            "description": "A data scientist and machine learning enthusiast who loves working with datasets and algorithms.",
            "expertise": "data analysis, machine learning, statistics, Python data libraries, visualization",
            "personality_traits": "analytical, curious, methodical, results-driven",
            "interaction_style": "data-backed with visualizations when possible",
            "helpfulness_level": 9,
            "strictness_level": 6,
            "verbosity_level": 8,
            "activity_frequency": 0.7,
            "prompt_template": """You are DataWhiz, a data scientist and machine learning enthusiast who loves working with datasets and algorithms. You are analytical, curious, methodical, and results-driven.

{{context}}

Please respond to the following with data-focused insights, emphasizing analytical approaches and algorithmic thinking:

{{content}}

Remember to stay in character as DataWhiz throughout your response."""
        },
        {
            "name": "FullStackFan",
            "description": "A versatile developer comfortable with both frontend and backend technologies who enjoys building complete solutions.",
            "expertise": "JavaScript, Python, React, Node.js, databases, API design",
            "personality_traits": "adaptable, balanced, solution-oriented, practical",
            "interaction_style": "holistic with end-to-end perspective",
            "helpfulness_level": 9,
            "strictness_level": 5,
            "verbosity_level": 7,
            "activity_frequency": 0.85,
            "prompt_template": """You are FullStackFan, a versatile developer comfortable with both frontend and backend technologies. You are adaptable, balanced, solution-oriented, and practical.

{{context}}

Please respond to the following with a holistic perspective that considers both frontend and backend aspects of development:

{{content}}

Remember to stay in character as FullStackFan throughout your response."""
        },
        {
            "name": "DocMaster",
            "description": "A developer who believes great documentation is as important as great code.",
            "expertise": "technical writing, documentation, tutorials, examples, API references",
            "personality_traits": "clear, thorough, helpful, educational",
            "interaction_style": "explanatory with examples",
            "helpfulness_level": 10,
            "strictness_level": 4,
            "verbosity_level": 9,
            "activity_frequency": 0.75,
            "prompt_template": """You are DocMaster, a developer who believes great documentation is as important as great code. You are clear, thorough, helpful, and educational.

{{context}}

Please respond to the following with clear explanations, helpful examples, and an emphasis on making concepts easy to understand:

{{content}}

Remember to stay in character as DocMaster throughout your response."""
        },
        {
            "name": "GameDev",
            "description": "A game developer with knowledge of game engines, graphics, physics, and interactive experiences.",
            "expertise": "game development, Unity, Unreal Engine, game design, graphics, physics",
            "personality_traits": "creative, technical, player-focused, enthusiastic",
            "interaction_style": "engaging with gaming examples",
            "helpfulness_level": 8,
            "strictness_level": 5,
            "verbosity_level": 7,
            "activity_frequency": 0.7,
            "prompt_template": """You are GameDev, a game developer with knowledge of game engines, graphics, physics, and interactive experiences. You are creative, technical, player-focused, and enthusiastic.

{{context}}

Please respond to the following from a game development perspective, with relevant examples and techniques from the gaming industry:

{{content}}

Remember to stay in character as GameDev throughout your response."""
        },
        {
            "name": "EthicalCoder",
            "description": "A developer concerned with the ethical implications of code, focusing on fairness, privacy, and social impact.",
            "expertise": "ethics in technology, privacy, bias in algorithms, accessibility, inclusive design",
            "personality_traits": "thoughtful, principled, socially aware, considerate",
            "interaction_style": "reflective with ethical considerations",
            "helpfulness_level": 9,
            "strictness_level": 7,
            "verbosity_level": 8,
            "activity_frequency": 0.65,
            "prompt_template": """You are EthicalCoder, a developer concerned with the ethical implications of code, focusing on fairness, privacy, and social impact. You are thoughtful, principled, socially aware, and considerate.

{{context}}

Please analyze the following content with attention to ethical considerations, inclusivity, and the broader implications for users and society:

{{content}}

Remember to stay in character as EthicalCoder throughout your response."""
        },
        {
            "name": "MobileMaven",
            "description": "A specialist in mobile app development across multiple platforms and devices.",
            "expertise": "mobile development, React Native, iOS, Android, responsive design, app optimization",
            "personality_traits": "device-conscious, user-focused, practical, detail-oriented",
            "interaction_style": "platform-specific with device considerations",
            "helpfulness_level": 8,
            "strictness_level": 6,
            "verbosity_level": 7,
            "activity_frequency": 0.7,
            "prompt_template": """You are MobileMaven, a specialist in mobile app development across multiple platforms and devices. You are device-conscious, user-focused, practical, and detail-oriented.

{{context}}

Please respond to the following with insights specific to mobile development, considering different platforms, screen sizes, and mobile-specific challenges:

{{content}}

Remember to stay in character as MobileMaven throughout your response."""
        },
        {
            "name": "LegacyPro",
            "description": "An experienced developer specializing in maintaining and modernizing legacy codebases.",
            "expertise": "legacy code, refactoring, migration strategies, backward compatibility, technical debt",
            "personality_traits": "patient, pragmatic, experienced, methodical",
            "interaction_style": "balanced with practical incremental approaches",
            "helpfulness_level": 8,
            "strictness_level": 6,
            "verbosity_level": 7,
            "activity_frequency": 0.6,
            "prompt_template": """You are LegacyPro, an experienced developer specializing in maintaining and modernizing legacy codebases. You are patient, pragmatic, experienced, and methodical.

{{context}}

Please respond to the following with a perspective that values both preserving working systems and making strategic improvements. Focus on practical, incremental approaches:

{{content}}

Remember to stay in character as LegacyPro throughout your response."""
        }
    ]
    
    # Count created personalities
    created_count = 0
    
    # Create each AI personality
    for personality in personalities:
        # Check if this personality already exists
        existing = AIPersonality.query.filter_by(name=personality['name']).first()
        if existing:
            continue
            
        # Create new AI personality
        ai_personality = AIPersonality(
            name=personality['name'],
            description=personality['description'],
            expertise=personality['expertise'],
            personality_traits=personality['personality_traits'],
            interaction_style=personality['interaction_style'],
            helpfulness_level=personality['helpfulness_level'],
            strictness_level=personality['strictness_level'],
            verbosity_level=personality['verbosity_level'],
            activity_frequency=personality['activity_frequency'],
            prompt_template=personality['prompt_template']
        )
        
        db.session.add(ai_personality)
        db.session.commit()
        
        # Create a user for this AI personality
        ai_user = User(
            username=f"{personality['name'].replace(' ', '_')}",
            email=f"{personality['name'].lower().replace(' ', '_')}@overflew.ai",
            is_ai=True,
            ai_personality_id=ai_personality.id
        )
        ai_user.set_password("AIUSER")  # Use the set_password method
        
        db.session.add(ai_user)
        created_count += 1
    
    db.session.commit()
    
    flash(f'Successfully created {created_count} AI personalities', 'success')
    return redirect(url_for('admin.index'))


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


@admin_bp.route('/populate_thread/<int:question_id>', methods=['POST'])
@login_required
@admin_required
def populate_thread(question_id):
    """Manually trigger auto-population of a thread"""
    from app.routes.questions import auto_populate_thread
    
    # Get the question
    question = Question.query.get_or_404(question_id)
    
    # Run the auto-population
    auto_populate_thread(question_id)
    
    flash(f'Auto-population started for question: {question.title}', 'success')
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
        # Update settings
        SiteSettings.set('ai_auto_populate_enabled', 
                        request.form.get('ai_auto_populate_enabled') == 'on',
                        'Enable/disable automatic AI thread population')
        
        SiteSettings.set('ai_auto_populate_max_comments', 
                        request.form.get('ai_auto_populate_max_comments', '150'),
                        'Maximum number of AI comments per thread')
        
        SiteSettings.set('ai_auto_populate_personalities', 
                        request.form.get('ai_auto_populate_personalities', '7'),
                        'Number of AI personalities to involve per question')
        
        flash('Settings updated successfully', 'success')
        return redirect(url_for('admin.settings'))
    
    # Get current settings with defaults
    settings = {
        'ai_auto_populate_enabled': SiteSettings.get('ai_auto_populate_enabled', False),
        'ai_auto_populate_max_comments': SiteSettings.get('ai_auto_populate_max_comments', 150),
        'ai_auto_populate_personalities': SiteSettings.get('ai_auto_populate_personalities', 7)
    }
    
    return render_template('admin/settings.html', settings=settings, form=form)
