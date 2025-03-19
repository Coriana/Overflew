"""
A utility script to promote a user to admin status.
Run this script with the username of the user you want to promote:
    python promote_admin.py username
"""

import sys
import os
from app import create_app, db
from app.models.user import User

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python promote_admin.py <username>")
        sys.exit(1)
        
    username = sys.argv[1]
    app = create_app()
    
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        
        if not user:
            print(f"User '{username}' not found!")
            sys.exit(1)
            
        if user.is_admin:
            print(f"User '{username}' is already an admin!")
        else:
            user.is_admin = True
            db.session.commit()
            print(f"User '{username}' has been promoted to admin!")
