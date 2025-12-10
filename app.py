"""
TabletTracker Application Entry Point

This file creates and exports the Flask application using the application factory pattern.
All routes are defined in blueprints under app/blueprints/
All business logic is in services under app/services/
All utilities are in app/utils/

To run the application:
    flask run
    
Or for production with gunicorn:
    gunicorn app:app
"""
from app import create_app

# Create the Flask application
app = create_app()

if __name__ == '__main__':
    # Development server
    app.run(debug=True, host='0.0.0.0', port=5000)
