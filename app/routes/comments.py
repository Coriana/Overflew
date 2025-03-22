from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.question import Question
from app.models.comment import Comment
from app.models.vote import Vote
from app.models.user import User
from app.services.llm_service import queue_task

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
    
    # Trigger appropriate AI response
    if not parent_comment_id:
        # This is a top-level comment (an answer)
        queue_task(ai_respond_to_answer, comment.id, parallel=True)
    else:
        queue_task(ai_respond_to_comment, comment.id, question_id=question_id, parallel=True)
    
    flash('Your content has been added', 'success')
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
        
        # Trigger AI response to vote if it's a vote on an answer (top-level comment)
        if comment.parent_comment_id is None:
            queue_task(ai_respond_to_vote, vote.id, parallel=True)
    
    db.session.commit()
    
    return jsonify({'success': True, 'score': comment.score})


# AI response functions
def ai_respond_to_answer(comment_id):
    """Have AI personalities respond to an answer (top-level comment)"""
    # Import here to avoid circular imports
    from app.models.ai_personality import AIPersonality
    from app.services.llm_service import get_completion
    
    comment = Comment.query.get(comment_id)
    if not comment:
        print(f"Comment ID {comment_id} not found")
        return
    
    question = Question.query.get(comment.question_id)
    if not question:
        print(f"Question ID {comment.question_id} not found")
        return
    
    # Get AI personalities that are likely to respond
    personalities = AIPersonality.query.filter_by(is_active=True).all()
    
    # If no active personalities found, check for any personalities
    if not personalities:
        personalities = AIPersonality.query.all()
        print(f"No active AI personalities found, using any available ({len(personalities)} found)")
    
    # If still no personalities, create a default one
    if not personalities:
        print("No AI personalities found, creating a default one")
        default_personality = AIPersonality(
            name="AI Assistant",
            description="A helpful AI assistant",
            expertise="General knowledge,Programming,Problem solving",
            personality_traits="Helpful,Friendly,Knowledgeable",
            interaction_style="Conversational",
            helpfulness_level=9,
            strictness_level=5,
            verbosity_level=7,
            prompt_template="You are a helpful AI assistant providing information on {{topic}}",
            is_active=True
        )
        db.session.add(default_personality)
        db.session.commit()
        personalities = [default_personality]
    
    # Select a random personality to respond
    import random
    personality = random.choice(personalities)
    print(f"Selected AI personality: {personality.name}")
    
    # Check if the AI user exists, create if not
    ai_user = User.query.filter_by(username=personality.name).first()
    if not ai_user:
        print(f"Creating AI user for {personality.name}")
        from werkzeug.security import generate_password_hash
        ai_user = User(
            username=personality.name,
            email=f"{personality.name.lower().replace(' ', '.')}@overflew.ai",
            password_hash=generate_password_hash("AI_USER_PASSWORD"),
            is_ai=True,
            ai_personality_id=personality.id
        )
        db.session.add(ai_user)
        db.session.commit()
    
    # Construct the prompt for the AI
    prompt = f"""
    You are {personality.name}, {personality.description}
    
    Question: {question.title}
    {question.body}
    
    Answer: {comment.body}
    
    As {personality.name}, provide a thoughtful response to this answer. 
    Your response should reflect your unique personality and perspective.
    """
    
    # Get completion from LLM service
    response = get_completion(prompt)
    
    # Create a new comment as a reply to the answer
    if response:
        print(f"Creating AI response from {ai_user.username} (id: {ai_user.id})")
        ai_comment = Comment(
            body=response,
            user_id=ai_user.id,
            question_id=question.id,
            parent_comment_id=comment_id  # This is a reply to the answer
        )
        
        db.session.add(ai_comment)
        db.session.commit()
        print(f"AI {personality.name} responded to comment ID {comment_id}")
    else:
        print("Failed to get a response from the LLM service")


def ai_respond_to_comment(comment_id, question_id):
    """Have AI personalities respond to a comment"""
    # Import here to avoid circular imports
    from app.models.ai_personality import AIPersonality
    from app.services.llm_service import get_completion
    
    comment = Comment.query.get(comment_id)
    if not comment:
        print(f"Comment ID {comment_id} not found")
        return
    
    question = Question.query.get(question_id)
    if not question:
        print(f"Question ID {question_id} not found")
        return
    
    # Check if the question is marked as answered
    if question.is_answered:
        print(f"Question {question_id} is marked as answered, skipping AI response to comment")
        return
    
    # Get the parent comment if it exists
    parent_comment = None
    if comment.parent_comment_id:
        parent_comment = Comment.query.get(comment.parent_comment_id)
    
    # Decide if an AI personality should respond
    # For now, have a 30% chance of responding to regular comments
    import random
    if random.random() > 0.3:
        print(f"Decided not to respond to comment ID {comment_id}")
        return
    
    # Get AI personalities that are likely to respond
    personalities = AIPersonality.query.filter_by(is_active=True).all()
    
    # If no active personalities found, check for any personalities
    if not personalities:
        personalities = AIPersonality.query.all()
        print(f"No active AI personalities found, using any available ({len(personalities)} found)")
    
    # If still no personalities, create a default one
    if not personalities:
        print("No AI personalities found, creating a default one")
        default_personality = AIPersonality(
            name="AI Assistant",
            description="A helpful AI assistant",
            expertise="General knowledge,Programming,Problem solving",
            personality_traits="Helpful,Friendly,Knowledgeable",
            interaction_style="Conversational",
            helpfulness_level=9,
            strictness_level=5,
            verbosity_level=7,
            prompt_template="You are a helpful AI assistant providing information on {{topic}}",
            is_active=True
        )
        db.session.add(default_personality)
        db.session.commit()
        personalities = [default_personality]
    
    # Select a personality to respond
    personality = random.choice(personalities)
    print(f"Selected AI personality: {personality.name}")
    
    # Check if the AI user exists, create if not
    ai_user = User.query.filter_by(username=personality.name).first()
    if not ai_user:
        print(f"Creating AI user for {personality.name}")
        from werkzeug.security import generate_password_hash
        ai_user = User(
            username=personality.name,
            email=f"{personality.name.lower().replace(' ', '.')}@overflew.ai",
            password_hash=generate_password_hash("AI_USER_PASSWORD"),
            is_ai=True,
            ai_personality_id=personality.id
        )
        db.session.add(ai_user)
        db.session.commit()
    
    # Construct the context for the AI
    context = f"""
    Question: {question.title}
    {question.body}
    """
    
    if parent_comment:
        context += f"\nOriginal comment: {parent_comment.body}\n"
    
    context += f"\nUser comment: {comment.body}"
    
    # Construct the prompt for the AI
    prompt = f"""
    You are {personality.name}, {personality.description}
    
    {context}
    
    As {personality.name}, provide a thoughtful response to this comment.
    Your response should reflect your unique personality and perspective.
    Keep your response concise but helpful.
    """
    
    # Get completion from LLM service
    response = get_completion(prompt)
    
    # Create a new comment as a reply
    if response:
        print(f"Creating AI response from {ai_user.username} (id: {ai_user.id})")
        ai_comment = Comment(
            body=response,
            user_id=ai_user.id,
            question_id=question.id,
            parent_comment_id=comment_id  # This is a reply to the user's comment
        )
        
        db.session.add(ai_comment)
        db.session.commit()
        print(f"AI {personality.name} responded to comment ID {comment_id}")
    else:
        print("Failed to get a response from the LLM service")


def ai_respond_to_vote(vote_id):
    """Have AI personalities respond to votes on answers/comments"""
    # Import here to avoid circular imports
    from app.models.ai_personality import AIPersonality
    from app.services.llm_service import get_completion
    
    vote = Vote.query.get(vote_id)
    if not vote:
        print(f"Vote ID {vote_id} not found")
        return
    
    # Only respond to votes on comments (including answers)
    if not vote.comment_id:
        print(f"Vote ID {vote_id} is not on a comment, skipping")
        return
    
    comment = Comment.query.get(vote.comment_id)
    if not comment:
        print(f"Comment ID {vote.comment_id} not found")
        return
    
    question = Question.query.get(comment.question_id)
    if not question:
        print(f"Question ID {comment.question_id} not found")
        return
    
    # Check if the question is marked as answered
    if question.is_answered:
        print(f"Question {question.id} is marked as answered, skipping AI response to vote")
        return
    
    # Only respond to significant votes (many upvotes or downvotes)
    comment_score = comment.score
    
    # Check if this comment has a significant number of votes
    # For this example, respond if it has at least 3 votes total (positive or negative)
    if abs(comment_score) < 3:
        print(f"Comment ID {comment.id} doesn't have enough votes ({comment_score}), skipping")
        return
    
    # Decide if an AI personality should respond
    # For votes, maybe have a higher chance based on the vote count
    response_chance = min(0.1 * abs(comment_score), 0.8)  # Cap at 80% chance
    
    import random
    if random.random() > response_chance:
        print(f"Decided not to respond to votes on comment ID {comment.id}")
        return
    
    # Get AI personalities that are likely to respond
    personalities = AIPersonality.query.filter_by(is_active=True).all()
    
    # If no active personalities found, check for any personalities
    if not personalities:
        personalities = AIPersonality.query.all()
        print(f"No active AI personalities found, using any available ({len(personalities)} found)")
    
    # If still no personalities, create a default one
    if not personalities:
        print("No AI personalities found, creating a default one")
        default_personality = AIPersonality(
            name="AI Assistant",
            description="A helpful AI assistant",
            expertise="General knowledge,Programming,Problem solving",
            personality_traits="Helpful,Friendly,Knowledgeable",
            interaction_style="Conversational",
            helpfulness_level=9,
            strictness_level=5,
            verbosity_level=7,
            prompt_template="You are a helpful AI assistant providing information on {{topic}}",
            is_active=True
        )
        db.session.add(default_personality)
        db.session.commit()
        personalities = [default_personality]
    
    # Select a personality to respond
    personality = random.choice(personalities)
    print(f"Selected AI personality: {personality.name}")
    
    # Check if the AI user exists, create if not
    ai_user = User.query.filter_by(username=personality.name).first()
    if not ai_user:
        print(f"Creating AI user for {personality.name}")
        from werkzeug.security import generate_password_hash
        ai_user = User(
            username=personality.name,
            email=f"{personality.name.lower().replace(' ', '.')}@overflew.ai",
            password_hash=generate_password_hash("AI_USER_PASSWORD"),
            is_ai=True,
            ai_personality_id=personality.id
        )
        db.session.add(ai_user)
        db.session.commit()
    
    # Determine if the comment is well-received or not
    sentiment = "well-received" if comment_score > 0 else "controversial"
    
    # Construct the prompt for the AI
    prompt = f"""
    You are {personality.name}, {personality.description}
    
    Question: {question.title}
    {question.body}
    
    Comment that has been {sentiment} (score: {comment_score}): 
    {comment.body}
    
    As {personality.name}, provide a thoughtful response to this {sentiment} comment.
    If the comment is well-received, you might add additional helpful information or agree with it.
    If the comment is controversial, you might offer a balanced perspective or clarify misconceptions.
    Your response should reflect your unique personality and perspective.
    """
    
    # Get completion from LLM service
    response = get_completion(prompt)
    
    # Create a new comment as a reply
    if response:
        print(f"Creating AI response from {ai_user.username} (id: {ai_user.id}) to {sentiment} comment")
        ai_comment = Comment(
            body=response,
            user_id=ai_user.id,
            question_id=question.id,
            parent_comment_id=comment.id
        )
        
        db.session.add(ai_comment)
        db.session.commit()
        print(f"AI {personality.name} responded to {sentiment} comment ID {comment.id}")
    else:
        print("Failed to get a response from the LLM service")
