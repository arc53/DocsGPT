from application.app import app
from application.core.settings import settings

if __name__ == "__main__":
    app.run(debug=settings.FLASK_DEBUG_MODE, port=7091)
