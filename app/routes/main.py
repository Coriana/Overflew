from flask import Blueprint, render_template, redirect, url_for, request, current_app
from flask_login import current_user
from app.models.question import Question
from app.models.answer import Answer
from app.models.comment import Comment
from app.models.tag import Tag, QuestionTag
from app.models.user import User
from app.models.ai_personality import AIPersonality
from app import db

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    # Get sort parameter from query string
    sort = request.args.get('sort', 'newest')
    page = request.args.get('page', 1, type=int)
    
    # Query questions based on sort parameter
    if sort == 'active':
        questions = Question.query.order_by(Question.updated_at.desc())
    elif sort == 'unanswered':
        questions = Question.query.filter(~Question.answers.any())
    elif sort == 'popular':
        questions = Question.query.order_by(Question.score.desc())
    else:  # default to newest
        questions = Question.query.order_by(Question.created_at.desc())
    
    # Paginate results
    questions = questions.paginate(page=page, per_page=10, error_out=False)
    
    # Get popular tags
    tags = Tag.query.all()
    
    # Get site statistics
    stats = {
        'question_count': Question.query.count(),
        'answer_count': Answer.query.count(),
        'user_count': User.query.count(),
        'ai_count': User.query.filter_by(is_ai=True).count()
    }
    
    return render_template('main/index.html', 
                          questions=questions, 
                          pagination=questions, 
                          tags=tags, 
                          sort=sort,
                          stats=stats)


@main_bp.route('/search')
def search():
    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    
    if not query:
        return redirect(url_for('main.index'))
    
    # Search for questions that match the query in title or body
    questions = Question.query.filter(
        Question.title.ilike(f'%{query}%') | 
        Question.body.ilike(f'%{query}%')
    ).order_by(Question.created_at.desc())
    
    # Also search by tags
    tag_questions = Question.query.join(
        QuestionTag, Question.id == QuestionTag.question_id
    ).join(
        Tag, QuestionTag.tag_id == Tag.id
    ).filter(
        Tag.name.ilike(f'%{query}%')
    )
    
    # Combine the queries
    combined_questions = questions.union(tag_questions).order_by(Question.created_at.desc())
    
    # Paginate the results
    paginated_questions = combined_questions.paginate(
        page=page, per_page=10, error_out=False
    )
    
    current_app.logger.info(f"Search query '{query}' found {paginated_questions.total} results")
    
    return render_template('main/search.html', questions=paginated_questions, query=query)


@main_bp.route('/tags')
def tags():
    from datetime import datetime, timedelta
    
    # Get time boundaries for filtering
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today - timedelta(days=today.weekday())
    
    tags = Tag.query.all()
    return render_template('main/tags.html', tags=tags, today=today, week_start=week_start, Question=Question)


@main_bp.route('/tag/<string:tag_name>')
def tag(tag_name):
    tag = Tag.query.filter_by(name=tag_name).first_or_404()
    page = request.args.get('page', 1, type=int)
    
    # Get questions with this tag
    questions = Question.query.join(
        QuestionTag, Question.id == QuestionTag.question_id
    ).join(
        Tag, QuestionTag.tag_id == Tag.id
    ).filter(
        Tag.name == tag_name
    ).order_by(Question.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False
    )
    
    current_app.logger.info(f"Tag '{tag_name}' found {questions.total} questions")
    
    return render_template('main/tag.html', tag=tag, questions=questions)


@main_bp.route('/users')
def users():
    # Get sort parameter from query string
    sort = request.args.get('sort', 'reputation')
    q = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    
    # Query to get users based on sort and search parameters
    query = User.query.filter_by(is_ai=False)
    
    # Apply search if provided
    if q:
        query = query.filter(
            (User.username.ilike(f'%{q}%')) | 
            (User.display_name.ilike(f'%{q}%')) | 
            (User.bio.ilike(f'%{q}%'))
        )
    
    # Apply sorting
    if sort == 'newest':
        query = query.order_by(User.created_at.desc())
    elif sort == 'name':
        query = query.order_by(User.username.asc())
    elif sort == 'active':
        query = query.order_by(User.last_seen.desc())
    else:  # default to reputation
        query = query.order_by(User.reputation.desc())
    
    # Paginate the results
    users = query.paginate(page=page, per_page=20, error_out=False)
    
    # Get top contributors for sidebar
    top_contributors = User.query.filter_by(is_ai=False).order_by(
        User.reputation.desc()
    ).limit(10).all()
    
    # Get AI personalities for sidebar
    ai_personalities = User.query.filter_by(is_ai=True).order_by(
        User.reputation.desc()
    ).limit(5).all()
    
    return render_template('main/users.html', 
                          users=users, 
                          pagination=users,
                          top_contributors=top_contributors,
                          ai_personalities=ai_personalities)


@main_bp.route('/ai-community')
@main_bp.route('/ai_community')  # Keep old route for backward compatibility
def ai_community():
    page = request.args.get('page', 1, type=int)
    expertise = request.args.get('expertise', '')
    knowledge_level = request.args.get('knowledge_level', '')
    sort = request.args.get('sort', 'reputation')
    
    # Build query with AI users joined with their personalities
    query = db.session.query(User, AIPersonality).join(
        AIPersonality, User.ai_personality_id == AIPersonality.id
    ).filter(User.is_ai == True)
    
    # Apply filters
    if expertise:
        query = query.filter(AIPersonality.expertise.ilike(f'%{expertise}%'))
    
    # Apply sorting
    if sort == 'reputation':
        query = query.order_by(User.reputation.desc())
    elif sort == 'activity':
        query = query.order_by(AIPersonality.activity_frequency.desc())
    elif sort == 'newest':
        query = query.order_by(User.created_at.desc())
    
    # Execute query and paginate
    results = query.paginate(page=page, per_page=20, error_out=False)
    
    # Prepare data for template
    ai_personalities = []
    for user, personality in results.items:
        # Get post count for this user using count() instead of length
        answers_count = db.session.query(db.func.count(Answer.id)).filter(Answer.user_id == user.id).scalar() or 0
        comments_count = db.session.query(db.func.count(Comment.id)).filter(Comment.user_id == user.id).scalar() or 0
        post_count = answers_count + comments_count
        
        # Combine user and personality data
        personality_data = {
            'user': user,
            'knowledge_level': 'Expert',  # Default, could be derived from helpfulness_level
            'interaction_style': personality.interaction_style,
            'expertise': personality.expertise,
            'traits': personality.personality_traits,
            'post_count': post_count
        }
        ai_personalities.append(personality_data)
    
    # Set up pagination
    pagination = results
    
    return render_template('main/ai_community.html', 
                          ai_personalities=ai_personalities,
                          pagination=pagination)
