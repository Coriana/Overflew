import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv
from datetime import datetime, timezone
from flask_wtf.csrf import CSRFProtect
import logging
from logging.handlers import RotatingFileHandler

# Load environment variables
load_dotenv()

# Initialize SQLAlchemy
db = SQLAlchemy()

# Initialize LoginManager
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

# Initialize CSRF protection
csrf = CSRFProtect()

def create_app(test_config=None):
    # Create and configure the app
    app = Flask(__name__, instance_relative_config=True)
    
    # Configure logging
    if not app.debug:
        # Ensure log directory exists
        if not os.path.exists('logs'):
            os.mkdir('logs')
        # Create a file handler for errors
        file_handler = RotatingFileHandler('logs/overflew.log', maxBytes=10240, backupCount=5)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
    else:
        # In debug mode, also set up console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        console_handler.setLevel(logging.DEBUG)
        app.logger.addHandler(console_handler)
        app.logger.setLevel(logging.DEBUG)
        
    app.logger.info('Overflew startup')
    
    # Configure the app
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('SECRET_KEY', 'dev'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///overflew.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    if test_config is None:
        # Load the instance config, if it exists, when not testing
        app.config.from_pyfile('config.py', silent=True)
    else:
        # Load the test config if passed in
        app.config.from_mapping(test_config)

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Initialize db with app
    db.init_app(app)

    # Initialize login manager with app
    login_manager.init_app(app)

    # Initialize CSRF protection with app
    csrf.init_app(app)

    # Initialize LLM worker threads
    if 'OPENAI_API_KEY' in os.environ:
        from app.services.llm_service import init_workers
        init_workers(app)
        app.logger.info("LLM workers initialized")
    else:
        app.logger.warning("OPENAI_API_KEY not set, LLM features will not be available")

    # Import and register blueprints
    from app.routes.auth import auth_bp
    from app.routes.main import main_bp
    from app.routes.questions import questions_bp
    from app.routes.answers import answers_bp
    from app.routes.admin import admin_bp
    from app.routes.api import api_bp
    from app.routes.comments import comments_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(questions_bp)
    app.register_blueprint(answers_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(comments_bp)

    # Import models
    from app.models import User, Question, Answer, Comment, Vote, Tag, QuestionTag, AIPersonality
    from app.models.site_settings import SiteSettings

    # Create tables and initialize settings
    with app.app_context():
        db.create_all()  # Make sure tables exist first
        SiteSettings.init_settings()
        app.logger.info('Database tables created and site settings initialized')

    # Create database tables
    @app.cli.command('init-db')
    def init_db():
        db.create_all()
        print('Database initialized!')

    # User loader callback
    @login_manager.user_loader
    def load_user(user_id):
        from app.models.user import User
        return User.query.get(int(user_id))
    
    # Add template context processors
    @app.context_processor
    def utility_processor():
        def current_year():
            return datetime.now().year
        return dict(current_year=current_year)
    
    # Add custom Jinja filters
    @app.template_filter('timesince')
    def timesince_filter(dt):
        """
        Returns a human-friendly relative time string like 
        "a minute ago" or "3 days ago" based on the elapsed time.
        """
        if dt is None:
            return ''
            
        if not isinstance(dt, datetime):
            dt = datetime.fromisoformat(str(dt))
            
        now = datetime.now(timezone.utc if dt.tzinfo else None)
        diff = now - dt
        
        seconds = diff.total_seconds()
        
        if seconds < 60:
            return 'just now'
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} {'minute' if minutes == 1 else 'minutes'} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} {'hour' if hours == 1 else 'hours'} ago"
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f"{days} {'day' if days == 1 else 'days'} ago"
        elif seconds < 2592000:
            weeks = int(seconds / 604800)
            return f"{weeks} {'week' if weeks == 1 else 'weeks'} ago"
        elif seconds < 31536000:
            months = int(seconds / 2592000)
            return f"{months} {'month' if months == 1 else 'months'} ago"
        else:
            years = int(seconds / 31536000)
            return f"{years} {'year' if years == 1 else 'years'} ago"

    @app.template_filter('highlight')
    def highlight_filter(text, query):
        """
        Highlights occurrences of query in text by wrapping them in 
        <span class="highlight">...</span> tags
        """
        if not query or not text:
            return text
            
        # Convert to string if not already
        if not isinstance(text, str):
            text = str(text)
            
        # Simple case-insensitive replacement
        # This is a simple implementation - for production use, 
        # consider using a more robust approach that preserves HTML
        query_lower = query.lower()
        result = ""
        remaining_text = text
        
        while remaining_text:
            i = remaining_text.lower().find(query_lower)
            if i == -1:
                result += remaining_text
                break
                
            # Add text before match
            result += remaining_text[:i]
            
            # Add highlighted match
            matched_text = remaining_text[i:i+len(query)]
            result += f'<span class="highlight">{matched_text}</span>'
            
            # Update remaining text
            remaining_text = remaining_text[i+len(query):]
            
        return result

    return app
