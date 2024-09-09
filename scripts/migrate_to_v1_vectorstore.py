import pymongo
import os

def migrate_to_v1_vectorstore_mongo():
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    db = client["docsgpt"]
    vectors_collection = db["vectors"]
    sources_collection = db["sources"]

    for vector in vectors_collection.find():
        if "location" in vector:
            del vector["location"]
        if "retriever" not in vector:
            vector["retriever"] = "classic"
            vector["remote_data"] = None
        vectors_collection.update_one({"_id": vector["_id"]}, {"$set": vector})

    # move data from vectors_collection to sources_collection
    for vector in vectors_collection.find():
        sources_collection.insert_one(vector)

    vectors_collection.drop()

    client.close()

def migrate_faiss_to_v1_vectorstore():
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    db = client["docsgpt"]
    vectors_collection = db["vectors"]

    for vector in vectors_collection.find():
        old_path = f"./application/indexes/{vector['user']}/{vector['name']}"
        new_path = f"./application/indexes/{vector['_id']}"
        try:
            os.rename(old_path, new_path)
        except OSError as e:
            print(f"Error moving {old_path} to {new_path}: {e}")

    client.close()

def migrate_mongo_atlas_vector_to_v1_vectorstore():
    client = pymongo.MongoClient("mongodb+srv://<username>:<password>@<cluster>/<dbname>?retryWrites=true&w=majority")
    db = client["docsgpt"]
    vectors_collection = db["vectors"]

    # mongodb atlas collection
    documents_collection = db["documents"]

    for vector in vectors_collection.find():
        documents_collection.update_many({"store": vector["user"] + "/" + vector["name"]}, {"$set": {"source_id": str(vector["_id"])}})

    client.close()

migrate_faiss_to_v1_vectorstore()
migrate_to_v1_vectorstore_mongo()