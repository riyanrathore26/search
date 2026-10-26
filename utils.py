"""Shared utilities — avoids circular imports between lambda_function and search modules."""
import os
import typesense
from fastembed import TextEmbedding

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
MODEL_DIR = os.environ.get("MODEL_DIR", "/opt/models")
MODEL_DATA_BUCKET = "wyidesigns-in"

TYPESENSE_HOST = os.environ.get("TYPESENSE_HOST", "nqdrsa2he6xj5w0tp.a1.typesense.net")
TYPESENSE_PORT = os.environ.get("TYPESENSE_PORT", "443")
TYPESENSE_PROTOCOL = os.environ.get("TYPESENSE_PROTOCOL", "https")
TYPESENSE_API_KEY = os.environ["TYPESENSE_API_KEY"]

_MODEL = None
_CLIENT = None


def get_model():
    global _MODEL
    if _MODEL is None:
        _MODEL = TextEmbedding(
            model_name=EMBEDDING_MODEL,
            cache_dir=MODEL_DIR,
            local_files_only=True,
        )
    return _MODEL


def get_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = typesense.Client({
            "nodes": [{
                "host": TYPESENSE_HOST,
                "port": TYPESENSE_PORT,
                "protocol": TYPESENSE_PROTOCOL,
            }],
            "api_key": TYPESENSE_API_KEY,
            "connection_timeout_seconds": 30,
        })
    return _CLIENT


def generate_s3_url(bucket, key):
    if not key:
        return None
    return f"https://{bucket}.s3.amazonaws.com/{key}"
