// Initialize highlight.js for code syntax highlighting
document.addEventListener('DOMContentLoaded', function() {
    // Apply syntax highlighting to all code blocks
    document.querySelectorAll('pre code').forEach((block) => {
        hljs.highlightBlock(block);
    });

    // Setup markdown editor if it exists on the page
    setupMarkdownEditor();
    
    // Initialize vote buttons
    initializeVoteButtons();
    
    // Initialize AI response functionality
    initializeAIResponders();
});

// Setup markdown editor and preview functionality
function setupMarkdownEditor() {
    const markdownEditor = document.getElementById('markdown-editor');
    const previewTab = document.getElementById('preview-tab');
    const previewContent = document.getElementById('preview-content');
    
    if (markdownEditor && previewTab && previewContent) {
        // Update preview content when user clicks on preview tab
        previewTab.addEventListener('click', function(e) {
            e.preventDefault();
            const markdown = markdownEditor.value;
            const html = marked.parse(markdown);
            previewContent.innerHTML = html;
            
            // Apply syntax highlighting to code blocks in preview
            document.querySelectorAll('#preview-content pre code').forEach((block) => {
                hljs.highlightBlock(block);
            });
            
            // Show the preview tab
            document.getElementById('preview-tab').classList.add('active');
            document.getElementById('edit-tab').classList.remove('active');
            document.getElementById('preview-pane').classList.add('active', 'show');
            document.getElementById('edit-pane').classList.remove('active', 'show');
        });

        // Return to edit tab functionality
        document.getElementById('edit-tab').addEventListener('click', function(e) {
            e.preventDefault();
            document.getElementById('edit-tab').classList.add('active');
            document.getElementById('preview-tab').classList.remove('active');
            document.getElementById('edit-pane').classList.add('active', 'show');
            document.getElementById('preview-pane').classList.remove('active', 'show');
        });
    }
}

// Initialize vote buttons for questions and answers
function initializeVoteButtons() {
    document.querySelectorAll('.vote-button').forEach(button => {
        button.addEventListener('click', handleVote);
    });
}

// Handle voting on questions, answers, and comments
function handleVote(e) {
    e.preventDefault();
    
    if (!isUserAuthenticated()) {
        window.location.href = loginUrl + '?next=' + window.location.pathname;
        return;
    }
    
    const button = e.currentTarget;
    const voteType = button.dataset.voteType === 'up' ? 1 : -1;
    const questionId = button.dataset.questionId || null;
    const answerId = button.dataset.answerId || null;
    const commentId = button.dataset.commentId || null;
    
    // Get the current vote status
    const upButton = button.parentElement.querySelector('.vote-button[data-vote-type="up"]');
    const downButton = button.parentElement.querySelector('.vote-button[data-vote-type="down"]');
    let currentVote = 0;
    
    if (upButton.classList.contains('upvoted')) {
        currentVote = 1;
    } else if (downButton.classList.contains('downvoted')) {
        currentVote = -1;
    }
    
    // Calculate the new vote value
    let newVote = voteType;
    if (currentVote === voteType) {
        // Clicking the same button again removes the vote
        newVote = 0;
    }
    
    // Send the vote to the server
    fetch('/api/vote', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
            vote_type: newVote,
            question_id: questionId,
            answer_id: answerId,
            comment_id: commentId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update the UI
            updateVoteUI(button.parentElement, data.vote_type);
            
            // Update the vote count
            const voteCount = button.parentElement.querySelector('.vote-count');
            const currentCount = parseInt(voteCount.textContent);
            let newCount = currentCount;
            
            if (data.vote_type === 1) {
                // If it was previously downvoted, add 2
                newCount = currentVote === -1 ? currentCount + 2 : currentCount + 1;
            } else if (data.vote_type === -1) {
                // If it was previously upvoted, subtract 2
                newCount = currentVote === 1 ? currentCount - 2 : currentCount - 1;
            } else {
                // Vote was removed
                newCount = currentVote === 1 ? currentCount - 1 : currentCount + 1;
            }
            
            voteCount.textContent = newCount;
        }
    })
    .catch(error => {
        console.error('Error voting:', error);
    });
}

// Update vote UI based on vote type
function updateVoteUI(voteContainer, voteType) {
    const upButton = voteContainer.querySelector('.vote-button[data-vote-type="up"]');
    const downButton = voteContainer.querySelector('.vote-button[data-vote-type="down"]');
    
    // Reset classes
    upButton.classList.remove('upvoted');
    downButton.classList.remove('downvoted');
    
    // Add the appropriate class based on the vote type
    if (voteType === 1) {
        upButton.classList.add('upvoted');
    } else if (voteType === -1) {
        downButton.classList.add('downvoted');
    }
}

// Check if the user is authenticated
function isUserAuthenticated() {
    return document.body.dataset.userAuthenticated === 'true';
}

// Get CSRF token from meta tag
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]').getAttribute('content');
}

// Initialize AI responders for questions and answers
function initializeAIResponders() {
    const aiResponderButtons = document.querySelectorAll('.ai-responder-button');
    
    aiResponderButtons.forEach(button => {
        button.addEventListener('click', handleAIResponse);
    });
    
    // If there's an AI responder form, set it up
    const aiResponderForm = document.getElementById('ai-responder-form');
    if (aiResponderForm) {
        aiResponderForm.addEventListener('submit', handleAIResponseForm);
    }
}

// Handle AI response button click
function handleAIResponse(e) {
    e.preventDefault();
    
    // Get the AI responder modal
    const modal = document.getElementById('ai-responder-modal');
    const bootstrapModal = new bootstrap.Modal(modal);
    
    // Update the form with the content details
    const contentType = e.currentTarget.dataset.contentType;
    const contentId = e.currentTarget.dataset.contentId;
    
    document.getElementById('ai-response-content-type').value = contentType;
    document.getElementById('ai-response-content-id').value = contentId;
    
    // Show the modal
    bootstrapModal.show();
}

// Handle AI response form submission
function handleAIResponseForm(e) {
    e.preventDefault();
    
    const form = e.currentTarget;
    const contentType = form.querySelector('#ai-response-content-type').value;
    const contentId = form.querySelector('#ai-response-content-id').value;
    const personalityId = form.querySelector('#ai-response-personality').value;
    
    // Disable the submit button and show loading
    const submitButton = form.querySelector('button[type="submit"]');
    const originalButtonText = submitButton.textContent;
    submitButton.disabled = true;
    submitButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Generating...';
    
    // Send the request to the server
    fetch('/api/ai/respond', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
            content_type: contentType,
            content_id: contentId,
            personality_id: personalityId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Hide the modal
            const modal = document.getElementById('ai-responder-modal');
            const bootstrapModal = bootstrap.Modal.getInstance(modal);
            bootstrapModal.hide();
            
            // Add the AI response to the page
            addAIResponseToPage(contentType, contentId, data.response);
            
            // Display a success message
            showAlert('success', 'AI response generated successfully!');
        } else {
            showAlert('danger', data.error || 'Failed to generate AI response');
        }
    })
    .catch(error => {
        console.error('Error generating AI response:', error);
        showAlert('danger', 'Failed to generate AI response');
    })
    .finally(() => {
        // Re-enable the submit button
        submitButton.disabled = false;
        submitButton.textContent = originalButtonText;
    });
}

// Add AI response to the page
function addAIResponseToPage(contentType, contentId, response) {
    if (contentType === 'question') {
        // Add answer to the answers list
        const answersList = document.getElementById('answers-list');
        if (answersList) {
            const answerHtml = createAnswerHtml(response);
            answersList.insertAdjacentHTML('afterbegin', answerHtml);
            
            // Apply syntax highlighting
            document.querySelectorAll(`#answer-${response.id} pre code`).forEach((block) => {
                hljs.highlightBlock(block);
            });
            
            // Initialize vote buttons
            document.querySelectorAll(`#answer-${response.id} .vote-button`).forEach(button => {
                button.addEventListener('click', handleVote);
            });
        }
    } else {
        // Add comment to the comments list
        const commentsContainer = contentType === 'answer' 
            ? document.querySelector(`#answer-${contentId} .comments-list`)
            : document.querySelector(`#question-${contentId} .comments-list`);
            
        if (commentsContainer) {
            const commentHtml = createCommentHtml(response);
            commentsContainer.insertAdjacentHTML('beforeend', commentHtml);
        }
    }
}

// Create HTML for an answer
function createAnswerHtml(answer) {
    return `
    <div id="answer-${answer.id}" class="answer">
        <div class="row">
            <div class="col-1">
                <div class="vote-buttons">
                    <button class="vote-button" data-vote-type="up" data-answer-id="${answer.id}">
                        <i class="fa-solid fa-caret-up"></i>
                    </button>
                    <div class="vote-count">${answer.score}</div>
                    <button class="vote-button" data-vote-type="down" data-answer-id="${answer.id}">
                        <i class="fa-solid fa-caret-down"></i>
                    </button>
                </div>
            </div>
            <div class="col-11">
                <div class="post-content">
                    ${marked.parse(answer.body)}
                </div>
                <div class="post-menu">
                    <a href="#" class="add-comment-link" data-bs-toggle="collapse" data-bs-target="#add-comment-answer-${answer.id}">
                        Add comment
                    </a>
                </div>
                <div class="user-info mt-3">
                    <div class="d-flex align-items-center">
                        <img src="${answer.author.profile_image || 'https://api.dicebear.com/6.x/identicon/svg?seed=' + answer.author.username}" alt="${answer.author.username}" class="user-image me-2">
                        <div>
                            <span class="fw-bold">${answer.author.username}</span>
                            ${answer.author.is_ai ? '<span class="ai-badge">AI</span>' : ''}
                            <div class="text-muted small">
                                answered ${new Date(answer.created_at).toLocaleString()}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="collapse" id="add-comment-answer-${answer.id}">
                    <form class="comment-form mt-3" action="/answers/${answer.id}/comment" method="post">
                        <div class="mb-3">
                            <textarea class="form-control" name="comment_body" rows="2" required></textarea>
                        </div>
                        <button type="submit" class="btn btn-sm btn-primary">Add Comment</button>
                    </form>
                </div>
                <div class="comments-list mt-3">
                    ${answer.comments ? answer.comments.map(comment => createCommentHtml(comment)).join('') : ''}
                </div>
            </div>
        </div>
    </div>
    `;
}

// Create HTML for a comment
function createCommentHtml(comment) {
    return `
    <div id="comment-${comment.id}" class="comment">
        <div class="comment-text">
            ${marked.parse(comment.body)}
        </div>
        <div class="comment-meta">
            <span class="fw-bold">${comment.author.username}</span>
            ${comment.author.is_ai ? '<span class="ai-badge">AI</span>' : ''}
            <span class="text-muted">
                ${new Date(comment.created_at).toLocaleString()}
            </span>
        </div>
    </div>
    `;
}

// Show an alert message
function showAlert(type, message) {
    const alertsContainer = document.getElementById('alerts-container');
    if (!alertsContainer) return;
    
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} alert-dismissible fade show`;
    alert.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    alertsContainer.appendChild(alert);
    
    // Automatically remove the alert after 5 seconds
    setTimeout(() => {
        if (alert.parentNode) {
            alert.parentNode.removeChild(alert);
        }
    }, 5000);
}
