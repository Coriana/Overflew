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
    answers = question.answers.order_by(Answer.is_accepted.desc(), 
                                       db.desc(db.func.coalesce(
                                           db.func.sum(db.case([(Vote.vote_type == 1, 1)], else_=0)) -
                                           db.func.sum(db.case([(Vote.vote_type == -1, 1)], else_=0)),
                                           0
                                       ))).outerjoin(Vote).group_by(Answer.id).all()
    
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
                user_id=current_user.id, answer_id=answer.id).first()
            answer_data['user_vote'] = user_answer_vote.vote_type if user_answer_vote else 0
    
    return jsonify(result)


@api_bp.route('/vote', methods=['POST'])
@login_required
def vote():
    """API endpoint to vote on a question, answer, or comment"""
    data = request.json
    
    if not data or 'vote_type' not in data or data['vote_type'] not in [1, -1, 0]:
        return jsonify({'error': 'Invalid vote data'}), 400
    
    # Determine what is being voted on
    question_id = data.get('question_id')
    answer_id = data.get('answer_id')
    comment_id = data.get('comment_id')
    
    if not any([question_id, answer_id, comment_id]):
        return jsonify({'error': 'Must specify question_id, answer_id, or comment_id'}), 400
    
    vote_type = data['vote_type']
    
    # Handle removing vote if vote_type is 0
    if vote_type == 0:
        if question_id:
            Vote.query.filter_by(
                user_id=current_user.id, question_id=question_id).delete()
        elif answer_id:
            Vote.query.filter_by(
                user_id=current_user.id, answer_id=answer_id).delete()
        elif comment_id:
            Vote.query.filter_by(
                user_id=current_user.id, comment_id=comment_id).delete()
        
        db.session.commit()
        return jsonify({'success': True, 'vote_type': 0})
    
    # Check if user has already voted
    existing_vote = None
    if question_id:
        existing_vote = Vote.query.filter_by(
            user_id=current_user.id, question_id=question_id).first()
    elif answer_id:
        existing_vote = Vote.query.filter_by(
            user_id=current_user.id, answer_id=answer_id).first()
    elif comment_id:
        existing_vote = Vote.query.filter_by(
            user_id=current_user.id, comment_id=comment_id).first()
    
    # Update or create the vote
    if existing_vote:
        # Change vote
        existing_vote.vote_type = vote_type
    else:
        # New vote
        new_vote = Vote(
            user_id=current_user.id,
            question_id=question_id,
            answer_id=answer_id,
            comment_id=comment_id,
            vote_type=vote_type
        )
        db.session.add(new_vote)
    
    try:
        db.session.commit()
        
        # Update reputation for the content author
        if question_id:
            question = Question.query.get(question_id)
            if question and question.user_id != current_user.id:
                author = User.query.get(question.user_id)
                if author:
                    author.reputation += vote_type
                    db.session.commit()
        elif answer_id:
            answer = Answer.query.get(answer_id)
            if answer and answer.user_id != current_user.id:
                author = User.query.get(answer.user_id)
                if author:
                    author.reputation += vote_type
                    db.session.commit()
        
        # Trigger AI responses to the vote
        if question_id:
            vote_obj = Vote.query.filter_by(user_id=current_user.id, question_id=question_id).first()
            if vote_obj:
                from app.routes.questions import ai_respond_to_vote
                queue_task(ai_respond_to_vote, vote_obj, parallel=True)
        elif answer_id:
            vote_obj = Vote.query.filter_by(user_id=current_user.id, answer_id=answer_id).first()
            if vote_obj:
                from app.routes.answers import ai_respond_to_vote
                queue_task(ai_respond_to_vote, vote_obj, parallel=True)
        
        return jsonify({
            'success': True, 
            'vote_type': vote_type,
            'message': 'Vote processed successfully'
        })
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing vote: {str(e)}")
        return jsonify({'error': 'Failed to process vote'}), 500


@api_bp.route('/comments/add', methods=['POST'])
@login_required
def add_comment():
    """API endpoint to add a comment to a question or answer"""
    data = request.json
    
    if not data or 'body' not in data or not data['body']:
        return jsonify({'error': 'Comment body is required'}), 400
    
    # Determine what is being commented on
    question_id = data.get('question_id')
    answer_id = data.get('answer_id')
    
    if not any([question_id, answer_id]):
        return jsonify({'error': 'Must specify question_id or answer_id'}), 400
    
    # Create the comment
    comment = Comment(
        body=data['body'],
        user_id=current_user.id,
        question_id=question_id,
        answer_id=answer_id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    # Trigger AI responses to the comment
    if question_id:
        from app.routes.questions import ai_respond_to_comment
        ai_respond_to_comment(comment.id, question_id=question_id)
    elif answer_id:
        from app.routes.answers import ai_respond_to_comment
        ai_respond_to_comment(comment.id, answer_id=answer_id)
    
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


@api_bp.route('/answers/accept/<int:answer_id>', methods=['POST'])
@login_required
def accept_answer(answer_id):
    """API endpoint to accept an answer"""
    answer = Answer.query.get_or_404(answer_id)
    question = Question.query.get_or_404(answer.question_id)
    
    # Check if user is the question author
    if question.user_id != current_user.id:
        return jsonify({'error': 'Only the question author can accept answers'}), 403
    
    answer.accept()
    
    # Award reputation points to answer author
    answer_author = User.query.get(answer.user_id)
    answer_author.update_reputation(15)  # Reputation for accepted answer
    
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
    
    if content_type not in ['question', 'answer', 'comment']:
        return jsonify({'error': 'Invalid content_type'}), 400
    
    # Get the content item
    content_item = None
    if content_type == 'question':
        content_item = Question.query.get(content_id)
    elif content_type == 'answer':
        content_item = Answer.query.get(content_id)
    else:  # comment
        content_item = Comment.query.get(content_id)
    
    if not content_item:
        return jsonify({'error': 'Content not found'}), 404
    
    # Get the AI personality
    ai_personality_id = data.get('ai_personality_id')
    if not ai_personality_id:
        return jsonify({'error': 'Must specify ai_personality_id'}), 400
    
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
        'message': 'AI response generation queued'
    })

def generate_ai_response(content_type, content_id, ai_personality_id):
    """Background task to generate an AI response"""
    try:
        # Get the content item
        content_item = None
        if content_type == 'question':
            content_item = Question.query.get(content_id)
        elif content_type == 'answer':
            content_item = Answer.query.get(content_id)
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
        elif content_type == 'answer':
            answer = content_item
            question = Question.query.get(answer.question_id)
            context = f"Question: {question.title}\nQuestion: {question.body}\nAnswer: {answer.body}"
            prompt = ai_personality.format_prompt(answer.body, context)
        else:  # comment
            if content_item.question_id:
                question = Question.query.get(content_item.question_id)
                context = f"Question: {question.title}\nComment: {content_item.body}"
            else:
                answer = Answer.query.get(content_item.answer_id)
                question = Question.query.get(answer.question_id)
                context = f"Question: {question.title}\nAnswer: {answer.body}\nComment: {content_item.body}"
            prompt = ai_personality.format_prompt(content_item.body, context)
        
        # Generate AI response
        response = get_completion(prompt, max_tokens=4096)
        
        # Create the appropriate response based on content type
        result = None
        if content_type == 'question':
            # Create an answer
            answer = Answer(
                body=response,
                user_id=ai_user.id,
                question_id=content_item.id
            )
            db.session.add(answer)
            result = answer
        elif content_type == 'answer':
            # Create a comment on the answer
            comment = Comment(
                body=response,
                user_id=ai_user.id,
                answer_id=content_item.id
            )
            db.session.add(comment)
            result = comment
        else:  # comment
            # Create a reply comment
            reply = Comment(
                body=response,
                user_id=ai_user.id
            )
            
            if content_item.question_id:
                reply.question_id = content_item.question_id
            else:
                reply.answer_id = content_item.answer_id
                
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
            elif content_type == 'answer':
                existing_vote = Vote.query.filter_by(user_id=ai_user.id, answer_id=content_item.id).first()
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
                elif content_type == 'answer':
                    vote.answer_id = content_item.id
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
