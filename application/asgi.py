from a2wsgi import WSGIMiddleware

from application.app import app as flask_app

asgi_app = WSGIMiddleware(flask_app)
