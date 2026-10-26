from fastembed import TextEmbedding

MODEL_NAME = "BAAI/bge-small-en-v1.5"
MODEL_DIR = "/opt/models"

print("Downloading and preparing embedding model...")

model = TextEmbedding(
    model_name=MODEL_NAME,
    cache_dir=MODEL_DIR,
)

embedding = list(model.embed(["Testing embedding model"]))[0]

assert len(embedding) == 384

print("Model ready.")
print("Embedding dimensions:", len(embedding))
