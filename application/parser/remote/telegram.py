from langchain.document_loader import TelegramChatApiLoader, TelegramChatFileLoader
from application.parser.remote.base import BaseRemote

class TelegramChatApiRemote(BaseRemote):
    def _init_parser(self, *args, **load_kwargs):
        self.loader = TelegramChatApiLoader(**load_kwargs)
        return {}

    def parse_file(self, *args, **load_kwargs):

        return text