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
    
    // Initialize comments
    initializeCommentReplies();
    
    // Initialize comment sorting
    initializeCommentSorting();
    
    // Initialize comment deletes
    initializeCommentDeletes();
    
    // Initialize load more comments
    initializeLoadMoreComments();
    
    // Initialize AI response functionality
    initializeAIResponders();
    
    // Initialize mark as answered functionality
    initializeMarkAsAnswered();
    
    // Initialize real-time updates
    initializeRealtimeUpdates();
    
    // Initialize notification sound toggle
    initializeNotificationSoundToggle();
    
    // Comment toggle and sorting functionality
    // Toggle comments visibility
    document.querySelectorAll('.comments-toggle').forEach(toggle => {
        toggle.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            const commentsContainer = document.getElementById(targetId);
            
            if (commentsContainer) {
                commentsContainer.classList.toggle('collapsed');
                
                if (commentsContainer.classList.contains('collapsed')) {
                    const count = commentsContainer.querySelectorAll('.comment').length;
                    this.textContent = count > 3 ? `Show all ${count} comments` : `${count} comments`;
                } else {
                    this.textContent = 'Hide comments';
                }
            }
        });
    });
    
    // Sort comments
    document.querySelectorAll('.comment-sort-select').forEach(select => {
        select.addEventListener('change', function() {
            const targetId = this.getAttribute('data-target');
            const container = document.getElementById(targetId);
            const topLevelComments = Array.from(container.querySelectorAll('.comment')).filter(comment => {
                // Only get top-level comments
                return !comment.closest('.replies');
            });
            
            const sortType = this.value;
            
            // Sort comments based on selected option
            switch(sortType) {
                case 'votes':
                    topLevelComments.sort((a, b) => {
                        return parseInt(b.getAttribute('data-score')) - parseInt(a.getAttribute('data-score'));
                    });
                    break;
                case 'newest':
                    topLevelComments.sort((a, b) => {
                        return new Date(b.getAttribute('data-created')) - new Date(a.getAttribute('data-created'));
                    });
                    break;
                case 'oldest':
                    topLevelComments.sort((a, b) => {
                        return new Date(a.getAttribute('data-created')) - new Date(b.getAttribute('data-created'));
                    });
                    break;
            }
            
            // Re-append sorted top-level comments
            topLevelComments.forEach(comment => {
                container.appendChild(comment);
            });
        });
    });
    
    // Sort answers
    document.querySelector('.answer-sort-select')?.addEventListener('change', function() {
        const targetId = this.getAttribute('data-target');
        const container = document.getElementById(targetId);
        const answers = Array.from(container.querySelectorAll('.answer'));
        
        const sortType = this.value;
        
        // Sort answers based on selected option
        switch(sortType) {
            case 'votes':
                answers.sort((a, b) => {
                    // If answer is accepted, it should be first
                    if (a.classList.contains('accepted')) return -1;
                    if (b.classList.contains('accepted')) return 1;
                    
                    return parseInt(b.getAttribute('data-score')) - parseInt(a.getAttribute('data-score'));
                });
                break;
            case 'newest':
                answers.sort((a, b) => {
                    // If answer is accepted, it should be first
                    if (a.classList.contains('accepted')) return -1;
                    if (b.classList.contains('accepted')) return 1;
                    
                    return new Date(b.getAttribute('data-created')) - new Date(a.getAttribute('data-created'));
                });
                break;
            case 'oldest':
                answers.sort((a, b) => {
                    // If answer is accepted, it should be first
                    if (a.classList.contains('accepted')) return -1;
                    if (b.classList.contains('accepted')) return 1;
                    
                    return new Date(a.getAttribute('data-created')) - new Date(b.getAttribute('data-created'));
                });
                break;
        }
        
        // Re-append sorted answers
        answers.forEach(answer => {
            container.appendChild(answer);
        });
    });
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
    
    if (!window.appConfig.isAuthenticated) {
        // Store current URL before redirecting
        const currentUrl = window.location.pathname + window.location.search;
        window.location.href = window.appConfig.loginUrl + '?next=' + encodeURIComponent(currentUrl);
        return;
    }
    
    const button = e.currentTarget;
    const voteType = button.dataset.voteType === 'up' ? 1 : -1;
    const questionId = button.dataset.questionId || null;
    const commentId = button.dataset.commentId || null;
    
    // Get the vote count element
    const voteCount = button.parentElement.querySelector('.vote-count');
    const upButton = button.parentElement.querySelector('.vote-button[data-vote-type="up"]');
    const downButton = button.parentElement.querySelector('.vote-button[data-vote-type="down"]');
    
    // Check if clicking the same button
    const isVoted = button.classList.contains('voted');
    const newVoteType = isVoted ? 0 : voteType;  // Remove vote if clicking same button
    
    // Send vote to server
    fetch('/api/vote', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
            vote_type: newVoteType,
            question_id: questionId,
            comment_id: commentId
        }),
        credentials: 'same-origin'
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok');
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            // Update vote count
            const currentCount = parseInt(voteCount.textContent);
            if (isVoted) {
                // Remove vote
                voteCount.textContent = currentCount - voteType;
                button.classList.remove('voted');
            } else {
                // Add new vote
                voteCount.textContent = currentCount + newVoteType;
                // Remove voted class from both buttons
                upButton.classList.remove('voted');
                downButton.classList.remove('voted');
                // Add voted class to clicked button
                button.classList.add('voted');
            }
            
            // Show success message
            showNotification('success', 'Vote recorded successfully');
        } else {
            showNotification('error', data.error || 'Failed to record vote');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('error', 'An error occurred while voting');
    });
}

// Show notification
function showNotification(type, message) {
    // Remove any existing notifications
    document.querySelectorAll('.notification').forEach(n => n.remove());
    
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Add fade-out class after a delay
    setTimeout(() => {
        notification.classList.add('fade-out');
        // Remove notification after animation
        setTimeout(() => {
            notification.remove();
        }, 300);
    }, 2700);
}

// Update vote UI based on vote type
function updateVoteUI(voteContainer, voteType) {
    const upButton = voteContainer.querySelector('.vote-button[data-vote-type="up"]');
    const downButton = voteContainer.querySelector('.vote-button[data-vote-type="down"]');
    
    // Reset classes
    upButton.classList.remove('voted');
    downButton.classList.remove('voted');
    
    // Add the appropriate class based on the vote type
    if (voteType === 1) {
        upButton.classList.add('voted');
    } else if (voteType === -1) {
        downButton.classList.add('voted');
    }
}

// Check if the user is authenticated
function isUserAuthenticated() {
    return window.appConfig.isAuthenticated;
}

// Get CSRF token from meta tag
function getCsrfToken() {
    return document.querySelector('meta[name="csrf-token"]').getAttribute('content');
}

// Initialize AI responders for questions and comments
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

// Handle AI Response Form Submission
function handleAIResponseForm(e) {
    e.preventDefault();
    const form = e.currentTarget;
    const contentType = form.querySelector('#ai-response-content-type').value;
    const contentId = form.querySelector('#ai-response-content-id').value;
    const personalityId = form.querySelector('#ai-response-personality').value;
    
    // Show loading state
    const submitButton = form.querySelector('button[type="submit"]');
    const originalButtonText = submitButton.innerHTML;
    submitButton.disabled = true;
    submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
    
    // Check if the question is marked as answered
    const questionAnsweredElement = document.querySelector('meta[name="question-answered"]');
    if (questionAnsweredElement && questionAnsweredElement.getAttribute('content') === 'true') {
        showNotification('error', 'This question is marked as answered. AI responses are disabled.');
        submitButton.disabled = false;
        submitButton.innerHTML = originalButtonText;
        $('#ai-response-modal').modal('hide');
        return;
    }
    
    // Send the request to the API
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
    .then(response => {
        if (!response.ok) {
            return response.json().then(data => {
                throw new Error(data.error || 'Failed to generate AI response');
            });
        }
        return response.json();
    })
    .then(data => {
        // Reset the form and close the modal
        form.reset();
        $('#ai-response-modal').modal('hide');
        
        // Show success notification
        showNotification('success', 'AI response generated successfully');
        
        // If we're not using SSE for real-time updates, manually add the comment to the page
        if (!window.EventSource) {
            addNewCommentToPage(data.response);
        }
    })
    .catch(error => {
        console.error('Error generating AI response:', error);
        showNotification('error', error.message);
    })
    .finally(() => {
        // Reset button state
        submitButton.disabled = false;
        submitButton.innerHTML = originalButtonText;
    });
}

// Add AI response to the page
function addAIResponseToPage(contentType, contentId, response) {
    // Find the content container based on type
    let container;
    
    if (contentType === 'question') {
        container = document.querySelector(`.question-container[data-question-id="${contentId}"] .comments-container`);
    } else if (contentType === 'comment') {
        container = document.querySelector(`.comment[id="comment-${contentId}"] .replies`);
        
        // If there's no replies container yet, create one
        if (!container) {
            const commentEl = document.querySelector(`.comment[id="comment-${contentId}"]`);
            container = document.createElement('div');
            container.className = 'replies';
            commentEl.appendChild(container);
        }
    }
    
    // If container is found, add the response
    if (container) {
        container.insertAdjacentHTML('beforeend', response);
        
        // Apply syntax highlighting to any code blocks
        container.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightBlock(block);
        });
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
    const createdDate = new Date(comment.created_at);
    
    let commentHtml = `
        <div class="comment" id="comment-${comment.id}" data-score="${comment.score}" data-created="${comment.created_at}">
            <div class="comment-text">
                ${comment.html_content}
                <div class="comment-vote float-end">
                    <button class="vote-button" data-vote-type="up" data-comment-id="${comment.id}">
                        <i class="fa-solid fa-arrow-up"></i>
                    </button>
                    <span class="vote-count small">${comment.score}</span>
                </div>
            </div>
            <div class="comment-meta">
                – <a href="/profile/${comment.author.username}" class="fw-bold">${comment.author.username}</a>
                ${comment.author.is_ai ? '<span class="ai-badge">AI</span>' : ''}
                <span class="text-muted">
                    ${timeSince(createdDate)}
                </span>
                <a href="#" class="reply-link text-muted small" data-comment-id="${comment.id}">
                    reply
                </a>
                <a href="#" class="delete-comment-link text-muted text-danger small" data-comment-id="${comment.id}">
                    delete
                </a>
                <button class="comment-collapse-toggle float-end" title="Collapse thread">
                    <i class="fa-solid fa-minus"></i>
                </button>
            </div>
            
            <!-- Reply form (hidden by default) -->
            <div class="reply-form-container collapse" id="reply-form-${comment.id}">
                <form class="comment-form mt-2" action="/questions/${comment.question_id}/comments" method="post">
                    <input type="hidden" name="csrf_token" value="${getCsrfToken()}">
                    <input type="hidden" name="parent_comment_id" value="${comment.id}">
                    <div class="mb-2">
                        <textarea class="form-control form-control-sm" name="comment_body" rows="2" required placeholder="Reply to this comment..."></textarea>
                    </div>
                    <div class="d-flex justify-content-between">
                        <button type="submit" class="btn btn-sm btn-primary">Reply</button>
                        <button type="button" class="btn btn-sm btn-outline-secondary cancel-reply">Cancel</button>
                    </div>
                </form>
            </div>
            <div class="replies collapsed">
                ${comment.replies ? comment.replies.map(reply => createCommentHtml(reply)).join('') : ''}
            </div>
        </div>
    `;
    
    return commentHtml;
}

// Helper function to format time since a date
function timeSince(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    
    let interval = Math.floor(seconds / 31536000);
    if (interval >= 1) {
        return interval + " year" + (interval === 1 ? "" : "s") + " ago";
    }
    
    interval = Math.floor(seconds / 2592000);
    if (interval >= 1) {
        return interval + " month" + (interval === 1 ? "" : "s") + " ago";
    }
    
    interval = Math.floor(seconds / 86400);
    if (interval >= 1) {
        return interval + " day" + (interval === 1 ? "" : "s") + " ago";
    }
    
    interval = Math.floor(seconds / 3600);
    if (interval >= 1) {
        return interval + " hour" + (interval === 1 ? "" : "s") + " ago";
    }
    
    interval = Math.floor(seconds / 60);
    if (interval >= 1) {
        return interval + " minute" + (interval === 1 ? "" : "s") + " ago";
    }
    
    return "just now";
}

// Initialize comment reply functionality
function initializeCommentReplies() {
    // Handle reply links
    document.querySelectorAll('.reply-link').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            // Don't allow replies if not authenticated
            if (!window.appConfig.isAuthenticated) {
                const currentUrl = window.location.pathname + window.location.search;
                window.location.href = window.appConfig.loginUrl + '?next=' + encodeURIComponent(currentUrl);
                return;
            }
            
            const commentId = this.getAttribute('data-comment-id');
            const replyForm = document.getElementById(`reply-form-${commentId}`);
            
            // Toggle reply form visibility
            if (replyForm.classList.contains('show')) {
                replyForm.classList.remove('show');
            } else {
                // Hide all other reply forms first
                document.querySelectorAll('.reply-form-container.show').forEach(form => {
                    form.classList.remove('show');
                });
                replyForm.classList.add('show');
                
                // Focus on the textarea
                const textarea = replyForm.querySelector('textarea');
                if (textarea) {
                    textarea.focus();
                }
            }
        });
    });
    
    // Initialize collapsible comment threads
    initializeCommentCollapseToggles();
    
    // Handle cancel reply buttons
    document.querySelectorAll('.cancel-reply').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            const replyForm = this.closest('.reply-form-container');
            if (replyForm) {
                replyForm.classList.remove('show');
            }
        });
    });
    
    // Handle comment forms submission to include parent comment id
    document.querySelectorAll('.comment-form').forEach(form => {
        form.addEventListener('submit', function(e) {
            // Form submission is handled by the server
            // We use the hidden parent_comment_id field already included in the form
        });
    });
}

// Initialize collapsible comment threads
function initializeCommentCollapseToggles() {
    document.querySelectorAll('.comment-collapse-toggle').forEach(toggle => {
        toggle.addEventListener('click', function(e) {
            e.preventDefault();
            
            const comment = this.closest('.comment');
            const replies = comment.querySelector('.replies');
            
            if (replies) {
                if (replies.classList.contains('collapsed')) {
                    // Expand
                    replies.classList.remove('collapsed');
                    this.innerHTML = '<i class="fa-solid fa-minus"></i>';
                    this.setAttribute('title', 'Collapse thread');
                } else {
                    // Collapse
                    replies.classList.add('collapsed');
                    this.innerHTML = '<i class="fa-solid fa-plus"></i>';
                    this.setAttribute('title', 'Expand thread');
                }
            }
        });
    });
}

// Initialize comment delete functionality
function initializeCommentDeletes() {
    document.querySelectorAll('.delete-comment-link').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            
            if (!window.appConfig.isAuthenticated) {
                return;
            }
            
            if (!confirm('Are you sure you want to delete this comment? This action cannot be undone.')) {
                return;
            }
            
            const commentId = this.getAttribute('data-comment-id');
            
            // Send delete request to server
            fetch(`/api/comments/${commentId}/delete`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken()
                },
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Comment was deleted successfully, now update UI
                    const comment = document.getElementById(`comment-${commentId}`);
                    if (comment) {
                        // Mark content as deleted
                        const contentDiv = comment.querySelector('.comment-text');
                        contentDiv.innerHTML = '<em>[deleted]</em>';
                        
                        // Remove the author info
                        const authorLink = comment.querySelector('.comment-meta a');
                        if (authorLink) {
                            authorLink.parentNode.removeChild(authorLink);
                        }
                        
                        // Remove delete button
                        this.parentNode.removeChild(this);
                        
                        showNotification('success', 'Comment deleted successfully');
                    }
                } else {
                    showNotification('error', data.message || 'Failed to delete comment');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showNotification('error', 'An error occurred while deleting the comment');
            });
        });
    });
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

// Initialize comment sorting functionality
function initializeCommentSorting() {
    document.querySelectorAll('.comment-sort-select').forEach(select => {
        select.addEventListener('change', function() {
            const targetId = this.getAttribute('data-target');
            const container = document.getElementById(targetId);
            if (!container) return;
            
            const sortType = this.value;
            const comments = Array.from(container.querySelectorAll('.comment-level-0'));
            
            // Sort comments based on selected option
            if (sortType === 'votes') {
                comments.sort((a, b) => {
                    const scoreA = parseInt(a.getAttribute('data-score'), 10) || 0;
                    const scoreB = parseInt(b.getAttribute('data-score'), 10) || 0;
                    return scoreB - scoreA; // Highest votes first
                });
            } else if (sortType === 'newest') {
                comments.sort((a, b) => {
                    const dateA = new Date(a.getAttribute('data-created')) || new Date(0);
                    const dateB = new Date(b.getAttribute('data-created')) || new Date(0);
                    return dateB - dateA; // Newest first
                });
            } else if (sortType === 'oldest') {
                comments.sort((a, b) => {
                    const dateA = new Date(a.getAttribute('data-created')) || new Date(0);
                    const dateB = new Date(b.getAttribute('data-created')) || new Date(0);
                    return dateA - dateB; // Oldest first
                });
            } else if (sortType === 'controversial') {
                // A simple implementation - could be refined later
                comments.sort((a, b) => {
                    const scoreA = parseInt(a.getAttribute('data-score'), 10) || 0;
                    const scoreB = parseInt(b.getAttribute('data-score'), 10) || 0;
                    // If score is near zero, it might be controversial
                    return Math.abs(scoreA) - Math.abs(scoreB); // Smallest absolute score first
                });
            }
            
            // Re-append comments in the new order
            comments.forEach(comment => {
                container.appendChild(comment);
            });
        });
    });
    
    // Handle comment toggle (show/hide all comments)
    document.querySelectorAll('.comments-toggle').forEach(toggle => {
        toggle.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            const container = document.getElementById(targetId);
            if (container) {
                container.classList.toggle('collapsed');
                
                // Update text based on state
                if (container.classList.contains('collapsed')) {
                    const commentCount = container.querySelectorAll('.comment-level-0').length;
                    if (commentCount > 3) {
                        this.textContent = `Show all ${commentCount} comments`;
                    }
                } else {
                    this.textContent = 'Hide comments';
                }
            }
        });
    });
}

// Initialize load more comments functionality
function initializeLoadMoreComments() {
    // Handle "load more comments" buttons
    document.querySelectorAll('.load-more-comments').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            
            const parentId = this.getAttribute('data-parent-id');
            const parentComment = document.getElementById(`comment-${parentId}`);
            
            if (!parentComment) return;
            
            const repliesContainer = parentComment.querySelector('.replies');
            if (!repliesContainer) return;
            
            // Get the parent type and parent ID from the original comment
            const parentType = parentComment.querySelector('.reply-link').getAttribute('data-parent-type');
            const originalParentId = parentComment.querySelector('.reply-link').getAttribute('data-parent-id');
            
            // Show loading indicator
            this.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Loading...';
            
            // Fetch more comments via AJAX
            fetch(`/api/comments/children/${parentId}?skip=${repliesContainer.querySelectorAll('.comment').length}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.comments) {
                        // Insert new comments before the "load more" button
                        const currentButton = this;
                        let remainingCount = 0;
                        
                        data.comments.forEach(comment => {
                            // Create the comment HTML
                            const commentHtml = createCommentHtml(comment);
                            
                            // Insert the comment before the load more button
                            currentButton.insertAdjacentHTML('beforebegin', commentHtml);
                        });
                        
                        // Update the count or remove the button if no more comments
                        remainingCount = data.total_remaining;
                        if (remainingCount > 0) {
                            this.innerHTML = `<i class="fa-solid fa-angle-down"></i> Load ${remainingCount} more replies`;
                        } else {
                            this.remove();
                        }
                        
                        // Initialize event handlers for the new comments
                        initializeCommentReplies();
                        initializeCommentCollapseToggles();
                        initializeCommentDeletes();
                        initializeVoteButtons();
                    } else {
                        this.innerHTML = 'Error loading comments';
                    }
                })
                .catch(error => {
                    console.error('Error loading more comments:', error);
                    this.innerHTML = 'Error loading comments';
                });
        });
    });
    
    // Handle "continue this thread" indicators
    document.querySelectorAll('.comment-collapsed-indicator').forEach(indicator => {
        indicator.addEventListener('click', function(e) {
            e.preventDefault();
            
            const parentId = this.getAttribute('data-parent-id');
            
            // Open a modal or expand in-place
            const modal = new bootstrap.Modal(document.getElementById('continueThreadModal'));
            
            // Set the parent comment ID in the modal
            document.getElementById('continueThreadContent').setAttribute('data-parent-id', parentId);
            
            // Load the content
            loadContinuedThreadContent(parentId);
            
            // Show the modal
            modal.show();
        });
    });
}

// Load continued thread content
function loadContinuedThreadContent(parentId) {
    const contentContainer = document.getElementById('continueThreadContent');
    
    // Show loading indicator
    contentContainer.innerHTML = '<div class="text-center p-4"><i class="fa-solid fa-spinner fa-spin"></i> Loading comments...</div>';
    
    // Fetch nested comments via AJAX
    fetch(`/api/comments/thread/${parentId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && data.comments) {
                contentContainer.innerHTML = '';
                
                // Recursively create the thread HTML
                data.comments.forEach(comment => {
                    const commentHtml = createCommentHtml(comment);
                    contentContainer.insertAdjacentHTML('beforeend', commentHtml);
                });
                
                // Initialize event handlers for the loaded comments
                initializeCommentReplies();
                initializeCommentCollapseToggles();
                initializeCommentDeletes();
                initializeVoteButtons();
            } else {
                contentContainer.innerHTML = '<div class="alert alert-danger">Error loading comments</div>';
            }
        })
        .catch(error => {
            console.error('Error loading thread comments:', error);
            contentContainer.innerHTML = '<div class="alert alert-danger">Error loading comments</div>';
        });
}

// Initialize mark as answered functionality
function initializeMarkAsAnswered() {
    // Handle marking a question as answered
    document.querySelectorAll('.mark-answered-link').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            
            if (!isUserAuthenticated()) {
                showNotification('error', 'You must be logged in to mark a question as answered');
                return;
            }
            
            const questionId = this.getAttribute('data-question-id');
            
            // Send request to server
            fetch(`/questions/${questionId}/mark_answered`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken()
                },
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Reload the page to show the question as answered
                    window.location.reload();
                } else {
                    showNotification('error', data.message || 'Failed to mark question as answered');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showNotification('error', 'An error occurred while marking question as answered');
            });
        });
    });

    // Handle unmarking a question as answered
    document.querySelectorAll('.mark-unanswered-link').forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            
            if (!isUserAuthenticated()) {
                showNotification('error', 'You must be logged in to unmark a question as answered');
                return;
            }
            
            const questionId = this.getAttribute('data-question-id');
            
            // Send request to server
            fetch(`/questions/${questionId}/mark_unanswered`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken()
                },
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(data => {
                if (data.success) {
                    // Reload the page to show the question as not answered
                    window.location.reload();
                } else {
                    showNotification('error', data.message || 'Failed to unmark question as answered');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                showNotification('error', 'An error occurred while unmarking question as answered');
            });
        });
    });
}

// Initialize real-time updates for comments using Server-Sent Events (SSE)
function initializeRealtimeUpdates() {
    // Check if we're on a question page
    const questionIdElement = document.querySelector('meta[name="question-id"]');
    if (!questionIdElement) {
        console.log('No question ID found, skipping real-time updates');
        return;
    }
    
    const questionId = questionIdElement.getAttribute('content');
    if (!questionId) {
        console.log('Empty question ID, skipping real-time updates');
        return;
    }
    
    console.log(`Setting up real-time updates for question ID: ${questionId}`);
    
    // Get the highest comment ID currently on the page
    let highestCommentId = 0;
    document.querySelectorAll('.comment').forEach(comment => {
        const commentId = parseInt(comment.id.replace('comment-', ''));
        if (commentId > highestCommentId) {
            highestCommentId = commentId;
        }
    });
    
    console.log(`Highest comment ID found: ${highestCommentId}`);
    
    // Create an EventSource for SSE
    const eventSourceUrl = `/api/questions/${questionId}/stream?last_comment_id=${highestCommentId}`;
    console.log(`Connecting to SSE endpoint: ${eventSourceUrl}`);
    
    const eventSource = new EventSource(eventSourceUrl);
    
    // Handle incoming events
    eventSource.onmessage = function(event) {
        console.log('SSE message received:', event.data);
        
        const data = JSON.parse(event.data);
        
        // Ignore heartbeat events
        if (data.heartbeat) {
            console.log('Heartbeat received');
            return;
        }
        
        // Handle new comments
        if (data.comments && data.comments.length > 0) {
            console.log(`Received ${data.comments.length} new comments`);
            data.comments.forEach(comment => {
                console.log('Adding new comment to page:', comment);
                addNewCommentToPage(comment);
            });
        }
    };
    
    eventSource.onopen = function() {
        console.log('SSE connection opened');
    };
    
    eventSource.onerror = function(error) {
        console.error('SSE connection error:', error);
        eventSource.close();
        
        // Try to reconnect after a delay
        setTimeout(() => {
            console.log('Attempting to reconnect SSE...');
            initializeRealtimeUpdates();
        }, 5000);
    };
    
    // Close the connection when the page is unloaded
    window.addEventListener('beforeunload', () => {
        console.log('Closing SSE connection due to page unload');
        eventSource.close();
    });
}

// Add a new comment to the page
function addNewCommentToPage(comment) {
    console.log(`Processing new comment ID: ${comment.id}`);
    
    // Check if the comment already exists
    if (document.getElementById(`comment-${comment.id}`)) {
        console.log(`Comment ID ${comment.id} already exists on the page, skipping`);
        return;
    }
    
    // Check if the question is marked as answered
    const questionAnsweredElement = document.querySelector('meta[name="question-answered"]');
    if (questionAnsweredElement && questionAnsweredElement.getAttribute('content') === 'true') {
        console.log('Question is marked as answered, not adding new AI comments');
        // If this is an AI comment and the question is answered, don't add it
        if (comment.author && comment.author.is_ai) {
            return;
        }
    }
    
    if (comment.parent_comment_id) {
        // This is a reply to another comment
        const parentComment = document.getElementById(`comment-${comment.parent_comment_id}`);
        if (parentComment) {
            console.log(`Found parent comment ${comment.parent_comment_id}, adding as reply`);
            
            // Get or create the replies container
            let repliesContainer = parentComment.querySelector('.comment-replies');
            if (!repliesContainer) {
                repliesContainer = document.createElement('div');
                repliesContainer.className = 'comment-replies';
                parentComment.appendChild(repliesContainer);
            }
            
            // Create the comment element
            const commentElement = document.createElement('div');
            commentElement.className = 'comment';
            commentElement.id = `comment-${comment.id}`;
            commentElement.dataset.score = comment.score;
            commentElement.dataset.created = comment.created_at;
            
            // Determine the nesting level
            const parentLevelMatch = parentComment.className.match(/comment-level-(\d+)/);
            const parentLevel = parentLevelMatch ? parseInt(parentLevelMatch[1]) : 0;
            commentElement.classList.add(`comment-level-${parentLevel + 1}`);
            
            // Set the HTML content
            commentElement.innerHTML = `
                <div class="comment-thread-line"></div>
                <div class="comment-content">
                    <div class="comment-text">
                        ${comment.html_content}
                    </div>
                    <div class="comment-meta">
                        <div class="comment-vote me-2">
                            <button class="vote-button" data-vote-type="up" data-comment-id="${comment.id}">
                                <i class="fa-solid fa-arrow-up"></i>
                            </button>
                            <span class="vote-count">${comment.score}</span>
                            <button class="vote-button" data-vote-type="down" data-comment-id="${comment.id}">
                                <i class="fa-solid fa-arrow-down"></i>
                            </button>
                        </div>
                        <a href="/profile/${comment.author.username}" class="fw-bold">${comment.author.username}</a>
                        ${comment.author.is_ai ? '<span class="ai-badge">AI</span>' : ''}
                        <span class="text-muted">just now</span>
                        <button class="btn btn-sm btn-link reply-button" data-comment-id="${comment.id}">
                            <i class="fa-solid fa-reply"></i> Reply
                        </button>
                    </div>
                </div>
            `;
            
            // Add the comment to the replies container
            repliesContainer.appendChild(commentElement);
            
            // Initialize vote buttons for the new comment
            const voteButtons = commentElement.querySelectorAll('.vote-button');
            voteButtons.forEach(button => {
                button.addEventListener('click', handleVote);
            });
            
            // Initialize reply button
            const replyButton = commentElement.querySelector('.reply-button');
            if (replyButton) {
                replyButton.addEventListener('click', function() {
                    showReplyForm(comment.id);
                });
            }
            
            // Play a notification sound if available
            playNotificationSound();
        } else {
            console.log(`Parent comment ${comment.parent_comment_id} not found, cannot add reply`);
        }
    } else {
        // This is a top-level comment (answer to the question)
        const commentsContainer = document.querySelector('.thread-container');
        if (commentsContainer) {
            console.log('Adding as top-level comment');
            
            // Create the comment element
            const commentElement = document.createElement('div');
            commentElement.className = 'comment comment-level-0';
            commentElement.id = `comment-${comment.id}`;
            commentElement.dataset.score = comment.score;
            commentElement.dataset.created = comment.created_at;
            
            // Set the HTML content
            commentElement.innerHTML = `
                <div class="comment-content">
                    <div class="comment-text">
                        ${comment.html_content}
                    </div>
                    <div class="comment-meta">
                        <div class="comment-vote me-2">
                            <button class="vote-button" data-vote-type="up" data-comment-id="${comment.id}">
                                <i class="fa-solid fa-arrow-up"></i>
                            </button>
                            <span class="vote-count">${comment.score}</span>
                            <button class="vote-button" data-vote-type="down" data-comment-id="${comment.id}">
                                <i class="fa-solid fa-arrow-down"></i>
                            </button>
                        </div>
                        <a href="/profile/${comment.author.username}" class="fw-bold">${comment.author.username}</a>
                        ${comment.author.is_ai ? '<span class="ai-badge">AI</span>' : ''}
                        <span class="text-muted">just now</span>
                        <button class="btn btn-sm btn-link reply-button" data-comment-id="${comment.id}">
                            <i class="fa-solid fa-reply"></i> Reply
                        </button>
                    </div>
                </div>
            `;
            
            // Add the comment to the comments container
            commentsContainer.appendChild(commentElement);
            
            // Initialize vote buttons for the new comment
            const voteButtons = commentElement.querySelectorAll('.vote-button');
            voteButtons.forEach(button => {
                button.addEventListener('click', handleVote);
            });
            
            // Initialize reply button
            const replyButton = commentElement.querySelector('.reply-button');
            if (replyButton) {
                replyButton.addEventListener('click', function() {
                    showReplyForm(comment.id);
                });
            }
            
            // Play a notification sound if available
            playNotificationSound();
        } else {
            console.log('Comments container not found, cannot add top-level comment');
        }
    }
    
    // Show a notification for the new comment
    showNotification('info', `New comment from ${comment.author.username}`);
}

// Initialize the notification sound toggle
function initializeNotificationSoundToggle() {
    const toggle = document.getElementById('notification-sound-toggle');
    if (toggle) {
        // Check if there's a saved preference
        const soundEnabled = localStorage.getItem('notification-sound-enabled');
        if (soundEnabled !== null) {
            toggle.checked = soundEnabled === 'true';
        }
        
        // Save preference when changed
        toggle.addEventListener('change', function() {
            localStorage.setItem('notification-sound-enabled', toggle.checked);
            
            // Update the icon based on the toggle state
            const icon = toggle.nextElementSibling.querySelector('i');
            if (icon) {
                if (toggle.checked) {
                    icon.className = 'fa-solid fa-volume-high';
                } else {
                    icon.className = 'fa-solid fa-volume-xmark';
                }
            }
        });
        
        // Initialize the icon based on the saved preference
        const icon = toggle.nextElementSibling.querySelector('i');
        if (icon && soundEnabled !== null) {
            if (toggle.checked) {
                icon.className = 'fa-solid fa-volume-high';
            } else {
                icon.className = 'fa-solid fa-volume-xmark';
            }
        }
    }
}

// Function to play notification sound if enabled
function playNotificationSound() {
    const toggle = document.getElementById('notification-sound-toggle');
    if (toggle && toggle.checked) {
        const notificationSound = document.getElementById('notification-sound');
        if (notificationSound) {
            notificationSound.play().catch(e => console.log('Could not play notification sound', e));
        }
    }
}
