#!/usr/bin/env python3
"""
Migration script to convert conversation_id from DBRef to ObjectId in shared_conversations collection.
"""

import pymongo
import logging
from tqdm import tqdm
from bson.dbref import DBRef
from bson.objectid import ObjectId

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Configuration
MONGO_URI = "mongodb://localhost:27017/"
DB_NAME = "docsgpt"

def backup_collection(collection, backup_collection_name):
    """Backup collection before migration."""
    logger.info(f"Backing up collection {collection.name} to {backup_collection_name}")
    collection.aggregate([{"$out": backup_collection_name}])
    logger.info("Backup completed")

def migrate_conversation_id_dbref_to_objectid():
    """Migrate conversation_id from DBRef to ObjectId."""
    client = pymongo.MongoClient(MONGO_URI)
    db = client[DB_NAME]
    shared_conversations_collection = db["shared_conversations"]

    try:
        # Backup collection before migration
        backup_collection(shared_conversations_collection, "shared_conversations_backup")

        # Find all documents and filter for DBRef conversation_id in Python
        all_documents = list(shared_conversations_collection.find({}))
        documents_with_dbref = []

        for doc in all_documents:
            conversation_id_field = doc.get("conversation_id")
            if isinstance(conversation_id_field, DBRef):
                documents_with_dbref.append(doc)

        if not documents_with_dbref:
            logger.info("No documents with DBRef conversation_id found. Migration not needed.")
            return

        logger.info(f"Found {len(documents_with_dbref)} documents with DBRef conversation_id")

        # Process each document
        migrated_count = 0
        error_count = 0

        for doc in tqdm(documents_with_dbref, desc="Migrating conversation_id"):
            try:
                conversation_id_field = doc.get("conversation_id")

                # Extract the ObjectId from the DBRef
                dbref_id = conversation_id_field.id

                if dbref_id and ObjectId.is_valid(dbref_id):
                    # Update the document to use direct ObjectId
                    result = shared_conversations_collection.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"conversation_id": dbref_id}}
                    )

                    if result.modified_count > 0:
                        migrated_count += 1
                        logger.debug(f"Successfully migrated document {doc['_id']}")
                    else:
                        error_count += 1
                        logger.warning(f"Failed to update document {doc['_id']}")
                else:
                    error_count += 1
                    logger.warning(f"Invalid ObjectId in DBRef for document {doc['_id']}: {dbref_id}")

            except Exception as e:
                error_count += 1
                logger.error(f"Error migrating document {doc['_id']}: {e}")

        # Final verification
        all_docs_after = list(shared_conversations_collection.find({}))
        remaining_dbref = 0
        for doc in all_docs_after:
            if isinstance(doc.get("conversation_id"), DBRef):
                remaining_dbref += 1

        logger.info(f"Migration completed:")
        logger.info(f"  - Total documents processed: {len(documents_with_dbref)}")
        logger.info(f"  - Successfully migrated: {migrated_count}")
        logger.info(f"  - Errors encountered: {error_count}")
        logger.info(f"  - Remaining DBRef documents: {remaining_dbref}")

        if remaining_dbref == 0:
            logger.info("✅ Migration successful: All DBRef conversation_id fields have been converted to ObjectId")
        else:
            logger.warning(f"⚠️ Migration incomplete: {remaining_dbref} DBRef documents still exist")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        client.close()

if __name__ == "__main__":
    try:
        logger.info("Starting conversation_id DBRef to ObjectId migration...")
        migrate_conversation_id_dbref_to_objectid()
        logger.info("Migration completed successfully!")
    except Exception as e:
        logger.error(f"Migration failed due to error: {e}")
        logger.warning("Please verify database state or restore from backups if necessary.")
