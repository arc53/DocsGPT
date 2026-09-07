from flask import Blueprint

from docsgpt.api import api
from docsgpt.api.answer.routes.answer import AnswerResource
from docsgpt.api.answer.routes.base import answer_ns
from docsgpt.api.answer.routes.search import SearchResource
from docsgpt.api.answer.routes.stream import StreamResource


answer = Blueprint("answer", __name__)

api.add_namespace(answer_ns)


def init_answer_routes():
    api.add_resource(StreamResource, "/stream")
    api.add_resource(AnswerResource, "/api/answer")
    api.add_resource(SearchResource, "/api/search")


init_answer_routes()
