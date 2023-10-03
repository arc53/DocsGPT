# import necessary modules
import platform
import dotenv
from application.celery import celery
from flask import Flask, request, redirect
from application.core.settings import settings
from application.api.user.routes import user
from application.api.answer.routes import answer
from application.api.internal.routes import internal

# Redirect PosixPath to WindowsPath on Windows
if platform.system() == "Windows":
    import pathlib

    # Temporary alias to handle PosixPath on Windows
    temp = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath

# loading envirornment variables from a .env file
dotenv.load_dotenv()

# Create a Flask application instance
app = Flask(__name__)

# Register Blueprint for different parts of the application
app.register_blueprint(user)
app.register_blueprint(answer)
app.register_blueprint(internal)

# Set configuration settings for flask
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER = "inputs"
app.config["CELERY_BROKER_URL"] = settings.CELERY_BROKER_URL
app.config["CELERY_RESULT_BACKEND"] = settings.CELERY_RESULT_BACKEND
app.config["MONGO_URI"] = settings.MONGO_URI

# Configure Celery using celeryconfig file
celery.config_from_object("application.celeryconfig")

# Define route for the homepage
@app.route("/")
def home():
    """
    The frontend source code lives in the /frontend directory of the repository.
    """
    if request.remote_addr in ('0.0.0.0', '127.0.0.1', 'localhost', '172.18.0.1'):
        # If users locally try to access DocsGPT running in Docker,
        # they will be redirected to the Frontend application.
        return redirect('http://localhost:5173')
    else:
        # Handle other cases or render the default page
        return 'Welcome to DocsGPT Backend!'

# Define a function to handling CORS (CROSS-ORIGIN RESOURCE SHARING)
@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    # response.headers.add("Access-Control-Allow-Credentials", "true")
    return response

# Start the flask application if this script is executed directly
if __name__ == "__main__":
    app.run(debug=True, port=7091)
