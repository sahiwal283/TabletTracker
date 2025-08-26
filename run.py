"""
Application entry point for the refactored TabletTracker
"""

from app import create_app
from app.config import Config

app = create_app(Config)

if __name__ == '__main__':
    app.run(debug=True, port=5001)
