from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.question import Question
from app.models.answer import Answer
from app.models.comment import Comment
from app.models.tag import Tag, QuestionTag
from app.models.vote import Vote
from app.models.ai_personality import AIPersonality
from app.models.user import User
from app.services.llm_service import get_completion, queue_task
import os
import random
import json
from datetime import datetime
import re

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
        
        # Trigger AI responses
        from app.models.ai_personality import AIPersonality
        from app.models.user import User
        
        # Get AI personalities that are active
        personalities = AIPersonality.query.filter_by(is_active=True).all()
        
        # If no active ones, use any
        if not personalities:
            personalities = AIPersonality.query.all()
            print(f"No active AI personalities found, using any available ({len(personalities)} found)")
        
        # If still no personalities, skip AI answer
        if personalities:
            # Select a random personality to respond
            import random
            personality = random.choice(personalities)
            print(f"Selected AI personality for initial answer: {personality.name}")
            
            # Find the corresponding AI user
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
            
            # Generate AI answer using the selected personality
            success, message = _generate_ai_answer(question.id, personality.id)
            if success:
                flash(message, 'success')
            else:
                flash(message, 'warning')
        else:
            print("No AI personalities found, skipping initial AI answer")
        
        # Check if auto-population is enabled and trigger it if so
        from app.models.site_settings import SiteSettings
        
        # Use flask.current_app to access the application context
        from flask import current_app
        
        if SiteSettings.get('ai_auto_populate_enabled', False) and not question.is_answered:
            print(f"Auto-population is enabled, populating thread for question {question.id}")
            # Use the LLM worker thread pool to run auto-population in the background
            from app.services.llm_service import queue_task
            queue_task(auto_populate_thread, question.id, parallel=True)
        elif question.is_answered:
            print(f"Question {question.id} is marked as answered, skipping auto-population")
        
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
    
    # Get AI personalities for the AI responder modal
    from app.models.ai_personality import AIPersonality
    from app.models.user import User
    
    # Get AI users with their personalities
    ai_users = User.query.filter_by(is_ai=True).all()
    
    return render_template('questions/view.html', 
                          question=question, 
                          comments=top_level_comments,
                          ai_personalities=ai_users)


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
        
        # Process tags
        # First remove all existing tags
        QuestionTag.query.filter_by(question_id=question.id).delete()
        
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
        flash('Your question has been updated', 'success')
        return redirect(url_for('questions.view', question_id=question.id))
    
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
    
    # Trigger AI responses to the vote asynchronously
    queue_task(ai_respond_to_vote, vote)
    
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


def _generate_ai_answer(question_id, ai_personality_id=None):
    """
    Generate an AI answer for a question
    
    Args:
        question_id (int): The ID of the question to answer
        ai_personality_id (int, optional): The ID of the AI personality to use. If None, a random one is selected.
        
    Returns:
        tuple: (success, message)
    """
    try:
        from app.models.ai_personality import AIPersonality
        from app.services.llm_service import get_completion
        
        # Get the question
        question = Question.query.get(question_id)
        if not question:
            return False, "Question not found"
        
        # Get or select an AI personality
        if ai_personality_id:
            ai_personality = AIPersonality.query.get(ai_personality_id)
            if not ai_personality:
                return False, f"AI personality with ID {ai_personality_id} not found"
        else:
            # Get a random active AI personality
            ai_personalities = AIPersonality.query.filter_by(is_active=True).all()
            if not ai_personalities:
                # Create a default AI personality if none exists
                default_personality = AIPersonality(
                    name="Default AI",
                    description="A helpful AI assistant",
                    expertise="General knowledge",
                    personality_traits="Helpful, friendly, informative",
                    interaction_style="Conversational",
                    helpfulness_level=8,
                    strictness_level=5,
                    verbosity_level=7,
                    prompt_template="You are {{name}}, an AI with expertise in {{expertise}} and traits: {{personality_traits}}. Please respond to: {{content}}"
                )
                db.session.add(default_personality)
                db.session.commit()
                ai_personality = default_personality
            else:
                ai_personality = random.choice(ai_personalities)
        
        # Get the AI user or create one if it doesn't exist
        ai_user = User.query.filter_by(username=ai_personality.name).first()
        if not ai_user:
            # Create a user for this AI personality
            ai_user = User(
                username=ai_personality.name,
                email=f"{ai_personality.name.lower().replace(' ', '.')}@example.com",
                is_ai=True,
                ai_personality_id=ai_personality.id
            )
            ai_user.set_password("AIUSER")
            db.session.add(ai_user)
            db.session.commit()
        
        # Build context with question details
        context = f"Question Title: {question.title}\n"
        context += f"Question Body: {question.body}\n"
        if question.tags:
            context += f"\n\nTags: {', '.join([tag.tag.name for tag in question.tags])}"
        
        # Format the prompt with the AI personality
        prompt = ai_personality.format_prompt(
            content="Please provide a helpful and informative answer to this question.",
            context=context
        )
        
        # Get completion from LLM with custom settings if available
        answer_text = get_completion(
            prompt=prompt, 
            model=ai_personality.custom_model,
            api_key=ai_personality.custom_api_key,
            base_url=ai_personality.custom_base_url
        )
        
        # Create the answer as a comment
        comment = Comment(
            body=answer_text,
            question_id=question.id,
            user_id=ai_user.id,
            parent_comment_id=None  # This is a top-level comment
        )
        
        db.session.add(comment)
        db.session.commit()
        
        return True, f"AI answer generated successfully by {ai_personality.name}"
    except Exception as e:
        current_app.logger.error(f"Error generating AI answer: {str(e)}")
        return False, f"Error generating AI answer: {str(e)}"


def ai_respond_to_vote(vote):
    """
    Generate an AI response to a vote
    
    Args:
        vote (Vote): The vote to respond to
        
    Returns:
        Comment: The generated comment, or None if no response was generated
    """
    try:
        from app.models.ai_personality import AIPersonality
        from app.services.llm_service import get_completion
        
        # Skip if the vote is by an AI
        if vote.user.is_ai:
            return None
        
        # Get the content that was voted on
        content = None
        content_type = None
        
        if vote.question_id:
            content = Question.query.get(vote.question_id)
            content_type = "question"
        elif vote.comment_id:
            content = Comment.query.get(vote.comment_id)
            content_type = "comment"
        else:
            return None
            
        # Skip if the content doesn't exist or is deleted
        if not content or getattr(content, 'is_deleted', False):
            return None
            
        # Skip if the content was created by the voter (self-vote)
        if content_type == "question" and content.user_id == vote.user_id:
            return None
        elif content_type == "comment" and content.user_id == vote.user_id:
            return None
            
        # Get the AI personality of the content creator
        ai_user = User.query.get(content.user_id)
        if not ai_user or not ai_user.is_ai or not ai_user.ai_personality_id:
            return None
            
        ai_personality = AIPersonality.query.get(ai_user.ai_personality_id)
        if not ai_personality:
            return None
            
        # Get the question for context
        if content_type == "question":
            question = content
        elif content_type == "comment":
            question = Question.query.get(content.question_id)
            
        if not question:
            return None
            
        # Build context with question details
        context = f"Question Title: {question.title}\n"
        context += f"Question Body: {question.body}\n"
        if question.tags:
            context += f"\n\nTags: {', '.join([tag.tag.name for tag in question.tags])}"
            
        # Determine if this is an upvote or downvote
        vote_type = "upvote" if vote.vote_type > 0 else "downvote"
        
        # Create the prompt based on content type and vote type
        if content_type == "question":
            prompt = f"""
            You are {ai_personality.name}, an AI with the following traits:
            - Expertise: {ai_personality.expertise}
            - Personality: {ai_personality.personality_traits}
            - Interaction Style: {ai_personality.interaction_style}
            
            A user has {vote_type}d your question. Please respond to this {vote_type} in a way that reflects your personality.
            
            {context}
            
            Your question that was {vote_type}d: {content.title}
            
            Respond to this {vote_type} in a conversational way. If it's an upvote, express gratitude and perhaps expand on your question.
            If it's a downvote, be gracious and ask how you could improve your question or provide better information.
            """
        elif content_type == "comment":
            prompt = f"""
            You are {ai_personality.name}, an AI with the following traits:
            - Expertise: {ai_personality.expertise}
            - Personality: {ai_personality.personality_traits}
            - Interaction Style: {ai_personality.interaction_style}
            
            A user has {vote_type}d your comment. Please respond to this {vote_type} in a way that reflects your personality.
            
            {context}
            
            Your comment that was {vote_type}d: {content.body}
            
            Respond to this {vote_type} in a conversational way. If it's an upvote, express gratitude and perhaps expand on your comment.
            If it's a downvote, be gracious and ask how you could improve your comment or provide better information.
            """
            
        # Format the prompt using the personality's template
        formatted_prompt = ai_personality.prompt_template
        formatted_prompt = formatted_prompt.replace('{{content}}', prompt)
        formatted_prompt = formatted_prompt.replace('{{context}}', context)
        
        # For any other template variables, use personality attributes
        formatted_prompt = formatted_prompt.replace('{{name}}', ai_personality.name)
        formatted_prompt = formatted_prompt.replace('{{description}}', ai_personality.description)
        formatted_prompt = formatted_prompt.replace('{{expertise}}', ai_personality.expertise)
        formatted_prompt = formatted_prompt.replace('{{personality_traits}}', ai_personality.personality_traits)
        
        # Log the actual prompt sent to the model
        print("FINAL PROMPT FOR AI COMMENT RESPONSE:")
        print("=" * 40)
        print(formatted_prompt)
        print("=" * 40)
        
        # Get completion from LLM service
        response = get_completion(
            prompt=formatted_prompt,
            model=ai_personality.custom_model,
            api_key=ai_personality.custom_api_key,
            base_url=ai_personality.custom_base_url
        )
        
        # Create the reply
        if content_type == "question":
            reply = Comment(
                body=response,
                user_id=ai_user.id,
                question_id=question.id,
                parent_comment_id=None
            )
        elif content_type == "comment":
            reply = Comment(
                body=response,
                user_id=ai_user.id,
                question_id=question.id,
                parent_comment_id=content.id
            )
            
        db.session.add(reply)
        db.session.commit()
        
        return reply
    except Exception as e:
        current_app.logger.error(f"Error in ai_respond_to_vote: {str(e)}")
        return None


def ai_respond_to_comment(comment_id):
    """
    Generate an AI response to a comment.
    
    :param comment_id: The ID of the comment to respond to
    :return: The generated response, if any
    """
    from app.models.user import User
    from app.models.ai_personality import AIPersonality
    
    # Use a no_autoflush block to prevent autoflush-related database errors
    with db.session.no_autoflush:
        # Get the comment
        comment = Comment.query.get(comment_id)
        if not comment or comment.is_deleted:
            print(f"Comment ID {comment_id} not found")
            return None
        
        # Don't respond to AI comments to prevent loops
        comment_author = User.query.get(comment.user_id)
        if comment_author.is_ai:
            print(f"Comment {comment_id} was made by an AI user, skipping response to prevent loops")
            return None
        
        # Determine parent content (question or another comment)
        parent = None
        question = None
        
        if comment.parent_comment_id:
            parent = Comment.query.get(comment.parent_comment_id)
            question = Question.query.get(comment.question_id)
        else:
            parent = None  # This is a top-level comment (direct answer to a question)
            question = Question.query.get(comment.question_id)
        
        if not question:
            print(f"Question not found for comment {comment_id}")
            return None
        
        # Check if the question is marked as answered
        if question.is_answered:
            print(f"Question {question.id} is marked as answered, skipping AI response to comment")
            return None
        
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
                expertise="General knowledge",
                personality_traits="Helpful, friendly, informative",
                interaction_style="Conversational",
                helpfulness_level=8,
                strictness_level=5,
                verbosity_level=7,
                prompt_template="You are {{name}}, an AI with expertise in {{expertise}} and traits: {{personality_traits}}. Please respond to: {{content}}"
            )
            db.session.add(default_personality)
            db.session.commit()
            personalities = [default_personality]
        
        # Select a personality to respond
        personality = random.choice(personalities)
        print(f"Selected AI personality: {personality.name}")
        print(f"Personality template: {personality.prompt_template}")
        
        # Check if the AI user exists, create if not
        ai_user = User.query.filter_by(username=personality.name).first()
        if not ai_user:
            # Create a user for this AI personality
            ai_user = User(
                username=personality.name,
                email=f"{personality.name.lower().replace(' ', '.')}@example.com",
                is_ai=True,
                ai_personality_id=personality.id
            )
            ai_user.set_password("AIUSER")
            db.session.add(ai_user)
            db.session.commit()
        
        # Prepare content text and context text for the template
        content_text = ""
        context_text = f"Question: {question.title}\n\n{question.body}"
        
        # Add tags to context if available
        if question.tags:
            context_text += f"\n\nTags: {', '.join([tag.tag.name for tag in question.tags])}"
        
        # Determine if this is a top-level comment or a reply
        if comment.parent_comment_id is None:
            # This is an answer (top-level comment) to a question
            content_text = f"User's answer: {comment.body}\n\nAs {personality.name}, continue the discussion by providing additional insights, clarifications, or a different perspective on this answer."
        else:
            # This is a reply to another comment
            parent_comment = Comment.query.get(comment.parent_comment_id)
            content_text = f"Original comment: {parent_comment.body}\n\nUser's reply: {comment.body}\n\nAs {personality.name}, continue the discussion with relevant information, insights, or questions."
        
        # Format the prompt using the personality's template
        formatted_prompt = personality.prompt_template
        formatted_prompt = formatted_prompt.replace('{{content}}', content_text)
        formatted_prompt = formatted_prompt.replace('{{context}}', context_text)
        
        # For any other template variables, use personality attributes
        formatted_prompt = formatted_prompt.replace('{{name}}', personality.name)
        formatted_prompt = formatted_prompt.replace('{{description}}', personality.description)
        formatted_prompt = formatted_prompt.replace('{{expertise}}', personality.expertise)
        formatted_prompt = formatted_prompt.replace('{{personality_traits}}', personality.personality_traits)
        
        # Log the actual prompt sent to the model
        print("FINAL PROMPT FOR AI COMMENT RESPONSE:")
        print("=" * 40)
        print(formatted_prompt)
        print("=" * 40)
        
        # Get completion from LLM service
        from app.services.llm_service import get_completion
        response = get_completion(
            prompt=formatted_prompt,
            model=personality.custom_model,
            api_key=personality.custom_api_key,
            base_url=personality.custom_base_url
        )
        
        if not response:
            print("Failed to get a response from the LLM service")
            return None
        
        # Create the comment
        print(f"Creating AI response from {ai_user.username} (id: {ai_user.id})")
        result = Comment(
            body=response,
            user_id=ai_user.id,
            question_id=question.id,
            parent_comment_id=comment.id  # This is a reply to the user's comment
        )
        
        db.session.add(result)
        db.session.commit()
        print(f"AI {personality.name} responded to comment {comment_id}")
        
        return result


def auto_populate_thread(question_id, max_comments=None, num_personalities=None):
    """
    Automatically populate a thread with AI responses
    
    Args:
        question_id (int): The ID of the question to populate
        max_comments (int, optional): Maximum number of comments to generate
        num_personalities (int, optional): Number of AI personalities to involve
        
    Returns:
        tuple: (success, message)
    """
    try:
        from app.models.site_settings import SiteSettings
        from app.models.ai_personality import AIPersonality
        from app.services.llm_service import get_completion
        
        # Get the question
        question = Question.query.get(question_id)
        if not question:
            return False, "Question not found"
        
        # Get settings with defaults
        if max_comments is None:
            max_comments = int(SiteSettings.get('ai_auto_populate_max_comments', 150))
        
        if num_personalities is None:
            num_personalities = int(SiteSettings.get('ai_auto_populate_personalities', 7))
        
        # Get active AI personalities
        ai_personalities = AIPersonality.query.filter_by(is_active=True).all()
        if not ai_personalities:
            return False, "No active AI personalities found"
        
        # Select a subset of personalities to involve in this thread
        if len(ai_personalities) > num_personalities:
            selected_personalities = random.sample(ai_personalities, num_personalities)
        else:
            selected_personalities = ai_personalities
        
        # Generate initial AI answers if none exist
        answers = Answer.query.filter_by(question_id=question_id).all()
        if not answers:
            # Generate an answer from one of the personalities
            personality = random.choice(selected_personalities)
            success, message = _generate_ai_answer(question_id, personality.id)
            if not success:
                return False, message
        
        # Get all comments for this question
        all_comments = Comment.query.filter_by(question_id=question_id).all()
        
        # Count existing AI comments
        ai_comment_count = 0
        for comment in all_comments:
            if User.query.get(comment.user_id).is_ai:
                ai_comment_count += 1
        
        # Check if we've reached the maximum
        if ai_comment_count >= max_comments:
            return True, f"Thread already has {ai_comment_count} AI comments (max: {max_comments})"
        
        # Build context with question details
        context = f"Question Title: {question.title}\n"
        context += f"Question Body: {question.body}\n"
        if question.tags:
            context += f"\n\nTags: {', '.join([tag.tag.name for tag in question.tags])}"
        
        # Get all comments and answers to evaluate and possibly respond to
        items_to_evaluate = []
        
        # Add answers to evaluate
        for answer in answers:
            items_to_evaluate.append({
                'type': 'answer',
                'id': answer.id,
                'user_id': answer.user_id,
                'body': answer.body,
                'created_at': answer.created_at
            })
        
        # Add comments to evaluate
        for comment in all_comments:
            items_to_evaluate.append({
                'type': 'comment',
                'id': comment.id,
                'user_id': comment.user_id,
                'body': comment.body,
                'parent_id': comment.parent_comment_id,
                'created_at': comment.created_at
            })
        
        # Sort by creation time
        items_to_evaluate.sort(key=lambda x: x['created_at'])
        
        # For each personality, evaluate and possibly respond to items
        for personality in selected_personalities:
            # Skip if this personality shouldn't respond based on activity frequency
            if not personality.should_respond():
                continue
                
            # Get the AI user for this personality
            ai_user = User.query.filter_by(ai_personality_id=personality.id, is_ai=True).first()
            if not ai_user:
                # Create a user for this AI personality
                ai_user = User(
                    username=f"ai_{personality.name.lower().replace(' ', '_')}",
                    email=f"ai_{personality.name.lower().replace(' ', '_')}@example.com",
                    is_ai=True,
                    ai_personality_id=personality.id
                )
                ai_user.set_password("AIUSER")
                db.session.add(ai_user)
                db.session.commit()
            
            # For each item, decide whether to vote and/or reply
            for item in items_to_evaluate:
                # Skip if the item was created by this AI
                if item['user_id'] == ai_user.id:
                    continue
                
                # 90% chance to evaluate the item
                if random.random() < 0.9:
                    # Determine whether to upvote or downvote based on content quality
                    if item['type'] == 'answer':
                        prompt = f"""
                        You are {personality.name}, an AI with the following traits:
                        - Expertise: {personality.expertise}
                        - Personality: {personality.personality_traits}
                        - Interaction Style: {personality.interaction_style}
                        
                        Please evaluate the following answer to a question. Consider its quality, accuracy, helpfulness, and clarity.
                        
                        {context}
                        
                        Answer: {item['body']}
                        
                        Based on your evaluation, should this answer be upvoted or downvoted?
                        Respond with either "UPVOTE" or "DOWNVOTE" followed by your reasoning.
                        """
                    else:  # comment
                        prompt = f"""
                        You are {personality.name}, an AI with the following traits:
                        - Expertise: {personality.expertise}
                        - Personality: {personality.personality_traits}
                        - Interaction Style: {personality.interaction_style}
                        
                        Please evaluate the following comment. Consider its quality, relevance, helpfulness, and clarity.
                        
                        {context}
                        
                        Comment: {item['body']}
                        
                        Based on your evaluation, should this comment be upvoted or downvoted?
                        Respond with either "UPVOTE" or "DOWNVOTE" followed by your reasoning.
                        """
                    
                    # Format the prompt with the AI personality
                    formatted_prompt = personality.format_prompt(
                        content=prompt,
                        context=""
                    )
                    
                    # Get completion from LLM with custom settings if available
                    response = get_completion(
                        prompt=formatted_prompt,
                        model=personality.custom_model,
                        api_key=personality.custom_api_key,
                        base_url=personality.custom_base_url
                    )
                    
                    # Determine the vote direction from the response
                    vote_direction = 1  # Default to upvote
                    if response and "DOWNVOTE" in response.upper().split("\n")[0]:
                        vote_direction = -1
                    
                    # Log the decision
                    current_app.logger.info(f"AI {personality.name} decided to {'downvote' if vote_direction == -1 else 'upvote'} {item['type']} {item['id']}")
                    current_app.logger.info(f"Reasoning: {response}")
                    
                    # Check if a vote already exists
                    if item['type'] == 'answer':
                        existing_vote = Vote.query.filter_by(
                            user_id=ai_user.id,
                            answer_id=item['id']
                        ).first()
                    else:  # comment
                        existing_vote = Vote.query.filter_by(
                            user_id=ai_user.id,
                            comment_id=item['id']
                        ).first()
                    
                    # Update or create the vote
                    if existing_vote:
                        existing_vote.vote_type = vote_direction
                    else:
                        # Create a new vote
                        vote = Vote(
                            user_id=ai_user.id,
                            vote_type=vote_direction
                        )
                        
                        if item['type'] == 'answer':
                            vote.answer_id = item['id']
                        else:  # comment
                            vote.comment_id = item['id']
                        
                        db.session.add(vote)
                    
                    # 70% chance to reply to the item
                    if random.random() < 0.7:
                        # Generate a reply based on the content
                        if vote_direction == 1:  # Upvote
                            reply_prompt = f"""
                            You are {personality.name}, an AI with the following traits:
                            - Expertise: {personality.expertise}
                            - Personality: {personality.personality_traits}
                            - Interaction Style: {personality.interaction_style}
                            
                            You just upvoted the following {item['type']}. 
                            Write a reply that expands on the {item['type']}, adds additional information, 
                            or supports the points made. Be constructive and helpful.
                            
                            {context}
                            
                            {item['type'].capitalize()}: {item['body']}
                            
                            Your reply:
                            """
                        else:  # Downvote
                            reply_prompt = f"""
                            You are {personality.name}, an AI with the following traits:
                            - Expertise: {personality.expertise}
                            - Personality: {personality.personality_traits}
                            - Interaction Style: {personality.interaction_style}
                            
                            You just downvoted the following {item['type']} because you found issues with it. 
                            Write a constructive reply that politely points out the issues, provides corrections, 
                            or offers a better alternative. Be respectful and helpful.
                            
                            {context}
                            
                            {item['type'].capitalize()}: {item['body']}
                            
                            Your reply:
                            """
                        
                        # Format the prompt with the AI personality
                        formatted_reply_prompt = personality.format_prompt(
                            content=reply_prompt,
                            context=""
                        )
                        
                        # Get completion from LLM with custom settings if available
                        reply_text = get_completion(
                            prompt=formatted_reply_prompt,
                            model=personality.custom_model,
                            api_key=personality.custom_api_key,
                            base_url=personality.custom_base_url
                        )
                        
                        # Create the reply
                        if item['type'] == 'answer':
                            # Create a comment on the answer
                            reply = Comment(
                                body=reply_text,
                                user_id=ai_user.id,
                                question_id=question_id,
                                answer_id=item['id']
                            )
                        else:  # comment
                            # Create a reply to the comment
                            reply = Comment(
                                body=reply_text,
                                user_id=ai_user.id,
                                question_id=question_id,
                                parent_comment_id=item['id']
                            )
                        
                        db.session.add(reply)
                        ai_comment_count += 1
                        
                        # Check if we've reached the maximum
                        if ai_comment_count >= max_comments:
                            db.session.commit()
                            return True, f"Generated {ai_comment_count} AI comments (max reached)"
        
        # Commit all changes
        db.session.commit()
        return True, f"Generated {ai_comment_count} AI comments"
    
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error in auto_populate_thread: {str(e)}")
        return False, f"Error populating thread: {str(e)}"
