import os
import openai
import threading
import queue
import time
from flask import current_app
from concurrent.futures import ThreadPoolExecutor

# Configure OpenAI client with environment variables
openai.api_key = os.environ.get('OPENAI_API_KEY')

# Set base URL if provided in environment
base_url = os.environ.get('OPENAI_BASE_URL')
if base_url:
    openai.api_base = base_url

# Create a ThreadPoolExecutor for concurrent LLM tasks
# Using ThreadPoolExecutor instead of manual thread management for better performance
MAX_WORKERS = int(os.environ.get('MAX_LLM_WORKERS', 3))
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Task queue for managing LLM requests
task_queue = queue.Queue()
# Flag to indicate if workers are running
workers_running = False
# Lock for synchronizing access to workers_running
worker_lock = threading.Lock()
# List to store worker threads
workers = []

def get_completion(prompt, max_tokens=4096, model=None):
    """
    Get a completion from the LLM
    
    Args:
        prompt (str): The prompt to send to the LLM
        max_tokens (int): Maximum number of tokens to generate
        model (str): The model to use (defaults to environment variable or fallback)
        
    Returns:
        str: The LLM's response text
    """
    try:
        # Use model from environment or fallback to default
        model_name = model or os.environ.get('OPENAI_MODEL', 'gpt-3.5-turbo-instruct')
        
        # Log the request to help debug
        current_app.logger.info(f"Sending request to LLM with model {model_name}")
        
        # Make API call using the OpenAI v0.28.0 API format
        response = openai.Completion.create(
            model=model_name,
            prompt=prompt,
            max_tokens=max_tokens,
            n=1,
            stop=None
        )
        
        current_app.logger.info(f"Received response from LLM with {len(response.choices[0].text)} characters")
        
        # Return the response text
        return response.choices[0].text.strip()
    except Exception as e:
        current_app.logger.error(f"Error in LLM completion: {str(e)}")
        return f"I apologize, but I'm having trouble generating a response right now."

def worker_loop(app):
    """Process tasks from the queue in a loop"""
    global task_queue, workers_running
    
    # Create app context
    with app.app_context():
        # Log worker startup
        app.logger.info("LLM worker thread started")
        print("LLM worker thread started")
        
        while True:
            try:
                # Check if we should stop
                with worker_lock:
                    if not workers_running:
                        app.logger.info("Worker thread shutting down")
                        break
                
                # Try to get a task from the queue
                try:
                    task_func, args, kwargs = task_queue.get(timeout=0.5)
                    app.logger.info(f"Processing task {task_func.__name__}")
                    print(f"Processing task {task_func.__name__}")
                except queue.Empty:
                    # If no task is available, try again
                    continue
                
                # Execute the task
                try:
                    task_func(*args, **kwargs)
                    app.logger.info(f"Task {task_func.__name__} completed")
                    print(f"Task {task_func.__name__} completed")
                except Exception as e:
                    app.logger.error(f"Error executing task {task_func.__name__}: {str(e)}")
                    print(f"Error executing task {task_func.__name__}: {str(e)}")
                
                # Mark the task as done
                task_queue.task_done()
                
            except Exception as e:
                app.logger.error(f"Error in worker thread: {str(e)}")
                print(f"Error in worker thread: {str(e)}")
                # Sleep briefly to avoid tight loop on error
                time.sleep(1)

def init_workers(app):
    """Initialize worker threads for processing LLM tasks"""
    global workers, workers_running, MAX_WORKERS
    
    with worker_lock:
        if workers_running:
            app.logger.info("Workers already running")
            return
        
        app.logger.info(f"Initializing {MAX_WORKERS} LLM worker threads")
        print(f"Initializing {MAX_WORKERS} LLM worker threads")
        workers_running = True
        
        for i in range(MAX_WORKERS):
            worker = threading.Thread(target=worker_loop, args=(app,), daemon=True, name=f"LLMWorker-{i}")
            worker.start()
            workers.append(worker)
            app.logger.info(f"Started worker thread {i+1}/{MAX_WORKERS}")
            print(f"Started worker thread {i+1}/{MAX_WORKERS}")

def shutdown_workers():
    """Shut down all worker threads"""
    global workers_running
    
    with worker_lock:
        workers_running = False
    
    # Wait for all tasks to complete
    task_queue.join()
    
    # Shutdown the executor
    executor.shutdown(wait=False)

def process_in_thread(app, func, *args, **kwargs):
    """Execute a function in a separate thread with app context"""
    def run_with_context():
        with app.app_context():
            try:
                print(f"Executing {func.__name__} in thread")
                app.logger.info(f"Executing {func.__name__} in thread")
                result = func(*args, **kwargs)
                print(f"Successfully completed {func.__name__} in thread")
                app.logger.info(f"Successfully completed {func.__name__} in thread")
                return result
            except Exception as e:
                error_msg = f"Error executing {func.__name__} in thread: {str(e)}"
                print(error_msg)
                app.logger.error(error_msg)
                # Re-raise the exception so the executor can handle it
                raise
                
    # Submit the task to the executor
    print(f"Submitting {func.__name__} to thread executor")
    return executor.submit(run_with_context)

def queue_task(task_func, *args, **kwargs):
    """
    Queue a task to be executed by a worker thread
    
    Args:
        task_func: Function to execute
        *args, **kwargs: Arguments to pass to the function
    """
    global workers_running
    
    parallel = kwargs.pop('parallel', False)
    print(f"Queue task: {task_func.__name__}, parallel={parallel}")
    
    try:
        # Get current Flask app
        app = current_app._get_current_object()
        
        # Make sure workers are running
        with worker_lock:
            if not workers_running:
                app.logger.info("Workers not running, initializing now")
                print("Workers not running, initializing now")
                init_workers(app)
        
        # If parallel execution is requested, run directly in a separate thread
        if parallel:
            app.logger.info(f"Executing task in parallel: {task_func.__name__}")
            print(f"Executing task in parallel: {task_func.__name__}")
            return process_in_thread(app, task_func, *args, **kwargs)
        
        # Otherwise add to queue for worker threads to process
        app.logger.info(f"Task queued: {task_func.__name__}")
        print(f"Task queued: {task_func.__name__}")
        task_queue.put((task_func, args, kwargs))
            
    except Exception as e:
        try:
            current_app.logger.error(f"Error queueing task: {str(e)}")
            print(f"Error queueing task: {str(e)}")
        except:
            # If we can't access current_app, just print
            print(f"Error queueing task: {str(e)}")
