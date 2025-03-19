from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models.question import Question
from app.models.answer import Answer
from app.models.comment import Comment
from app.models.vote import Vote
from app.models.user import User
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

answers_bp = Blueprint('answers', __name__, url_prefix='/answers')


@answers_bp.route('/post/<int:question_id>', methods=['POST'])
@login_required
def post(question_id):
    question = Question.query.get_or_404(question_id)
    answer_body = request.form.get('answer_body')
    
    if not answer_body:
        flash('Answer cannot be empty', 'danger')
        return redirect(url_for('questions.view', question_id=question_id))
    
    answer = Answer(
        body=answer_body,
        user_id=current_user.id,
        question_id=question_id
    )
    
    db.session.add(answer)
    db.session.commit()
    
    # Trigger AI responses to the answer asynchronously
    queue_task(ai_respond_to_answer, answer.id, parallel=True)
    
    flash('Your answer has been posted', 'success')
    return redirect(url_for('questions.view', question_id=question_id))


@answers_bp.route('/<int:answer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(answer_id):
    answer = Answer.query.get_or_404(answer_id)
    
    # Check if user is author or admin
    if answer.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    if request.method == 'POST':
        body = request.form.get('answer_body')
        
        # Validate input
        if not body:
            flash('Answer body is required', 'danger')
            return render_template('answers/edit.html', answer=answer)
        
        # Update answer
        answer.body = body
        answer.updated_at = datetime.utcnow()
        
        db.session.commit()
        flash('Your answer has been updated', 'success')
        return redirect(url_for('questions.view', question_id=answer.question_id))
    
    return render_template('answers/edit.html', answer=answer)


@answers_bp.route('/<int:answer_id>/delete', methods=['POST'])
@login_required
def delete(answer_id):
    answer = Answer.query.get_or_404(answer_id)
    
    # Check if user is author or admin
    if answer.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    
    question_id = answer.question_id
    
    db.session.delete(answer)
    db.session.commit()
    
    flash('Your answer has been deleted', 'success')
    return redirect(url_for('questions.view', question_id=question_id))


@answers_bp.route('/<int:answer_id>/accept', methods=['POST'])
@login_required
def accept(answer_id):
    answer = Answer.query.get_or_404(answer_id)
    question = Question.query.get_or_404(answer.question_id)
    
    # Check if user is the question author
    if question.user_id != current_user.id:
        abort(403)
    
    answer.accept()
    
    # Award reputation points to answer author
    answer_author = User.query.get(answer.user_id)
    answer_author.update_reputation(15)  # Reputation for accepted answer
    
    flash('Answer has been accepted', 'success')
    return redirect(url_for('questions.view', question_id=answer.question_id))


@answers_bp.route('/<int:answer_id>/vote', methods=['POST'])
@login_required
def vote(answer_id):
    answer = Answer.query.get_or_404(answer_id)
    vote_type = int(request.form.get('vote_type', 0))
    
    if vote_type not in [1, -1]:
        flash('Invalid vote type', 'danger')
        return redirect(url_for('questions.view', question_id=answer.question_id))
    
    # Check if user has already voted
    existing_vote = Vote.query.filter_by(
        user_id=current_user.id, answer_id=answer_id
    ).first()
    
    if existing_vote:
        if existing_vote.vote_type == vote_type:
            # Remove vote if clicking the same button
            db.session.delete(existing_vote)
            # Update author reputation
            author = User.query.get(answer.user_id)
            author.update_reputation(-vote_type)
        else:
            # Change vote
            existing_vote.vote_type = vote_type
            # Update author reputation (double the effect since reversing)
            author = User.query.get(answer.user_id)
            author.update_reputation(vote_type * 2)
    else:
        # New vote
        vote = Vote(
            user_id=current_user.id,
            answer_id=answer_id,
            vote_type=vote_type
        )
        db.session.add(vote)
        
        # Update author reputation
        author = User.query.get(answer.user_id)
        author.update_reputation(vote_type)
    
    db.session.commit()
    
    # Trigger AI responses to the vote asynchronously
    queue_task(ai_respond_to_vote, vote, parallel=True)
    
    return redirect(url_for('questions.view', question_id=answer.question_id))


@answers_bp.route('/<int:answer_id>/comment', methods=['POST'])
@login_required
def add_comment(answer_id):
    answer = Answer.query.get_or_404(answer_id)
    comment_body = request.form.get('comment_body')
    
    if not comment_body:
        flash('Comment cannot be empty', 'danger')
        return redirect(url_for('questions.view', question_id=answer.question_id))
    
    comment = Comment(
        body=comment_body,
        user_id=current_user.id,
        answer_id=answer_id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    # Trigger AI responses asynchronously (pass comment_id instead of comment)
    queue_task(ai_respond_to_answer_comment, comment.id, parallel=True)
    
    flash('Your comment has been added', 'success')
    return redirect(url_for('questions.view', question_id=answer.question_id))


def ai_respond_to_answer(answer_id):
    """
    Have AI personalities respond to a new answer
    """
    # Get the answer
    answer = Answer.query.get(answer_id)
    if not answer:
        current_app.logger.warning(f"Answer {answer_id} not found for AI response")
        return
    
    # Get the question
    question = Question.query.get(answer.question_id)
    if not question:
        current_app.logger.warning(f"Question for answer {answer_id} not found")
        return
    
    # Get AI personalities
    ai_personalities = AIPersonality.query.all()
    
    # Filter to only personalities that should respond
    responding_ais = [ai for ai in ai_personalities if ai.should_respond()]
    
    # Ensure we have at least 7 AIs responding (or all available if less than 7)
    min_responses = 7
    if len(responding_ais) > min_responses:
        num_responses = max(min_responses, random.randint(min_responses, len(responding_ais)))
        responding_ais = random.sample(responding_ais, num_responses)
    
    current_app.logger.info(f"Selected {len(responding_ais)} AI personalities to respond to answer {answer_id}")
    print(f"Selected {len(responding_ais)} AI personalities to respond to answer {answer_id}")
    
    # For each AI that will respond
    for ai_personality in responding_ais:
        # Get the AI user
        ai_user = User.query.filter_by(ai_personality_id=ai_personality.id, is_ai=True).first()
        if not ai_user:
            current_app.logger.warning(f"No AI user found for personality {ai_personality.id}")
            continue
        
        # Format the prompt with context
        context = f"Question: {question.title}\nQuestion body: {question.body}\nAnswer: {answer.body}"
        prompt = ai_personality.format_prompt(answer.body, context)
        
        # Queue response generation in parallel
        # Use the _generate_ai_answer function from questions.py
        from app.routes.questions import _generate_ai_answer
        queue_task(
            _generate_ai_answer,
            prompt,
            ai_user.id,
            None,
            answer_id,
            None,
            ai_personality.id,
            parallel=True
        )


def ai_respond_to_vote(vote):
    """Have AI users respond to votes on answers"""
    # Get all AI personalities
    ai_personalities = AIPersonality.query.all()
    
    # Select a random subset of personalities (at most 2)
    selected_personalities = random.sample(ai_personalities, min(2, len(ai_personalities)))
    
    # For each selected AI
    for ai_personality in selected_personalities:
        if random.random() < 0.3:  # Lower chance for vote responses
            # Get the AI user associated with this personality
            ai_user = User.query.filter_by(ai_personality_id=ai_personality.id, is_ai=True).first()
            if not ai_user:
                continue
            
            # Get the answer that was voted on
            answer = Answer.query.get(vote.answer_id)
            if not answer:
                continue
                
            # Get the question for context
            question = Question.query.get(answer.question_id)
            
            # Format the context
            vote_type_str = "upvoted" if vote.vote_type == 1 else "downvoted"
            context = f"Question: {question.title}\nAnswer: {answer.body}\nSomeone {vote_type_str} this answer."
            
            # Format the prompt using the AI's personality
            prompt = ai_personality.format_prompt(answer.body, context)
            
            # Queue response generation in parallel
            from app.routes.questions import _generate_ai_answer
            queue_task(
                _generate_ai_answer,
                prompt, 
                ai_user.id, 
                None,  # question_id 
                answer.id,  # answer_id
                None,  # comment_id
                ai_personality.id,
                parallel=True
            )


def ai_respond_to_answer_comment(comment_id):
    """Have AI users respond to comments on answers"""
    # Get the comment
    comment = Comment.query.get(comment_id)
    if not comment:
        current_app.logger.warning(f"Comment {comment_id} not found for AI response")
        return
    
    # Get all AI personalities
    ai_personalities = AIPersonality.query.all()
    
    # Select a random subset of personalities (at most 2)
    selected_personalities = random.sample(ai_personalities, min(2, len(ai_personalities)))
    
    # For each selected AI
    for ai_personality in selected_personalities:
        if ai_personality.should_respond() and random.random() < 0.4:  # Lower chance for comment responses
            # Get the AI user associated with this personality
            ai_user = User.query.filter_by(ai_personality_id=ai_personality.id, is_ai=True).first()
            if not ai_user:
                continue
            
            # Get the answer and question for context
            answer = Answer.query.get(comment.answer_id)
            if not answer:
                continue
                
            question = Question.query.get(answer.question_id)
            
            # Format the context
            context = f"Question: {question.title}\nAnswer: {answer.body}\nComment: {comment.body}"
            
            # Format the prompt using the AI's personality
            prompt = ai_personality.format_prompt(comment.body, context)
            
            # Queue response generation in parallel
            from app.routes.questions import _generate_ai_answer
            queue_task(
                _generate_ai_answer,
                prompt, 
                ai_user.id, 
                None,  # question_id 
                None,  # answer_id
                comment.id,  # comment_id
                ai_personality.id,
                parallel=True
            )


def determine_vote_type(ai_personality, content):
    """
    Determine if an AI personality should upvote, downvote, or not vote
    Based on AI personality traits and the content
    """
    helpfulness = ai_personality.helpfulness_level
    strictness = ai_personality.strictness_level
    
    # Simple algorithm: high strictness makes downvotes more likely
    # This is a placeholder - in a real implementation you'd use the AI to decide
    import random
    
    # Check for code blocks which might increase positive votes for technical AIs
    has_code = '```' in content or '    ' in content
    if has_code and 'programming' in ai_personality.expertise.lower():
        helpfulness += 2
    
    # Check for negative patterns that might trigger strict personalities
    negative_patterns = ['wrong', 'incorrect', 'bad', 'terrible', 'awful']
    if any(pattern in content.lower() for pattern in negative_patterns):
        strictness += 2
    
    # Positive patterns that might trigger helpful personalities
    positive_patterns = ['thanks', 'helpful', 'great', 'excellent', 'good']
    if any(pattern in content.lower() for pattern in positive_patterns):
        helpfulness += 2
    
    # Calculate probability based on personality traits
    downvote_probability = strictness / 20  # Max 50% chance for downvote
    upvote_probability = helpfulness / 15   # Max 66% chance for upvote
    
    # Roll the dice
    roll = random.random()
    if roll < downvote_probability:
        return -1
    elif roll < downvote_probability + upvote_probability:
        return 1
    else:
        return 0
