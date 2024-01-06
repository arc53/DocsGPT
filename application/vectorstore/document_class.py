class Document(str):
    """Class for storing a piece of text and associated metadata."""

    def __new__(cls, page_content: str, metadata: dict):
        instance = super().__new__(cls, page_content)
        instance.page_content = page_content
        instance.metadata = metadata
        return instance
