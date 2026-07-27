"""Production entrypoint.

Serves the Flask app with Waitress, a pure-Python WSGI server that runs on
Windows (gunicorn does not). Use this in production instead of `python app.py`,
which starts Flask's single-threaded debug server.

Importing `app` runs its module-level initialize_cache(), which starts the
background cache-refresh scheduler, so there is nothing else to bootstrap here.

Run it:
    python serve.py

Configure via .env / environment variables:
    HOST              interface to bind      (default 0.0.0.0 = all interfaces)
    PORT              port to listen on      (default 8080)
    WAITRESS_THREADS  worker thread count    (default 8)
"""
import os

from waitress import serve

# Importing app also loads .env (app.py calls load_dotenv() at import time) and
# starts the background scheduler, so read the env AFTER this import.
from app import app, logger

HOST = os.environ.get('HOST', '0.0.0.0')
PORT = int(os.environ.get('PORT', '8080'))
THREADS = int(os.environ.get('WAITRESS_THREADS', '8'))

if __name__ == '__main__':
    logger.info(f"Starting Waitress on {HOST}:{PORT} ({THREADS} threads)")
    serve(app, host=HOST, port=PORT, threads=THREADS)
