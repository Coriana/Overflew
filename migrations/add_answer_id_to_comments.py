"""
Migration script to add answer_id column to the comments table to facilitate the transition
to the unified comment system.
"""

from app import create_app, db
import sqlite3
from sqlalchemy import text

def add_answer_id_column():
    # Create application context
    app = create_app()
    with app.app_context():
        print("Adding answer_id column to comments table...")
        
        # Check if column already exists
        try:
            db.session.execute(text("SELECT answer_id FROM comments LIMIT 1"))
            print("answer_id column already exists in comments table")
        except Exception:
            # Column doesn't exist, add it
            try:
                # For SQLite
                db.session.execute(text(
                    "ALTER TABLE comments ADD COLUMN answer_id INTEGER REFERENCES answers(id)"
                ))
                db.session.commit()
                print("Successfully added answer_id column to comments table")
            except Exception as e:
                db.session.rollback()
                print(f"Error adding answer_id column: {str(e)}")
                raise

        print("Migration complete.")

if __name__ == "__main__":
    add_answer_id_column()
