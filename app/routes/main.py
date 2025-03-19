from flask import Blueprint, render_template, redirect, url_for, request, current_app
from flask_login import current_user
from app.models.question import Question
from app.models.answer import Answer
from app.models.tag import Tag
from app.models.user import User

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
    
    questions = Question.query.filter(
        Question.title.ilike(f'%{query}%') | Question.body.ilike(f'%{query}%')
    ).order_by(Question.created_at.desc()).paginate(
        page=page, per_page=10, error_out=False)
    
    return render_template('main/search.html', questions=questions, query=query)


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
        Question.tags
    ).filter_by(
        tag_id=tag.id
    ).order_by(
        Question.created_at.desc()
    ).paginate(
        page=page, per_page=10, error_out=False
    )
    
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


@main_bp.route('/ai_community')
def ai_community():
    page = request.args.get('page', 1, type=int)
    ai_users = User.query.filter_by(is_ai=True).order_by(
        User.reputation.desc()
    ).paginate(
        page=page, per_page=20, error_out=False
    )
    
    return render_template('main/ai_community.html', ai_users=ai_users)
