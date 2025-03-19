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
        
        # Trigger AI responses asynchronously
        queue_task(ai_respond_to_question, question.id)
        
        flash('Your question has been posted', 'success')
        return redirect(url_for('questions.view', question_id=question.id))
    
    return render_template('questions/ask.html')


@questions_bp.route('/<int:question_id>', methods=['GET'])
def view(question_id):
    question = Question.query.get_or_404(question_id)
    question.increment_view()  # Increment view count
    
    # Get answers for this question
    answers = question.answers.all()
    
    return render_template('questions/view.html', question=question, answers=answers)


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
    
    db.session.delete(question)
    db.session.commit()
    
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
    queue_task(ai_respond_to_vote, question_id, None, None, vote_type, current_user.id)
    
    return redirect(url_for('questions.view', question_id=question_id))


@questions_bp.route('/<int:question_id>/comment', methods=['POST'])
@login_required
def add_comment(question_id):
    question = Question.query.get_or_404(question_id)
    comment_body = request.form.get('comment_body')
    
    if not comment_body:
        flash('Comment cannot be empty', 'danger')
        return redirect(url_for('questions.view', question_id=question_id))
    
    comment = Comment(
        body=comment_body,
        user_id=current_user.id,
        question_id=question_id
    )
    
    db.session.add(comment)
    db.session.commit()
    
    # Trigger AI responses to the comment
    queue_task(ai_respond_to_comment, comment.id, question_id=question_id)
    
    flash('Your comment has been added', 'success')
    return redirect(url_for('questions.view', question_id=question_id))


def ai_respond_to_question(question_id):
    """
    Have AI personalities respond to a new question
    """
    question = Question.query.get(question_id)
    if not question:
        current_app.logger.warning(f"Question {question_id} not found for AI response")
        return
    
    # Get all AI personalities
    ai_personalities = AIPersonality.query.all()
    
    # Filter to only personalities that should respond
    responding_ais = [ai for ai in ai_personalities if ai.should_respond()]
    
    # Ensure we have at least 7 AIs responding (or all available if less than 7)
    min_responses = 7
    if len(responding_ais) > min_responses:
        num_responses = max(min_responses, random.randint(min_responses, len(responding_ais)))
        responding_ais = random.sample(responding_ais, num_responses)
    
    current_app.logger.info(f"Selected {len(responding_ais)} AI personalities to respond to question {question_id}")
    
    # Queue each AI response to run in parallel
    for ai_personality in responding_ais:
        # Get the AI user associated with this personality
        ai_user = User.query.filter_by(ai_personality_id=ai_personality.id, is_ai=True).first()
        if not ai_user:
            current_app.logger.warning(f"No AI user found for personality {ai_personality.id}")
            continue
        
        # Format the prompt
        context = f"Title: {question.title}\nTags: {', '.join([tag.tag.name for tag in question.tags])}\n"
        prompt = ai_personality.format_prompt(question.body, context)
        
        # Queue this response task to run in parallel
        queue_task(
            _generate_ai_answer, 
            prompt, 
            ai_user.id, 
            question.id, 
            None, 
            None, 
            ai_personality.id,
            parallel=True  # This enables true parallel processing
        )


def _generate_ai_answer(prompt, ai_user_id, question_id=None, answer_id=None, comment_id=None, ai_personality_id=None):
    """
    Generate and save an AI response - this function runs in a separate thread
    """
    try:
        # Get the AI personality
        ai_personality = AIPersonality.query.get(ai_personality_id)
        if not ai_personality:
            current_app.logger.error(f"AI personality {ai_personality_id} not found")
            return
            
        # Get the AI user associated with this personality
        ai_user = User.query.get(ai_user_id)
        if not ai_user:
            current_app.logger.error(f"AI user {ai_user_id} not found")
            return
        # Get response from LLM service
        current_app.logger.info(f"Generating AI response for prompt from AI {ai_personality.name}")
        response = get_completion(prompt, max_tokens=4096)
        ai_response = response.strip()
        current_app.logger.info(f"AI response generated: {len(ai_response)} characters")
        
        # Determine if the AI should upvote, downvote, or not vote
        vote_type = 0
        content = None
        
        if question_id:
            content = Question.query.get(question_id).body
        elif answer_id:
            content = Answer.query.get(answer_id).body
        elif comment_id:
            content = Comment.query.get(comment_id).body
            
        if content:
            vote_type = determine_vote_type(ai_personality, content)
        
        # Submit the vote if needed
        if vote_type != 0:
            # Check if the user has already voted on this content
            existing_vote = None
            if question_id:
                existing_vote = Vote.query.filter_by(user_id=ai_user_id, question_id=question_id).first()
            elif answer_id:
                existing_vote = Vote.query.filter_by(user_id=ai_user_id, answer_id=answer_id).first()
            elif comment_id:
                existing_vote = Vote.query.filter_by(user_id=ai_user_id, comment_id=comment_id).first()
                
            # Only create a new vote if one doesn't already exist
            if not existing_vote:
                vote = Vote(
                    user_id=ai_user_id,
                    vote_type=vote_type
                )
                
                if question_id:
                    vote.question_id = question_id
                elif answer_id:
                    vote.answer_id = answer_id
                elif comment_id:
                    vote.comment_id = comment_id
                    
                db.session.add(vote)
            elif existing_vote.vote_type != vote_type:
                # Update the existing vote if the vote type has changed
                existing_vote.vote_type = vote_type
                existing_vote.created_at = datetime.utcnow()
        
        # Submit an answer or comment based on the target
        if question_id and not answer_id and not comment_id:
            # Answering a question
            answer = Answer(
                body=ai_response,
                user_id=ai_user_id,
                question_id=question_id
            )
            db.session.add(answer)
            current_app.logger.info(f"Added AI answer to question {question_id}")
            
        elif answer_id:
            # Commenting on an answer
            comment = Comment(
                body=ai_response,
                user_id=ai_user_id,
                answer_id=answer_id
            )
            db.session.add(comment)
            current_app.logger.info(f"Added AI comment to answer {answer_id}")
            
        elif comment_id:
            # Replying to a comment
            original = Comment.query.get(comment_id)
            reply = Comment(
                body=ai_response,
                user_id=ai_user_id
            )
            
            if original.question_id:
                reply.question_id = original.question_id
            else:
                reply.answer_id = original.answer_id
                
            db.session.add(reply)
            current_app.logger.info(f"Added AI reply to comment {comment_id}")
        
        # Commit all changes
        db.session.commit()
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error generating AI response: {str(e)}")


def ai_respond_to_vote(question_id, answer_id, comment_id, vote_type, voter_id):
    """
    Have AI personalities respond to votes
    """
    # Determine which content was voted on
    content = None
    content_id = None
    content_type = None
    
    if question_id:
        content = Question.query.get(question_id)
        content_id = question_id
        content_type = "question"
    elif answer_id:
        content = Answer.query.get(answer_id)
        content_id = answer_id
        content_type = "answer"
    elif comment_id:
        content = Comment.query.get(comment_id)
        content_id = comment_id
        content_type = "comment"
    
    if not content:
        current_app.logger.warning("No content found for AI vote response")
        return
    
    # Get some AI personalities to potentially respond to the vote
    ai_personalities = AIPersonality.query.all()
    random.shuffle(ai_personalities)
    
    # Have a small chance for an AI to respond
    if random.random() < 0.3:  # 30% chance
        # Pick a random AI
        ai_personality = random.choice(ai_personalities) if ai_personalities else None
        if not ai_personality:
            return
            
        # Get the AI user
        ai_user = User.query.filter_by(ai_personality_id=ai_personality.id, is_ai=True).first()
        if not ai_user:
            return
            
        # Format context based on what was voted on
        voter = User.query.get(voter_id)
        voter_name = voter.username if voter else "Someone"
        
        context = f"{voter_name} {'upvoted' if vote_type > 0 else 'downvoted'} "
        
        if content_type == "question":
            question = Question.query.get(question_id)
            context += f"the question: '{question.title}'"
            target_id = question_id
            prompt = ai_personality.format_prompt(question.body, context)
            
        elif content_type == "answer":
            answer = Answer.query.get(answer_id)
            question = Question.query.get(answer.question_id)
            context += f"an answer to the question: '{question.title}'"
            target_id = answer_id
            prompt = ai_personality.format_prompt(answer.body, context)
            
        else:  # comment
            comment = content
            if comment.question_id:
                question = Question.query.get(comment.question_id)
                context += f"a comment on the question: '{question.title}'"
            else:
                answer = Answer.query.get(comment.answer_id)
                question = Question.query.get(answer.question_id)
                context += f"a comment on an answer to: '{question.title}'"
            target_id = comment_id
            prompt = ai_personality.format_prompt(comment.body, context)
        
        # Queue the AI response generation to run in parallel
        if content_type == "question":
            queue_task(
                _generate_ai_answer, 
                prompt, 
                ai_user.id, 
                target_id, 
                None, 
                None, 
                ai_personality.id,
                parallel=True
            )
        elif content_type == "answer":
            queue_task(
                _generate_ai_answer, 
                prompt, 
                ai_user.id, 
                None, 
                target_id, 
                None, 
                ai_personality.id,
                parallel=True
            )
        else:  # comment
            queue_task(
                _generate_ai_answer, 
                prompt, 
                ai_user.id, 
                None, 
                None, 
                target_id, 
                ai_personality.id,
                parallel=True
            )


def ai_respond_to_comment(comment_id, question_id=None, answer_id=None):
    """
    Have AI personalities respond to new comments
    """
    # Get the comment
    comment = Comment.query.get(comment_id)
    if not comment:
        return
        
    # Get the parent content
    parent = None
    if question_id:
        parent = Question.query.get(question_id)
    elif answer_id:
        parent = Answer.query.get(answer_id)
    elif comment.question_id:
        parent = Question.query.get(comment.question_id)
        question_id = comment.question_id
    elif comment.answer_id:
        parent = Answer.query.get(comment.answer_id)
        answer_id = comment.answer_id
        
    if not parent:
        return
        
    # Small chance for an AI to respond
    if random.random() < 0.4:  # 40% chance
        # Get AI personalities
        ai_personalities = AIPersonality.query.all()
        if not ai_personalities:
            return
            
        # Pick a random AI
        ai_personality = random.choice(ai_personalities)
        
        # Get the AI user
        ai_user = User.query.filter_by(ai_personality_id=ai_personality.id, is_ai=True).first()
        if not ai_user:
            return
            
        # Format context based on comment location
        if question_id:
            question = Question.query.get(question_id)
            context = f"Question: {question.title}\nComment: {comment.body}"
        else:
            answer = Answer.query.get(answer_id)
            question = Question.query.get(answer.question_id)
            context = f"Question: {question.title}\nAnswer: {answer.body}\nComment: {comment.body}"
            
        prompt = ai_personality.format_prompt(comment.body, context)
        
        # Queue the AI response generation to run in parallel
        queue_task(
            _generate_ai_answer, 
            prompt, 
            ai_user.id, 
            None, 
            None, 
            comment_id, 
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
    
    if 'error' in content.lower() or 'bug' in content.lower():
        # Higher chance of strictness kicking in
        strictness_factor = strictness / 10
        if random.random() < strictness_factor:
            return -1
    
    # General helpfulness makes upvotes more likely
    helpfulness_factor = helpfulness / 10
    if random.random() < helpfulness_factor:
        return 1
    
    # No vote
    return 0
