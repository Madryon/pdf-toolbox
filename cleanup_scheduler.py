import atexit

from apscheduler.schedulers.background import BackgroundScheduler


def start_cleanup_scheduler(cleanup_func):
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(cleanup_func, "interval", minutes=30, id="cleanup")
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    return scheduler
