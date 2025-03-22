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
            from app.routes.api import generate_ai_response
            ai_response = generate_ai_response(
                'question', 
                question.id, 
                personality.id
            )
            if ai_response:
                print(f"Added AI answer to question {question.id}")
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


def _generate_ai_answer(prompt, ai_user_id=None, ai_personality_id=None, 
                       question_id=None, comment_id=None, answer_id=None):
    """
    Generate an AI answer based on the prompt and save it to the database
    """
    from app.models.user import User
    from app.models.ai_personality import AIPersonality
    
    # If AI user is provided, make sure it exists and is an AI
    ai_user = None
    personality = None
    
    if ai_personality_id:
        personality = AIPersonality.query.get(ai_personality_id)
        if personality:
            print(f"Using AI personality: {personality.name}")
            # Log the personality template for debugging
            print(f"Personality template: {personality.prompt_template}")
            
            # Check if there's a user for this personality
            ai_user = User.query.filter_by(username=personality.name).first()
            if not ai_user:
                # Create a user for this personality
                print(f"Creating new AI user for personality: {personality.name}")
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
        else:
            print(f"AI personality ID {ai_personality_id} not found")
    
    # If we don't have an AI user yet but we have an ID, try to get it
    if not ai_user and ai_user_id:
        ai_user = User.query.get(ai_user_id)
        if ai_user and ai_user.is_ai and ai_user.ai_personality_id:
            personality = AIPersonality.query.get(ai_user.ai_personality_id)
            if personality:
                print(f"Found AI personality {personality.name} for user {ai_user.username}")
                # Log the personality template for debugging
                print(f"Personality template: {personality.prompt_template}")
    
    # If we still don't have an AI user or personality, use any AI user or create a default
    if not ai_user or not personality:
        print("No specific AI personality specified, finding or creating one")
        # Try to find an active AI personality
        personalities = AIPersonality.query.filter_by(is_active=True).all()
        
        if not personalities:
            # If no active ones, use any
            personalities = AIPersonality.query.all()
        
        if personalities:
            # Use a random personality
            import random
            personality = random.choice(personalities)
            print(f"Selected random AI personality: {personality.name}")
            # Log the personality template for debugging
            print(f"Personality template: {personality.prompt_template}")
            
            # Check if there's a user for this personality
            ai_user = User.query.filter_by(username=personality.name).first()
            if not ai_user:
                # Create a user for this personality
                print(f"Creating new AI user for personality: {personality.name}")
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
        else:
            # Create a default AI personality and user
            print("No AI personalities found, creating default")
            default_personality = AIPersonality(
                name="AI Assistant",
                description="A helpful AI assistant",
                expertise="General knowledge,Programming,Problem solving",
                personality_traits="Helpful,Friendly,Knowledgeable",
                interaction_style="Conversational",
                helpfulness_level=9,
                strictness_level=5,
                verbosity_level=7,
                prompt_template="You are a helpful AI assistant providing information on {{content}}",
                is_active=True
            )
            db.session.add(default_personality)
            db.session.commit()
            
            # Create a user for the default personality
            from werkzeug.security import generate_password_hash
            ai_user = User(
                username=default_personality.name,
                email=f"{default_personality.name.lower().replace(' ', '.')}@overflew.ai",
                password_hash=generate_password_hash("AI_USER_PASSWORD"),
                is_ai=True,
                ai_personality_id=default_personality.id
            )
            db.session.add(ai_user)
            db.session.commit()
    
    # Now use the personality's template to format the prompt
    formatted_prompt = personality.prompt_template
    # Replace the {{content}} variable with our prompt
    formatted_prompt = formatted_prompt.replace('{{content}}', prompt)
    # If there's no context, replace with empty string
    formatted_prompt = formatted_prompt.replace('{{context}}', '')
    
    # For any other template variables, use personality attributes
    formatted_prompt = formatted_prompt.replace('{{name}}', personality.name)
    formatted_prompt = formatted_prompt.replace('{{description}}', personality.description)
    formatted_prompt = formatted_prompt.replace('{{expertise}}', personality.expertise)
    formatted_prompt = formatted_prompt.replace('{{personality_traits}}', personality.personality_traits)
    
    # Log the actual prompt sent to the model
    print("FINAL PROMPT FOR AI:")
    print("=" * 40)
    print(formatted_prompt)
    print("=" * 40)
    
    # Get completion from LLM service
    from app.services.llm_service import get_completion
    response = get_completion(formatted_prompt)
    
    if not response:
        print("Failed to get a response from the LLM service")
        return None
    
    # Create the answer or comment
    result = None
    print(f"Creating AI response from {ai_user.username} (id: {ai_user.id})")
    
    if question_id and not comment_id:
        # Create a comment as an answer to the question
        result = Comment(
            body=response,
            user_id=ai_user.id,
            question_id=question_id,
            parent_comment_id=None
        )
        db.session.add(result)
        print(f"Added AI answer to question {question_id}")
    elif comment_id:
        # Get the original comment
        original = Comment.query.get_or_404(comment_id)
        
        # Create a reply to the comment
        reply = Comment(
            body=response,
            user_id=ai_user.id,
            question_id=original.question_id,
            parent_comment_id=comment_id
        )
        db.session.add(reply)
        result = reply
        print(f"Added AI reply to comment {comment_id}")
    
    db.session.commit()
    return result


def ai_respond_to_vote(vote):
    """
    Generate an AI response to a vote on a question or comment.
    :param vote: The vote object
    :return: The generated response, if any
    """
    from app.models.user import User
    from app.models.ai_personality import AIPersonality
    import random
    
    # Add the vote to the session if it's not already in a session
    # This prevents SQLAlchemy warnings about objects not being in session
    from sqlalchemy.orm.util import object_state
    if object_state(vote).session is None:
        db.session.add(vote)
    
    # Use a no_autoflush block to prevent the temporary vote from being flushed to the database
    # This prevents UNIQUE constraint errors with existing votes
    with db.session.no_autoflush:
        # Don't respond to AI votes to prevent loops
        voter = User.query.get(vote.user_id)
        if voter.is_ai:
            print(f"Not responding to vote from AI user {voter.username}")
            return None
        
        # Don't respond to downvotes on content created by the same voter (self-correction)
        if vote.vote_type == -1:
            if (vote.question_id and vote.question.author.id == vote.user_id) or \
               (vote.comment_id and vote.comment.author.id == vote.user_id):
                print(f"Not responding to self-downvote")
                return None
        
        # Determine content type and get the content
        content_type = None
        content = None
        question_id = None
        comment_id = None
        
        if vote.question_id:
            content_type = "question"
            content = vote.question
            if content:  # Check if question exists
                question_id = content.id
                # Check if the question is marked as answered
                if content.is_answered:
                    print(f"Question {content.id} is marked as answered, skipping AI response to vote")
                    return None
            else:
                print(f"Question not found for vote {vote.id}")
                return None
        elif vote.comment_id:
            content_type = "comment"
            content = vote.comment
            if content:  # Check if comment exists
                comment_id = content.id
                question_id = content.question_id
                
                # Check if the parent question is marked as answered
                if question_id:
                    question = Question.query.get(question_id)
                    if question and question.is_answered:
                        print(f"Question {question_id} for comment {comment_id} is marked as answered, skipping AI response to vote")
                        return None
            else:
                print(f"Comment not found for vote {vote.id}")
                return None
        
        if not content:
            print(f"Content not found for vote {vote.id}")
            return None
        
        # Check whether to respond based on vote type
        vote_type = vote.vote_type
        response_chance = 0.1 if vote_type == 1 else 0.3
        
        import random
        # if random.random() > response_chance:
        #     print(f"AI decided not to respond to this vote")
        #     return None  # AI decides not to respond
        
        # Get AI personalities that are likely to respond
        personalities = AIPersonality.query.filter_by(is_active=True).all()
        
        # If no active personalities found, check for any personalities
        if not personalities:
            personalities = AIPersonality.query.all()
            print(f"No active AI personalities found, using any available ({len(personalities)} found)")
        
        # If still no personalities, create a default one
        if not personalities:
            print("No AI personalities found, creating default")
            default_personality = AIPersonality(
                name="AI Assistant",
                description="A helpful AI assistant",
                expertise="General knowledge,Programming,Problem solving",
                personality_traits="Helpful,Friendly,Knowledgeable",
                interaction_style="Conversational",
                helpfulness_level=9,
                strictness_level=5,
                verbosity_level=7,
                prompt_template="You are a helpful AI assistant providing information on {{content}}",
                is_active=True
            )
            db.session.add(default_personality)
            db.session.commit()
            personalities = [default_personality]
        
        # Select a personality to respond
        personality = random.choice(personalities)
        print(f"Selected AI personality for vote response: {personality.name}")
        print(f"Personality template: {personality.prompt_template}")
        
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
        
        # Prepare the content for the template
        content_text = ""
        context_text = ""
        
        if content_type == "question":
            question = content
            
            if vote_type == 1:
                content_text = f"The following question received an upvote:\n\n{question.title}\n\n{question.body}\n\nAs {personality.name}, provide an insightful answer to this question."
            else:
                content_text = f"The following question received a downvote:\n\n{question.title}\n\n{question.body}\n\nAs {personality.name}, help improve this question by answering what might be unclear or providing a better approach."
            
            target_id = question_id
        elif content_type == "comment":
            comment = content
            question = Question.query.get(comment.question_id)
            
            # Build comprehensive context with question details and comment thread
            context_text = f"QUESTION: {question.title}\n\n{question.body}\n\n"
            
            # Add tags if available 
            if question.tags:
                tags_str = ", ".join([tag.tag.name for tag in question.tags])
                context_text += f"TAGS: {tags_str}\n\n"
            
            # Build the comment chain to trace the full conversation
            comment_chain = []
            current = comment
            
            # Traverse up the comment tree to collect all parents
            while current:
                author = User.query.get(current.user_id)
                author_name = author.username if author else "Unknown User"
                is_ai = " (AI)" if author and author.is_ai else ""
                
                comment_chain.append(f"COMMENT by {author_name}{is_ai}: {current.body}")
                
                if hasattr(current, 'parent_comment_id') and current.parent_comment_id:
                    current = Comment.query.get(current.parent_comment_id)
                else:
                    break
            
            # Reverse to get chronological order (oldest first)
            comment_chain.reverse()
            
            context_text += "CONVERSATION HISTORY:\n" + "\n\n".join(comment_chain)
            
            # Get the prompt based on vote type
            if vote_type == 1:
                content_text = f"The following comment received an upvote:\n{comment.body}\n\nAs {personality.name}, add to this well-received comment with additional insights or support."
            else:
                content_text = f"The following comment received a downvote:\n{comment.body}\n\nAs {personality.name}, provide a balanced perspective or clarify potential misconceptions in this comment."
            
            target_id = comment_id
        
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
        print("FINAL PROMPT FOR AI VOTE RESPONSE:")
        print("=" * 40)
        print(formatted_prompt)
        print("=" * 40)
        
        # Get completion from LLM service
        from app.services.llm_service import get_completion
        response = get_completion(formatted_prompt)
        
        if not response:
            print("Failed to get a response from the LLM service")
            return None
        
        # Create the answer or comment
        result = None
        print(f"Creating AI response from {ai_user.username} (id: {ai_user.id})")
        
        if content_type == "question":
            # Create a comment as an answer to the question
            result = Comment(
                body=response,
                user_id=ai_user.id,
                question_id=question_id,
                parent_comment_id=None
            )
            db.session.add(result)
            print(f"Added AI answer to question {question_id}")
        elif content_type == "comment":
            # Get the original comment to ensure we have the correct question_id
            original_comment = Comment.query.get(comment_id)
            if not original_comment:
                print(f"Failed to find original comment {comment_id}")
                return None
                
            # Create a reply to the comment
            reply = Comment(
                body=response,
                user_id=ai_user.id,
                question_id=original_comment.question_id,  # Use the comment's question_id to ensure proper association
                parent_comment_id=comment_id  # Set this comment as a direct reply to the voted comment
            )
            db.session.add(reply)
            result = reply
            print(f"Added AI reply to comment {comment_id}")
        
        try:
            db.session.commit()
            print(f"Successfully saved AI response")
            return result
        except Exception as e:
            db.session.rollback()
            print(f"Error saving AI response: {str(e)}")
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
        if not comment:
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
        
        # Check if AI should respond (25% chance)
        import random
        # if random.random() > 0.25:
        #     print(f"AI decided not to respond to comment {comment_id}")
        #     return None  # AI decides not to respond
        
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
                prompt_template="You are a helpful AI assistant providing information on {{content}}",
                is_active=True
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
        
        # Prepare content text and context text for the template
        content_text = ""
        context_text = f"Question: {question.title}\n\n{question.body}"
        
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
        response = get_completion(formatted_prompt)
        
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


def auto_populate_thread(question_id):
    """Auto-populate a thread with AI-generated comments"""
    from app.models.site_settings import SiteSettings
    from app.models.ai_personality import AIPersonality
    from app.models.user import User
    from app.models.question import Question
    from app.models.answer import Answer
    from app.models.comment import Comment
    from app.models.vote import Vote
    from flask import current_app
    import random
    
    # Check if auto-population is enabled
    if not SiteSettings.get('ai_auto_populate_enabled', False):
        print("Auto-population is disabled, skipping")
        return
    
    try:
        # Get the max number of comments to generate
        max_comments = SiteSettings.get('ai_auto_populate_max_comments', 150)
        
        # Get the number of AI personalities to involve
        num_personalities = SiteSettings.get('ai_auto_populate_personalities', 7)
        
        # Get the question
        question = Question.query.get(question_id)
        if not question:
            print(f"Question {question_id} not found, skipping auto-population")
            return
        
        # Skip auto-population if the question is marked as answered
        if question.is_answered:
            print(f"Question {question_id} is marked as answered, skipping auto-population")
            return
        
        # Get active AI personalities
        ai_personalities = list(AIPersonality.query.filter_by(is_active=True).all())
        if len(ai_personalities) < num_personalities:
            print(f"Not enough active AI personalities ({len(ai_personalities)}), using all available")
            num_personalities = len(ai_personalities)
        
        if not ai_personalities:
            print("No active AI personalities found, skipping auto-population")
            return
        
        # Randomly select AI personalities to use
        selected_personalities = random.sample(ai_personalities, num_personalities)
        print(f"Selected {len(selected_personalities)} AI personalities for auto-population")
        
        # Get or create AI users for selected personalities
        ai_users = []
        for personality in selected_personalities:
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
            
            ai_users.append(ai_user)
        
        # Function to create initial AI answers
        def _create_ai_answer(ai_user, question):
            # Check if the question has been marked as answered since the task started
            db.session.refresh(question)
            if question.is_answered:
                print(f"Question {question.id} has been marked as answered during auto-population, skipping AI answer")
                return False
                
            print(f"Creating AI answer from {ai_user.username} for question {question.id}")
            
            # Generate AI response
            from app.routes.api import generate_ai_response
            ai_response = generate_ai_response(
                'question', 
                question.id, 
                ai_user.ai_personality_id
            )
            
            if ai_response:
                print(f"Added AI answer from {ai_user.username} to question {question.id}")
                return True
            return False
        
        # Function to create AI replies to comments
        def _create_ai_reply(ai_user, parent_comment, context=""):
            # Check if the question has been marked as answered since the task started
            db.session.refresh(Question.query.get(parent_comment.question_id))
            question = Question.query.get(parent_comment.question_id)
            if question and question.is_answered:
                print(f"Question {question.id} has been marked as answered during auto-population, skipping AI reply")
                return False
                
            # Don't reply to yourself
            if parent_comment.user_id == ai_user.id:
                return False
                
            print(f"Creating AI reply from {ai_user.username} to comment {parent_comment.id}")
            
            # Generate content for the context
            if isinstance(parent_comment, Answer):
                content_type = "answer"
                content = parent_comment.body
            else:
                content_type = "comment"
                content = parent_comment.body
            
            # Use direct comment creation for more control over the AI reply process
            try:
                # Update with AI-generated content
                from app.models.ai_personality import AIPersonality
                ai_personality = AIPersonality.query.get(ai_user.ai_personality_id)
                
                if ai_personality:
                    # Build comprehensive context including all parent comments and thread history
                    if not context:
                        # Start with the question
                        context = f"QUESTION: {question.title}\n\n{question.body}\n\n"
                        
                        # Add thread hierarchy (all parent comments)
                        comment_chain = []
                        current = parent_comment
                        
                        # Traverse up the comment tree to collect all parents
                        while current:
                            if isinstance(current, Comment):
                                author = User.query.get(current.user_id)
                                author_name = author.username if author else "Unknown User"
                                is_ai = " (AI)" if author and author.is_ai else ""
                                
                                comment_chain.append(f"COMMENT by {author_name}{is_ai}: {current.body}")
                                
                                if current.parent_comment_id:
                                    current = Comment.query.get(current.parent_comment_id)
                                else:
                                    current = None
                            else:
                                # If it's an Answer object
                                author = User.query.get(current.user_id)
                                author_name = author.username if author else "Unknown User"
                                is_ai = " (AI)" if author and author.is_ai else ""
                                
                                comment_chain.append(f"ANSWER by {author_name}{is_ai}: {current.body}")
                                current = None
                        
                        # Reverse the chain to get chronological order (oldest first)
                        comment_chain.reverse()
                        
                        # Add the comment chain to the context
                        context += "CONVERSATION HISTORY:\n" + "\n\n".join(comment_chain)
                    
                    # Generate response using personality template
                    prompt = ai_personality.format_prompt(content, context)
                    from app.services.llm_service import get_completion
                    response = get_completion(prompt, max_tokens=1024)
                    
                    # Create a new comment with the AI-generated content
                    reply = Comment(
                        body=response,
                        user_id=ai_user.id,
                        question_id=question.id,
                        parent_comment_id=parent_comment.id
                    )
                    db.session.add(reply)
                    db.session.commit()
                
                print(f"Added AI reply from {ai_user.username} to {content_type} {parent_comment.id}")
                return True
            except Exception as e:
                db.session.rollback()
                print(f"Error creating AI reply: {str(e)}")
                return False
        
        # First, create initial answers from some AI personalities
        for ai_user in random.sample(ai_users, min(3, len(ai_users))):
            # Check if the question has been marked as answered since the task started
            db.session.refresh(question)
            if question.is_answered:
                print(f"Question {question.id} has been marked as answered during auto-population, stopping")
                return
                
            _create_ai_answer(ai_user, question)
        
        # Get all comments and answers in the thread
        comments_count = 0
        while comments_count < max_comments:
            # Get all answers and comments in the thread
            answers = Answer.query.filter_by(question_id=question.id, is_deleted=False).all()
            comments = Comment.query.filter_by(question_id=question.id, is_deleted=False).all()
            
            # If no answers or comments yet, wait for them
            if not answers and not comments:
                import time
                time.sleep(5)
                continue
                
            # Calculate total count
            comments_count = len(answers) + len(comments)
            if comments_count >= max_comments:
                break
                
            # Combine answers and comments for AI to interact with
            all_comments = answers + comments
            
            # Each AI has a chance to interact
            for ai_user in ai_users:
                # Skip if we've reached the limit
                if comments_count >= max_comments:
                    break
                    
                # 90% chance to upvote a random comment and possibly reply
                if random.random() < 0.9:
                    # Try to find a comment not by this AI to upvote
                    for _ in range(min(10, len(all_comments))):
                        target = random.choice(all_comments)
                        # Don't vote on your own comments
                        if target.user_id != ai_user.id:
                            # Create upvote
                            vote = Vote.query.filter_by(
                                user_id=ai_user.id,
                                question_id=None if isinstance(target, Comment) else target.id,
                                comment_id=target.id if isinstance(target, Comment) else None
                            ).first()
                            
                            if not vote:
                                vote = Vote(
                                    user_id=ai_user.id,
                                    question_id=None if isinstance(target, Comment) else target.id,
                                    comment_id=target.id if isinstance(target, Comment) else None,
                                    vote_type=1  # upvote
                                )
                                db.session.add(vote)
                                try:
                                    db.session.commit()
                                    print(f"Added upvote from {ai_user.username} to {'answer' if isinstance(target, Answer) else 'comment'} {target.id}")
                                    
                                    # 70% chance to reply to upvoted comment
                                    if random.random() < 0.7:
                                        _create_ai_reply(ai_user, target)
                                        comments_count += 1
                                    
                                    break  # Found a comment to upvote
                                except Exception as e:
                                    db.session.rollback()
                                    print(f"Error adding upvote: {str(e)}")
                # 10% chance to downvote a random comment
                else:
                    # Try to find a comment not by this AI to downvote
                    for _ in range(min(10, len(all_comments))):
                        target = random.choice(all_comments)
                        # Don't vote on your own comments
                        if target.user_id != ai_user.id:
                            # Create downvote
                            vote = Vote.query.filter_by(
                                user_id=ai_user.id,
                                question_id=None if isinstance(target, Comment) else target.id,
                                comment_id=target.id if isinstance(target, Comment) else None
                            ).first()
                            
                            if not vote:
                                vote = Vote(
                                    user_id=ai_user.id,
                                    question_id=None if isinstance(target, Comment) else target.id,
                                    comment_id=target.id if isinstance(target, Comment) else None,
                                    vote_type=-1  # downvote
                                )
                                db.session.add(vote)
                                try:
                                    db.session.commit()
                                    print(f"Added downvote from {ai_user.username} to {'answer' if isinstance(target, Answer) else 'comment'} {target.id}")
                                    
                                    # 90% chance to reply to downvoted comment
                                    if random.random() < 0.9:
                                        _create_ai_reply(ai_user, target)
                                        comments_count += 1
                                    
                                    break  # Found a comment to downvote
                                except Exception as e:
                                    db.session.rollback()
                                    print(f"Error adding downvote: {str(e)}")
            
            # Check if the question has been marked as answered since the task started
            db.session.refresh(question)
            if question.is_answered:
                print(f"Question {question.id} has been marked as answered during auto-population, stopping")
                return
            
            # Pause between iterations to avoid overloading the server
            import time
            time.sleep(2)
        
        print(f"Auto-population complete for question {question_id} with {comments_count} comments/answers")
    except Exception as e:
        print(f"Error in auto_populate_thread: {str(e)}")


def _create_ai_answer(ai_user, question):
    """Helper function to create an AI answer to a question"""
    # Check if the question has been marked as answered since the task started
    db.session.refresh(question)
    if question.is_answered:
        print(f"Question {question.id} has been marked as answered during auto-population, skipping AI answer")
        return None
        
    # Get the AI personality
    personality = AIPersonality.query.get(ai_user.ai_personality_id)
    if not personality:
        print(f"No personality found for AI user {ai_user.username}")
        return None
    
    # Prepare the prompt
    prompt = f"Question: {question.title}\n\n{question.body}\n\nAs {personality.name}, provide a thoughtful answer to this question."
    
    # Format the prompt using the personality's template
    formatted_prompt = personality.prompt_template
    formatted_prompt = formatted_prompt.replace('{{content}}', prompt)
    formatted_prompt = formatted_prompt.replace('{{context}}', '')
    
    # For any other template variables, use personality attributes
    formatted_prompt = formatted_prompt.replace('{{name}}', personality.name)
    formatted_prompt = formatted_prompt.replace('{{description}}', personality.description)
    formatted_prompt = formatted_prompt.replace('{{expertise}}', personality.expertise)
    formatted_prompt = formatted_prompt.replace('{{personality_traits}}', personality.personality_traits)
    
    # Get completion from LLM service
    from app.services.llm_service import get_completion
    response = get_completion(formatted_prompt)
    
    if not response:
        print(f"Failed to get a response from the LLM service for {ai_user.username}")
        return None
    
    # Create the comment
    result = Comment(
        body=response,
        user_id=ai_user.id,
        question_id=question.id,
        parent_comment_id=None  # Top-level comment (direct answer)
    )
    
    db.session.add(result)
    try:
        db.session.commit()
        print(f"Added AI answer from {ai_user.username} to question {question.id}")
        return result
    except Exception as e:
        db.session.rollback()
        print(f"Error saving AI answer: {str(e)}")
        return None


def _create_ai_reply(ai_user, comment):
    """Helper function to create an AI reply to a comment"""
    # Check if the question has been marked as answered since the task started
    db.session.refresh(Question.query.get(comment.question_id))
    question = Question.query.get(comment.question_id)
    if question and question.is_answered:
        print(f"Question {question.id} has been marked as answered during auto-population, skipping AI reply")
        return None
        
    # Get the AI personality
    personality = AIPersonality.query.get(ai_user.ai_personality_id)
    if not personality:
        print(f"No personality found for AI user {ai_user.username}")
        return None
    
    # Get the question for context
    question = Question.query.get(comment.question_id)
    if not question:
        print(f"Question not found for comment {comment.id}")
        return None
    
    # Prepare content text and context text for the template
    content_text = ""
    context_text = f"Question: {question.title}\n\n{question.body}"
    
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
    
    # Get completion from LLM service
    from app.services.llm_service import get_completion
    response = get_completion(formatted_prompt)
    
    if not response:
        print(f"Failed to get a response from the LLM service for {ai_user.username}")
        return None
    
    # Create the reply
    result = Comment(
        body=response,
        user_id=ai_user.id,
        question_id=question.id,
        parent_comment_id=comment.id  # This is a reply to the comment
    )
    
    db.session.add(result)
    try:
        db.session.commit()
        print(f"Added AI reply from {ai_user.username} to comment {comment.id}")
        return result
    except Exception as e:
        db.session.rollback()
        print(f"Error saving AI reply: {str(e)}")
        return None
