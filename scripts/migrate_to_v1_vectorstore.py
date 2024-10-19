import pymongo
import os
import shutil
import logging
from tqdm import tqdm

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Configuration
MONGO_URI = "mongodb://localhost:27017/"
MONGO_ATLAS_URI = "mongodb+srv://<username>:<password>@<cluster>/<dbname>?retryWrites=true&w=majority"
DB_NAME = "docsgpt"

def backup_collection(collection, backup_collection_name):
    logger.info(f"Backing up collection {collection.name} to {backup_collection_name}")
    collection.aggregate([{"$out": backup_collection_name}])
    logger.info("Backup completed")

def migrate_to_v1_vectorstore_mongo():
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]
    vectors_collection = db["vectors"]
    sources_collection = db["sources"]

    # Backup collections before migration
    backup_collection(vectors_collection, "vectors_backup")
    backup_collection(sources_collection, "sources_backup")

    vectors = list(vectors_collection.find())
    for vector in tqdm(vectors, desc="Updating vectors"):
        if "location" in vector:
            del vector["location"]
        if "retriever" not in vector:
            vector["retriever"] = "classic"
            vector["remote_data"] = None
        vectors_collection.update_one({"_id": vector["_id"]}, {"$set": vector})

    # Move data from vectors_collection to sources_collection
    for vector in tqdm(vectors, desc="Moving to sources"):
        sources_collection.insert_one(vector)

    vectors_collection.drop()
    client.close()
    logger.info("Migration completed")

def migrate_faiss_to_v1_vectorstore():
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]
    vectors_collection = db["vectors"]

    vectors = list(vectors_collection.find())
    for vector in tqdm(vectors, desc="Migrating FAISS vectors"):
        old_path = f"./application/indexes/{vector['user']}/{vector['name']}"
        new_path = f"./application/indexes/{vector['_id']}"
        try:
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.move(old_path, new_path)
        except OSError as e:
            logger.error(f"Error moving {old_path} to {new_path}: {e}")

    client.close()
    logger.info("FAISS migration completed")

def migrate_mongo_atlas_vector_to_v1_vectorstore():
    client = pymongo.MongoClient(MONGO_ATLAS_URI)
    db = client[DB_NAME]
    vectors_collection = db["vectors"]
    documents_collection = db["documents"]

    # Backup collections before migration
    backup_collection(vectors_collection, "vectors_backup")
    backup_collection(documents_collection, "documents_backup")

    vectors = list(vectors_collection.find())
    for vector in tqdm(vectors, desc="Updating Mongo Atlas vectors"):
        documents_collection.update_many(
            {"store": vector["user"] + "/" + vector["name"]},
            {"$set": {"source_id": str(vector["_id"])}}
        )

    client.close()
    logger.info("Mongo Atlas migration completed")

if __name__ == "__main__":
    migrate_faiss_to_v1_vectorstore()
    migrate_to_v1_vectorstore_mongo()
    migrate_mongo_atlas_vector_to_v1_vectorstore()
