"""
Entry point used when the app is hosted on Vercel.

Vercel looks for a WSGI application called `app` inside the api/ folder, so
this file just imports the Flask app from app.py in the project root.
Running locally still works the same way (python app.py).
"""

import os
import sys

# Make the project root importable, so "import app" finds app.py one level up.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import app  # noqa: E402  (the path setup above has to come first)
