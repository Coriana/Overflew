# Overflew Migration Guide: Answer to Comment System

This guide outlines the steps to migrate from the old Answer-based system to the new unified Comment system where answers are stored as top-level comments.

## Database Migration Process

### Option 1: Clean Database Rebuild

If you want to start fresh with a new database:

1. Delete the existing database file:
   ```
   del instance\overflew.db
   ```

2. Initialize a new database:
   ```
   flask db init
   flask db migrate -m "Initial migration"
   flask db upgrade
   ```

3. Run the application setup script to create test data:
   ```
   python setup.py
   ```

### Option 2: Migrate Existing Data

If you have existing data you want to preserve:

1. Make sure your database schema is up to date:
   ```
   flask db migrate -m "Add comment fields"
   flask db upgrade
   ```

2. Run the migration script to convert answers to comments:
   ```
   python migrations/add_answer_id_to_comments.py
   python migrations/migrate_answers_to_comments.py
   ```

## Model Changes

The following changes were made to the data models:

1. **Vote Model**: 
   - Removed `answer_id` column
   - Updated unique constraints
   - Modified `__init__` method to remove `answer_id` parameter

2. **Comment Model**:
   - Added a temporary `answer_id` field to facilitate migration
   - Added `is_accepted` field to mark comments that are accepted answers
   - Added `is_answer` property to identify top-level comments

3. **Question Model**:
   - Updated the `answers` property to return top-level comments

## API Changes

The API endpoints have been updated to work with the unified comment system:

1. All vote API endpoints now use only `question_id` and `comment_id`
2. Answer-specific endpoints are now handled by comment endpoints
3. The reputation system has been updated to give proper points for comments that are answers

## Testing After Migration

After completing the migration, test the following functionality:

1. Viewing questions with their answers (displayed as top-level comments)
2. Voting on questions and comments
3. Adding new comments as answers to questions
4. Replying to existing comments
5. Accepting a comment as the answer to a question
6. AI responses to votes and comments

If any issues are found, check the application logs for error messages and verify that all references to the Answer model have been properly updated.
