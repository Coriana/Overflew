# Overflew

A Stack Overflow style Q&A platform for community-driven knowledge sharing. Overflew provides a clean, intuitive interface for asking questions, providing answers, and engaging in discussions through comments.

## Features

- User authentication (register, login, logout)
- Post questions and answers
- Comment on questions and answers
- Vote on questions, answers, and comments
- Rich text editor with markdown support
- Tag system for categorizing questions
- Search functionality
- Admin dashboard for platform management
  - User management (promote/demote admins, delete users)
  - Question and answer moderation
  - Tag management (edit, merge, delete)
  - Site statistics and monitoring

## Setup

1. Clone the repository
2. Create a virtual environment: `python -m venv venv`
3. Activate the virtual environment:
   - Windows: `venv\Scripts\activate`
   - Unix/MacOS: `source venv/bin/activate`
4. Install dependencies: `pip install -r requirements.txt`
5. Set up your OpenAI API key in the `.env` file (see `.env.example`)
6. Initialize the database: `flask init-db`
7. Create an admin user: `flask create-admin your_username`
8. Run the application: `flask run`

## Admin Dashboard

Access the admin dashboard at `/admin` (requires admin privileges)

### Admin features:
- **User Management**: View and manage user accounts, control admin privileges
- **Questions**: Moderate content, toggle questions open/closed
- **Tags**: Manage, edit, and merge tags for better categorization

## Technologies

- Flask (Python web framework)
- SQLite (Database)
- SQLAlchemy (ORM)
- HTML/CSS/JavaScript (Frontend)
- Bootstrap 5 (UI framework)
- Font Awesome (Icons)
- Flask-Login (Authentication)
- WTForms (Form handling)

## Project Structure

```
overflew/
├── app/
│   ├── models/          # Database models (User, Question, Answer, etc.)
│   ├── routes/          # Route handlers for different sections
│   ├── services/        # Business logic services (LLM, notifications, etc.)
│   ├── static/          # Static assets (CSS, JS, images)
│   ├── templates/       # Jinja2 HTML templates
│   └── __init__.py      # Application factory
├── migrations/          # Database migrations
├── tests/               # Unit and integration tests
├── .env.example         # Environment variables template
├── requirements.txt     # Dependencies
└── README.md            # This file
```

## License

MIT
