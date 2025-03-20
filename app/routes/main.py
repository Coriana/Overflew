from flask import Blueprint, render_template, redirect, url_for, request, current_app, flash
from flask_login import current_user, login_required
from sqlalchemy import or_, desc, case, func
from sqlalchemy.types import TypeDecorator, Integer

from app.models.user import User
from app.models.question import Question
from app.models.comment import Comment
from app.models.tag import Tag, QuestionTag
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
        # In our new model, "unanswered" means no top-level comments
        questions = Question.query.filter(~Question.comments.any(Comment.parent_comment_id == None))
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
        'answer_count': Comment.query.filter_by(parent_comment_id=None).count(),  # Top-level comments are answers
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
    tab = request.args.get('tab', 'all')
    sort = request.args.get('sort', 'relevance')
    
    if not query:
        return redirect(url_for('main.index'))
    
    # Search for questions that match the query in title or content
    question_query = Question.query.filter(
        or_(
            Question.title.ilike(f'%{query}%'),
            Question.body.ilike(f'%{query}%')
        )
    )
    
    # Also search by tags
    tag_questions = Question.query.join(
        QuestionTag, Question.id == QuestionTag.question_id
    ).join(
        Tag, QuestionTag.tag_id == Tag.id
    ).filter(
        Tag.name.ilike(f'%{query}%')
    )
    
    # Search for comments containing the query
    comment_query = Comment.query.filter(
        Comment.body.ilike(f'%{query}%')
    )
    
    # Get questions from the matching comments
    questions_from_comments = Question.query.filter(
        Question.id.in_([c.question_id for c in comment_query])
    )
    
    # Combine the queries using union to avoid duplicates
    all_question_ids = set()
    
    # Add IDs from each query source
    for q in question_query:
        all_question_ids.add(q.id)
    for q in tag_questions:
        all_question_ids.add(q.id)
    for q in questions_from_comments:
        all_question_ids.add(q.id)
        
    # Manually check all content if we have no results
    if not all_question_ids:
        current_app.logger.warning(f"No results found for '{query}', trying manual search")
        all_questions = Question.query.all()
        all_comments = Comment.query.all()
        
        # Search in questions (title and body)
        for q in all_questions:
            if query.lower() in q.title.lower() or query.lower() in q.body.lower():
                all_question_ids.add(q.id)
                current_app.logger.info(f"Found match in question {q.id}: {q.title}")
        
        # Search in comments
        for c in all_comments:
            if query.lower() in c.body.lower():
                all_question_ids.add(c.question_id)
                current_app.logger.info(f"Found match in comment {c.id} for question {c.question_id}")
    
    # Get the combined query from the IDs we collected
    combined_query = Question.query.filter(Question.id.in_(all_question_ids))
    
    # Apply sorting
    if sort == 'newest':
        combined_query = combined_query.order_by(Question.created_at.desc())
    elif sort == 'votes':
        # This is more complex as we need to sort by votes
        # We'll get all questions and sort them in Python
        sorted_questions = combined_query.all()
        sorted_questions.sort(key=lambda q: q.score, reverse=True)
        sorted_ids = [q.id for q in sorted_questions]
        
        # Create a new query using the sorted IDs
        # Use a case statement to preserve the sorting order
        if sorted_ids:
            case_stmt = case(
                {id_val: idx for idx, id_val in enumerate(sorted_ids)},
                value=Question.id
            )
            combined_query = Question.query.filter(Question.id.in_(sorted_ids)).order_by(case_stmt)
    elif sort == 'activity':
        combined_query = combined_query.order_by(Question.updated_at.desc())
    else:  # relevance - default
        # Sort by whether the query is found in the title (more relevant)
        sorted_questions = combined_query.all()
        sorted_questions.sort(key=lambda q: (
            query.lower() in q.title.lower(),  # First priority: term in title
            q.score  # Second priority: score
        ), reverse=True)
        sorted_ids = [q.id for q in sorted_questions]
        
        # Create a new query with preserved order
        if sorted_ids:
            case_stmt = case(
                {id_val: idx for idx, id_val in enumerate(sorted_ids)},
                value=Question.id
            )
            combined_query = Question.query.filter(Question.id.in_(sorted_ids)).order_by(case_stmt)
    
    # Get data for the other tabs
    users = User.query.filter(User.username.ilike(f'%{query}%')).all()
    tags = Tag.query.filter(Tag.name.ilike(f'%{query}%')).all()
    comments = Comment.query.filter(Comment.body.ilike(f'%{query}%')).all()
    
    # Get counts for each tab
    question_count = len(all_question_ids)
    comment_count = len(comments)
    user_count = len(users)
    tag_count = len(tags)
    total_results = question_count + comment_count + user_count + tag_count
    
    # Paginate the results
    paginated_questions = combined_query.paginate(
        page=page, per_page=10, error_out=False
    )
    
    current_app.logger.info(f"Search query '{query}' found {total_results} total results")
    
    return render_template(
        'main/search.html',
        questions=paginated_questions,
        comments=comments,
        users=users,
        tags=tags,
        query=query,
        total_results=total_results,
        question_count=question_count,
        comment_count=comment_count,
        user_count=user_count,
        tag_count=tag_count,
        tab=tab,
        sort=sort
    )


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
    sort = request.args.get('sort', 'newest')
    
    # Get questions with this tag
    query = Question.query.join(
        QuestionTag, Question.id == QuestionTag.question_id
    ).join(
        Tag, QuestionTag.tag_id == Tag.id
    ).filter(
        Tag.name == tag_name
    )
    
    # Apply sorting
    if sort == 'activity':
        query = query.order_by(Question.updated_at.desc())
    elif sort == 'votes':
        query = query.order_by(Question.score.desc())
    elif sort == 'unanswered':
        query = query.filter(~Question.comments.any(Comment.parent_comment_id == None))
    else:  # Default to newest
        query = query.order_by(Question.created_at.desc())
    
    # Paginate results
    questions = query.paginate(page=page, per_page=10, error_out=False)
    
    # Check if the current user is following this tag
    is_following = False
    if current_user.is_authenticated:
        try:
            is_following = tag in current_user.followed_tags
        except:
            # If followed_tags relationship isn't set up yet, just default to False
            is_following = False
    
    current_app.logger.info(f"Tag '{tag_name}' found {questions.total} questions")
    
    return render_template('main/tag.html', tag=tag, questions=questions, sort=sort, is_following=is_following)


@main_bp.route('/tag/<string:tag_name>/follow', methods=['POST'])
@login_required
def follow_tag(tag_name):
    tag = Tag.query.filter_by(name=tag_name).first_or_404()
    
    # Check if user is already following this tag
    if tag in current_user.followed_tags:
        flash('You are already following this tag.', 'info')
    else:
        current_user.followed_tags.append(tag)
        db.session.commit()
        flash(f'You are now following the [{tag.name}] tag.', 'success')
    
    return redirect(url_for('main.tag', tag_name=tag.name))


@main_bp.route('/tag/<string:tag_name>/unfollow', methods=['POST'])
@login_required
def unfollow_tag(tag_name):
    tag = Tag.query.filter_by(name=tag_name).first_or_404()
    
    # Check if user is following this tag
    if tag in current_user.followed_tags:
        current_user.followed_tags.remove(tag)
        db.session.commit()
        flash(f'You are no longer following the [{tag.name}] tag.', 'success')
    else:
        flash('You were not following this tag.', 'info')
    
    return redirect(url_for('main.tag', tag_name=tag.name))


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
        comments_count = db.session.query(db.func.count(Comment.id)).filter(Comment.user_id == user.id).scalar() or 0
        post_count = comments_count
        
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
