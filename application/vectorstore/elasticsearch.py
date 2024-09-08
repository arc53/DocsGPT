from application.vectorstore.base import BaseVectorStore
from application.core.settings import settings
from application.vectorstore.document_class import Document
import elasticsearch




class ElasticsearchStore(BaseVectorStore):
    _es_connection = None  # Class attribute to hold the Elasticsearch connection

    def __init__(self, path, embeddings_key, index_name=settings.ELASTIC_INDEX):
        super().__init__()
        self.path = path.replace("application/indexes/", "").rstrip("/")
        self.embeddings_key = embeddings_key
        self.index_name = index_name
        
        if ElasticsearchStore._es_connection is None:
            connection_params = {}
            if settings.ELASTIC_URL:
                connection_params["hosts"] = [settings.ELASTIC_URL]
                connection_params["http_auth"] = (settings.ELASTIC_USERNAME, settings.ELASTIC_PASSWORD)
            elif settings.ELASTIC_CLOUD_ID:
                connection_params["cloud_id"] = settings.ELASTIC_CLOUD_ID
                connection_params["basic_auth"] = (settings.ELASTIC_USERNAME, settings.ELASTIC_PASSWORD)
            else:
                raise ValueError("Please provide either elasticsearch_url or cloud_id.")

            

            ElasticsearchStore._es_connection = elasticsearch.Elasticsearch(**connection_params)
            
        self.docsearch = ElasticsearchStore._es_connection

    def connect_to_elasticsearch(
        *,
        es_url = None,
        cloud_id = None,
        api_key = None,
        username = None,
        password = None,
    ):
        try:
            import elasticsearch
        except ImportError:
            raise ImportError(
                "Could not import elasticsearch python package. "
                "Please install it with `pip install elasticsearch`."
            )

        if es_url and cloud_id:
            raise ValueError(
                "Both es_url and cloud_id are defined. Please provide only one."
            )

        connection_params = {}

        if es_url:
            connection_params["hosts"] = [es_url]
        elif cloud_id:
            connection_params["cloud_id"] = cloud_id
        else:
            raise ValueError("Please provide either elasticsearch_url or cloud_id.")

        if api_key:
            connection_params["api_key"] = api_key
        elif username and password:
            connection_params["basic_auth"] = (username, password)

        es_client = elasticsearch.Elasticsearch(
            **connection_params,
        )
        try:
            es_client.info()
        except Exception as e:
            raise e

        return es_client

    def search(self, question, k=2, index_name=settings.ELASTIC_INDEX, *args, **kwargs):
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key)
        vector = embeddings.embed_query(question)
        knn = {
            "filter": [{"match": {"metadata.store.keyword": self.path}}],
            "field": "vector",
            "k": k,
            "num_candidates": 100,
            "query_vector": vector,
        }
        full_query = {
            "knn": knn,
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "text": {
                                    "query": question,
                                }
                            }
                        }
                    ],
                    "filter": [{"match": {"metadata.store.keyword": self.path}}],
                }
            },
            "rank": {"rrf": {}},
        }
        resp = self.docsearch.search(index=self.index_name, query=full_query['query'], size=k, knn=full_query['knn'])
        # create Documents objects from the results page_content ['_source']['text'], metadata ['_source']['metadata']
        doc_list = []
        for hit in resp['hits']['hits']:
            
            doc_list.append(Document(page_content = hit['_source']['text'], metadata = hit['_source']['metadata']))
        return doc_list

    def _create_index_if_not_exists(
            self, index_name, dims_length
        ):

        if self._es_connection.indices.exists(index=index_name):
            print(f"Index {index_name} already exists.")

        else:

            indexSettings = self.index(
                dims_length=dims_length,
            )
            self._es_connection.indices.create(index=index_name, **indexSettings)

    def index(
            self,
            dims_length,
        ):
        return {
            "mappings": {
                "properties": {
                    "vector": {
                        "type": "dense_vector",
                        "dims": dims_length,
                        "index": True,
                        "similarity": "cosine",
                    },
                }
            }
        }

    def add_texts(
        self,
        texts,
        metadatas = None,
        ids = None,
        refresh_indices = True,
        create_index_if_not_exists = True,
        bulk_kwargs = None,
        **kwargs,
        ):
        
        from elasticsearch.helpers import BulkIndexError, bulk

        bulk_kwargs = bulk_kwargs or {}
        import uuid
        embeddings = []
        ids = ids or [str(uuid.uuid4()) for _ in texts]
        requests = []
        embeddings = self._get_embeddings(settings.EMBEDDINGS_NAME, self.embeddings_key)

        vectors = embeddings.embed_documents(list(texts))

        dims_length = len(vectors[0])

        if create_index_if_not_exists:
            self._create_index_if_not_exists(
                index_name=self.index_name, dims_length=dims_length
            )

        for i, (text, vector) in enumerate(zip(texts, vectors)):
            metadata = metadatas[i] if metadatas else {}

            requests.append(
                {
                    "_op_type": "index",
                    "_index": self.index_name,
                    "text": text,
                    "vector": vector,
                    "metadata": metadata,
                    "_id": ids[i],
                }
            )


        if len(requests) > 0:
            try:
                success, failed = bulk(
                    self._es_connection,
                    requests,
                    stats_only=True,
                    refresh=refresh_indices,
                    **bulk_kwargs,
                )
                return ids
            except BulkIndexError as e:
                print(f"Error adding texts: {e}")
                firstError = e.errors[0].get("index", {}).get("error", {})
                print(f"First error reason: {firstError.get('reason')}")
                raise e

        else:
            return []

    def delete_index(self):
        self._es_connection.delete_by_query(index=self.index_name, query={"match": {
                                      "metadata.store.keyword": self.path}},)
