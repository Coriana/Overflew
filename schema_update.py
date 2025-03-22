"""
Schema update script for Overflew
This script updates the database schema to include the new is_answered field for questions.
Run this script after modifying the models but before restarting the application.
"""
from app import create_app, db
from app.models.question import Question
from sqlalchemy import text

app = create_app()

with app.app_context():
    # Check if the column exists
    try:
        # Try to query using raw SQL to check if column exists
        with db.engine.connect() as conn:
            result = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='questions'"))
            table_def = result.scalar()
            
            if "is_answered" in table_def:
                print("The is_answered field already exists in the Question model.")
            else:
                print("Adding is_answered field to Question model...")
                # Add the column using the correct API
                conn.execute(text('ALTER TABLE questions ADD COLUMN is_answered BOOLEAN DEFAULT FALSE'))
                conn.commit()
                print("Successfully added is_answered field to Question model.")
    except Exception as e:
        print(f"Error updating schema: {e}")
        
    print("Schema update complete.")
