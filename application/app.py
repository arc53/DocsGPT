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

    temp = pathlib.PosixPath
    pathlib.PosixPath = pathlib.WindowsPath

# loading the .env file
dotenv.load_dotenv()



app = Flask(__name__)
app.register_blueprint(user)
app.register_blueprint(answer)
app.register_blueprint(internal)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER = "inputs"
app.config["CELERY_BROKER_URL"] = settings.CELERY_BROKER_URL
app.config["CELERY_RESULT_BACKEND"] = settings.CELERY_RESULT_BACKEND
app.config["MONGO_URI"] = settings.MONGO_URI
celery.config_from_object("application.celeryconfig")



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




# handling CORS
@app.after_request
def after_request(response):
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
    # response.headers.add("Access-Control-Allow-Credentials", "true")
    return response


if __name__ == "__main__":
    app.run(debug=True, port=7091)
