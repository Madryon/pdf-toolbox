import threading


def start_cleanup_scheduler(cleanup_func, interval_seconds=3600):
    def _run():
        while True:
            threading.Event().wait(interval_seconds)
            try:
                cleanup_func()
            except Exception:
                pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
