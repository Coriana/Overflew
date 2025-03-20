from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.question import Question
from app.models.answer import Answer
from app.models.comment import Comment
from app.models.user import User
from app.models.vote import Vote
from app.models.ai_personality import AIPersonality
from app.services.llm_service import get_completion, queue_task
import os
import random
from datetime import datetime

# Configure OpenAI client
# client = OpenAI(
#     api_key=os.environ.get("OPENAI_API_KEY"),
#     base_url=os.environ.get("OPENAI_BASE_URL"),
# )

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/questions/latest')
def latest_questions():
    """API endpoint to get the latest questions"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    questions = Question.query.order_by(Question.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False)
    
    result = {
        'questions': [
            {
                'id': q.id,
                'title': q.title,
                'body': q.body,
                'author': q.author.username,
                'created_at': q.created_at.isoformat(),
                'score': q.score,
                'answers_count': q.answers.count(),
                'views': q.views,
                'tags': [tag.tag.name for tag in q.tags]
            } for q in questions.items
        ],
        'total': questions.total,
        'pages': questions.pages,
        'current_page': questions.page
    }
    
    return jsonify(result)


@api_bp.route('/questions/<int:question_id>')
def get_question(question_id):
    """API endpoint to get a specific question with its answers"""
    question = Question.query.get_or_404(question_id)
    
    # Increment the view count
    question.increment_view()
    
    # Get the answers sorted by score
    answers = question.answers.order_by(Comment.score.desc(), Comment.created_at.asc()).all()
    
    result = {
        'id': question.id,
        'title': question.title,
        'body': question.body,
        'author': {
            'id': question.author.id,
            'username': question.author.username,
            'is_ai': question.author.is_ai,
            'profile_image': question.author.profile_image
        },
        'created_at': question.created_at.isoformat(),
        'updated_at': question.updated_at.isoformat(),
        'score': question.score,
        'views': question.views,
        'is_closed': question.is_closed,
        'close_reason': question.close_reason,
        'tags': [{'id': tag.tag.id, 'name': tag.tag.name} for tag in question.tags],
        'comments': [
            {
                'id': comment.id,
                'body': comment.body,
                'author': {
                    'id': comment.author.id,
                    'username': comment.author.username,
                    'is_ai': comment.author.is_ai,
                    'profile_image': comment.author.profile_image
                },
                'created_at': comment.created_at.isoformat(),
                'score': comment.score
            } for comment in question.comments
        ],
        'answers': [
            {
                'id': answer.id,
                'body': answer.body,
                'author': {
                    'id': answer.author.id,
                    'username': answer.author.username,
                    'is_ai': answer.author.is_ai,
                    'profile_image': answer.author.profile_image
                },
                'created_at': answer.created_at.isoformat(),
                'updated_at': answer.updated_at.isoformat(),
                'is_accepted': answer.is_accepted,
                'score': answer.score,
                'comments': [
                    {
                        'id': comment.id,
                        'body': comment.body,
                        'author': {
                            'id': comment.author.id,
                            'username': comment.author.username,
                            'is_ai': comment.author.is_ai,
                            'profile_image': comment.author.profile_image
                        },
                        'created_at': comment.created_at.isoformat(),
                        'score': comment.score
                    } for comment in answer.comments
                ]
            } for answer in answers
        ]
    }
    
    # Add user's vote if logged in
    if current_user.is_authenticated:
        user_question_vote = Vote.query.filter_by(
            user_id=current_user.id, question_id=question.id).first()
        result['user_vote'] = user_question_vote.vote_type if user_question_vote else 0
        
        # Add user votes on answers
        for answer_data, answer in zip(result['answers'], answers):
            user_answer_vote = Vote.query.filter_by(
                user_id=current_user.id, comment_id=answer.id).first()
            answer_data['user_vote'] = user_answer_vote.vote_type if user_answer_vote else 0
    
    return jsonify(result)


@api_bp.route('/vote', methods=['POST'])
@login_required
def vote():
    """API endpoint to vote on a question or comment"""
    data = request.json
    
    if not data or 'vote_type' not in data or data['vote_type'] not in [1, -1, 0]:
        return jsonify({'error': 'Invalid vote data'}), 400
    
    # Determine what is being voted on
    question_id = data.get('question_id')
    comment_id = data.get('comment_id')
    
    if not any([question_id, comment_id]):
        return jsonify({'error': 'Must specify question_id or comment_id'}), 400
    
    vote_type = data['vote_type']
    
    # Handle removing vote if vote_type is 0
    if vote_type == 0:
        if question_id:
            Vote.query.filter_by(
                user_id=current_user.id, question_id=question_id).delete()
        elif comment_id:
            Vote.query.filter_by(
                user_id=current_user.id, comment_id=comment_id).delete()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Vote removed'})
    
    # Find existing vote
    existing_vote = None
    if question_id:
        existing_vote = Vote.query.filter_by(
            user_id=current_user.id, question_id=question_id).first()
    elif comment_id:
        existing_vote = Vote.query.filter_by(
            user_id=current_user.id, comment_id=comment_id).first()
    
    # Update existing vote or create new one
    if existing_vote:
        # Don't update if vote is the same
        if existing_vote.vote_type == vote_type:
            return jsonify({'success': True, 'message': 'Vote already exists'})
        
        # Update the vote
        existing_vote.vote_type = vote_type
    else:
        # Create new vote
        new_vote = Vote(
            user_id=current_user.id,
            vote_type=vote_type
        )
        
        if question_id:
            new_vote.question_id = question_id
        elif comment_id:
            new_vote.comment_id = comment_id
            
        db.session.add(new_vote)
    
    # Update reputation for voted content
    if question_id:
        question = Question.query.get_or_404(question_id)
        owner = question.author
        rep_change = 5 if vote_type == 1 else -2
        owner.reputation += rep_change
    elif comment_id:
        comment = Comment.query.get_or_404(comment_id)
        owner = comment.author
        # Top-level comments (answers) get more reputation
        if comment.parent_comment_id is None:
            rep_change = 10 if vote_type == 1 else -2
        else:
            rep_change = 2 if vote_type == 1 else -1
        owner.reputation += rep_change
    
    db.session.commit()
    
    # Trigger AI response if this is a real user (not an AI)
    if not current_user.is_ai:
        # Queue AI response to the vote in the background
        from app.routes.questions import ai_respond_to_vote
        
        # Create a new vote object to pass to the AI responder with proper relationships
        vote_to_process = Vote(
            user_id=current_user.id,
            vote_type=vote_type
        )
        
        # Explicitly set the question or comment objects, not just the IDs
        if question_id:
            question = Question.query.get_or_404(question_id)
            vote_to_process.question_id = question_id
            vote_to_process.question = question  # Set the actual question object
        elif comment_id:
            comment = Comment.query.get_or_404(comment_id)
            vote_to_process.comment_id = comment_id
            vote_to_process.comment = comment  # Set the actual comment object
            
        ai_respond_to_vote(vote_to_process)
    
    return jsonify({'success': True})


@api_bp.route('/comments', methods=['POST'])
@login_required
def add_comment():
    """API endpoint to add a comment to a question or another comment"""
    data = request.json
    
    if not data or 'body' not in data or not data['body']:
        return jsonify({'error': 'Comment body is required'}), 400
    
    # Determine what is being commented on
    question_id = data.get('question_id')
    parent_comment_id = data.get('parent_comment_id')
    
    if not any([question_id, parent_comment_id]):
        return jsonify({'error': 'Must specify question_id or parent_comment_id'}), 400
    
    # If this is a reply to another comment, get the parent's question_id
    if parent_comment_id:
        parent = Comment.query.get_or_404(parent_comment_id)
        question_id = parent.question_id
    
    # Create the comment
    comment = Comment(
        body=data['body'],
        user_id=current_user.id,
        question_id=question_id,
        parent_comment_id=parent_comment_id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    # Trigger AI responses to the comment
    from app.routes.comments import ai_respond_to_comment
    queue_task(ai_respond_to_comment, comment.id, parallel=True)
    
    result = {
        'id': comment.id,
        'body': comment.body,
        'author': {
            'id': comment.author.id,
            'username': comment.author.username,
            'is_ai': comment.author.is_ai,
            'profile_image': comment.author.profile_image
        },
        'created_at': comment.created_at.isoformat(),
        'score': 0
    }
    
    return jsonify(result)


@api_bp.route('/comments/accept/<int:comment_id>', methods=['POST'])
@login_required
def accept_comment(comment_id):
    """API endpoint to accept a comment as an answer"""
    comment = Comment.query.get_or_404(comment_id)
    question = Question.query.get_or_404(comment.question_id)
    
    # Check if user is the question author
    if question.user_id != current_user.id:
        return jsonify({'error': 'Only the question author can accept answers'}), 403
    
    # Make sure this is a top-level comment (an answer)
    if comment.parent_comment_id is not None:
        return jsonify({'error': 'Only top-level comments can be accepted as answers'}), 400
    
    # Accept the comment as an answer
    comment.is_accepted = True
    db.session.commit()
    
    # Award reputation points to comment author
    comment_author = User.query.get(comment.user_id)
    comment_author.update_reputation(15)  # Reputation for accepted answer
    
    return jsonify({'success': True})


@api_bp.route('/ai/respond', methods=['POST'])
@login_required
def ai_respond():
    """API endpoint to trigger an AI response to a post"""
    data = request.json
    
    if not data:
        return jsonify({'error': 'Invalid data'}), 400
    
    content_type = data.get('content_type')
    content_id = data.get('content_id')
    
    if not content_type or not content_id:
        return jsonify({'error': 'Must specify content_type and content_id'}), 400
    
    if content_type not in ['question', 'comment']:
        return jsonify({'error': 'Invalid content_type'}), 400
    
    # Get the content item
    content_item = None
    if content_type == 'question':
        content_item = Question.query.get(content_id)
    else:  # comment
        content_item = Comment.query.get(content_id)
    
    if not content_item:
        return jsonify({'error': 'Content not found'}), 404
    
    # Get the AI personality
    ai_personality_id = data.get('personality_id')
    if not ai_personality_id:
        return jsonify({'error': 'Must specify personality_id'}), 400
    
    ai_personality = AIPersonality.query.get(ai_personality_id)
    if not ai_personality:
        return jsonify({'error': 'AI Personality not found'}), 404
    
    # Queue the AI response generation task to run asynchronously with parallel=True for concurrency
    queue_task(
        generate_ai_response, 
        content_type, 
        content_id, 
        ai_personality_id,
        parallel=True  # Enable true parallel processing
    )
    
    # Return immediately with a success message
    return jsonify({
        'success': True,
        'message': 'AI response generation queued',
        'response': {'id': 'pending'}  # Temporary placeholder for the response
    })

def generate_ai_response(content_type, content_id, ai_personality_id):
    """Background task to generate an AI response"""
    try:
        # Get the content item
        content_item = None
        if content_type == 'question':
            content_item = Question.query.get(content_id)
        else:  # comment
            content_item = Comment.query.get(content_id)
            
        if not content_item:
            current_app.logger.warning(f"Content item {content_type}:{content_id} not found")
            return
            
        # Get the AI personality
        ai_personality = AIPersonality.query.get(ai_personality_id)
        if not ai_personality:
            current_app.logger.warning(f"AI personality {ai_personality_id} not found")
            return
            
        # Get the AI user associated with this personality
        ai_user = User.query.filter_by(ai_personality_id=ai_personality.id, is_ai=True).first()
        if not ai_user:
            current_app.logger.warning(f"AI user for personality {ai_personality_id} not found")
            return
        
        # Check if the AI should respond based on its activity frequency
        if not ai_personality.should_respond():
            current_app.logger.info(f"AI {ai_personality.name} decided not to respond to {content_type}:{content_id}")
            return
            
        current_app.logger.info(f"Generating AI response for {content_type}:{content_id} with AI {ai_personality.name}")
            
        # Format the prompt based on content type
        prompt = ""
        context = ""
        if content_type == 'question':
            question = content_item
            tags = ', '.join([tag.tag.name for tag in question.tags])
            context = f"Title: {question.title}\nTags: {tags}\nQuestion: {question.body}"
            prompt = ai_personality.format_prompt(question.body, context)
        else:  # comment
            if content_item.question_id:
                # This is a comment on a question (either an answer or a reply to a question)
                question = Question.query.get(content_item.question_id)
                
                if content_item.parent_comment_id:
                    # This is a reply to another comment
                    parent_comment = Comment.query.get(content_item.parent_comment_id)
                    context = f"Question: {question.title}\nParent Comment: {parent_comment.body}\nReply: {content_item.body}"
                else:
                    # This is an answer (top-level comment on a question)
                    context = f"Question: {question.title}\nAnswer: {content_item.body}"
            else:
                # This should not happen in the new model, but handle it just in case
                context = f"Comment: {content_item.body}"
                
            prompt = ai_personality.format_prompt(content_item.body, context)
        
        # Generate AI response
        response = get_completion(prompt, max_tokens=4096)
        
        # Create the appropriate response based on content type
        result = None
        if content_type == 'question':
            # Create a comment as an answer (top-level comment)
            comment = Comment(
                body=response,
                user_id=ai_user.id,
                question_id=content_item.id
            )
            db.session.add(comment)
            result = comment
        else:  # comment
            # Create a reply comment
            reply = Comment(
                body=response,
                user_id=ai_user.id,
                question_id=content_item.question_id,
                parent_comment_id=content_item.id
            )
            db.session.add(reply)
            result = reply
        
        # Commit the changes
        db.session.commit()
        
        # Add a random vote from the AI on the content
        vote_type = determine_vote_type(ai_personality, content_item.body)
        if vote_type != 0:
            # Check if the user has already voted on this content
            existing_vote = None
            
            if content_type == 'question':
                existing_vote = Vote.query.filter_by(user_id=ai_user.id, question_id=content_item.id).first()
            else:  # comment
                existing_vote = Vote.query.filter_by(user_id=ai_user.id, comment_id=content_item.id).first()
            
            # Only create a new vote if one doesn't already exist
            if not existing_vote:
                vote = Vote(
                    user_id=ai_user.id,
                    vote_type=vote_type
                )
                
                if content_type == 'question':
                    vote.question_id = content_item.id
                else:  # comment
                    vote.comment_id = content_item.id
                    
                db.session.add(vote)
                db.session.commit()
            elif existing_vote.vote_type != vote_type:
                # Update the existing vote if the vote type has changed
                existing_vote.vote_type = vote_type
                existing_vote.created_at = datetime.utcnow()
                db.session.commit()
            
    except Exception as e:
        current_app.logger.error(f"Error generating AI response: {str(e)}")
        db.session.rollback()


@api_bp.route('/comments/children/<int:parent_id>')
def get_comment_children(parent_id):
    """
    API endpoint to get child comments for a parent comment
    Used for loading more comments in a thread
    """
    skip = request.args.get('skip', 0, type=int)
    limit = request.args.get('limit', 5, type=int)  # Default to 5 comments per load
    
    # Get the parent comment
    parent_comment = Comment.query.get_or_404(parent_id)
    
    # Get child comments with pagination
    child_comments = Comment.query.filter_by(
        parent_comment_id=parent_id
    ).order_by(Comment.score.desc(), Comment.created_at.asc()).offset(skip).limit(limit).all()
    
    # Count remaining comments
    total_children = Comment.query.filter_by(parent_comment_id=parent_id).count()
    remaining = total_children - (skip + len(child_comments))
    
    # Format the comments
    comments_data = []
    for comment in child_comments:
        # Format each comment including replies
        comment_data = format_comment_data(comment)
        comments_data.append(comment_data)
    
    return jsonify({
        'success': True,
        'comments': comments_data,
        'total_remaining': remaining
    })


@api_bp.route('/comments/thread/<int:parent_id>')
def get_comment_thread(parent_id):
    """
    API endpoint to get a full thread of comments starting from a parent
    Used for the "continue this thread" feature
    """
    # Get the parent comment
    parent_comment = Comment.query.get_or_404(parent_id)
    
    # Get all child comments (up to a reasonable limit)
    child_comments = Comment.query.filter_by(
        parent_comment_id=parent_id
    ).order_by(Comment.score.desc(), Comment.created_at.asc()).limit(50).all()
    
    # Format the comments
    comments_data = []
    for comment in child_comments:
        # Format each comment including replies
        comment_data = format_comment_data(comment)
        comments_data.append(comment_data)
    
    return jsonify({
        'success': True,
        'comments': comments_data
    })


def format_comment_data(comment, include_replies=True, max_depth=2, current_depth=0):
    """
    Helper function to format a comment and its replies into a JSON-serializable format
    """
    # Get the user vote if authenticated
    user_vote = 0
    if current_user.is_authenticated:
        vote = Vote.query.filter_by(user_id=current_user.id, comment_id=comment.id).first()
        if vote:
            user_vote = vote.vote_type
    
    # Format the base comment data
    comment_data = {
        'id': comment.id,
        'body': comment.body,
        'html_content': comment.html_content,
        'author_id': comment.author_id,
        'author_username': comment.author.username if comment.author else '[deleted]',
        'author_is_ai': comment.author.is_ai if comment.author else False,
        'score': comment.score,
        'created_at': comment.created_at.isoformat(),
        'is_deleted': comment.is_deleted,
        'user_vote': user_vote,
        'replies': []
    }
    
    # Include replies recursively, but limit depth to avoid too much data
    if include_replies and current_depth < max_depth:
        replies = Comment.query.filter_by(parent_comment_id=comment.id).all()
        for reply in replies:
            reply_data = format_comment_data(
                reply, 
                include_replies=True,
                max_depth=max_depth,
                current_depth=current_depth + 1
            )
            comment_data['replies'].append(reply_data)
    
    return comment_data


@api_bp.route('/comments/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    """API endpoint to soft delete a comment"""
    comment = Comment.query.get_or_404(comment_id)
    
    # Check if user is authorized to delete the comment
    if comment.user_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Soft delete the comment
    comment.soft_delete()
    
    return jsonify({'success': True, 'message': 'Comment deleted successfully'})


@api_bp.route('/tags/search')
def search_tags():
    """API endpoint to search for tags"""
    query = request.args.get('q', '')
    
    if not query:
        return jsonify({'tags': []})
    
    tags = db.session.query(tag_model.Tag).filter(
        tag_model.Tag.name.ilike(f'%{query}%')
    ).limit(10).all()
    
    result = [{'id': tag.id, 'name': tag.name} for tag in tags]
    
    return jsonify({'tags': result})


@api_bp.route('/ai_personalities')
def ai_personalities():
    """API endpoint to get all AI personalities"""
    personalities = AIPersonality.query.all()
    
    result = [
        {
            'id': p.id,
            'name': p.name,
            'description': p.description,
            'expertise': p.expertise,
            'personality_traits': p.personality_traits,
            'interaction_style': p.interaction_style,
            'helpfulness_level': p.helpfulness_level,
            'strictness_level': p.strictness_level,
            'avatar_url': p.avatar_url
        } for p in personalities
    ]
    
    return jsonify({'personalities': result})
