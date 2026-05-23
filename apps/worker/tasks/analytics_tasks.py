# apps/worker/tasks/analytics_tasks.py
import time
import random
from main import celery_app

@celery_app.task(
    name="tasks.analytics_tasks.calculate_locality_trends",
    bind=True,                          # Exposes 'self' instance so we can manually invoke explicit retries
    max_retries=5,                      # Give transient network hiccups a solid window to clear out
    autoretry_for=(Exception,),         # Target core connection or calculation operational failure states
    retry_backoff=True,                 # Enable exponential spacing growth intervals (e.g., 2s, 4s, 8s...)
    retry_backoff_max=300,              # Cap the ultimate delay boundary at 5 minutes
    retry_jitter=True                   # Inject random temporal variance to break up concurrent worker lock steps
)
def calculate_locality_trends(self, locality: str):
    """Pre-computes price distribution models and market velocity trends for a specific sub-market area."""
    # Fetch the unique task execution tracking handle provided by the Celery runtime engine
    celery_task_id = self.request.id
    
    print(f"[Analytics Worker] [{celery_task_id}] Received job signature for locality: {locality}")
    
    try:
        # Simulate a transient external system lock or database network timeout
        if random.random() < 0.3:  # Simulate a 30% arbitrary probability of temporary infrastructure failure
            print(f"[Infrastructure Notice] [{celery_task_id}] Simulated cloud query timed out. Initiating retry loop backoff...")
            raise ConnectionError("MongoDB Atlas multi-region cluster primary node changeover in progress.")
            
        # Execute normal heavy numerical calculation processes
        time.sleep(3)
        print(f"[Analytics Worker] [{celery_task_id}] Metrics compiled flawlessly for: {locality}")
        return {"locality": locality, "average_price_sqft": 4850.0, "status": "processed"}
        
    except Exception as exc:
        print(f"[Task Error Group] [{celery_task_id}] Processing state broken: {str(exc)}. Handing back to Celery framework handler.")
        # Re-raise the exception so Celery's native decorators can catch it and schedule the next backoff window
        raise exc