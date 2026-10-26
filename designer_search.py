"""Designer search module."""
import logging
from product_search import (
    generate_query_embedding,
    escape_filter_value,
    has_search_criteria,
    search_products,
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_VECTOR_K,
)
from utils import get_client, generate_s3_url, MODEL_DATA_BUCKET

logger = logging.getLogger(__name__)

DESIGNERS_COLLECTION = "designers"

# Actual schema fields (store_name / store_description / store_genres live
# inside stores[] and are already concatenated into search_text).
# Priority via weights:
#   search_text (includes store_name, store_description, store_genres) >
#   first_name, last_name > bio > profile_tags > state
DESIGNER_QUERY_BY = "search_text,first_name,last_name,bio,profile_tags,state"
DESIGNER_QUERY_WEIGHTS = "10,6,6,4,3,2"

DESIGNER_FIELD_MAP = {
    "country": "country",
    "state": "state",
    "first_name": "first_name",
    "last_name": "last_name",
    "profile_tags": "profile_tags",
    "node_0": "profile_tags",
    "node_1": "profile_tags",
    "node_2": "profile_tags",
    "Node-0 Art Style": "profile_tags",
    "Node-1 Art Style": "profile_tags",
    "Node-2 Art Style": "profile_tags",
}

TAG_KEYS = {
    "profile_tags", "node_0", "node_1", "node_2",
    "Node-0 Art Style", "Node-1 Art Style", "Node-2 Art Style",
}


def build_designer_filter_by(normal_search, region=None):
    """Build Typesense filter. Region is NOT auto-mapped to country
    (country stores full names like 'India', while region is IN/US for pricing).
    Pass country/state via Normal_search when you want to filter by location.
    """
    if not isinstance(normal_search, dict):
        raise ValueError("Normal_search must be a JSON object")

    filters = []
    for key, value in normal_search.items():
        if value is None or value == "":
            continue

        if isinstance(value, list):
            if key in TAG_KEYS:
                for v in value:
                    if v is not None and v != "":
                        filters.append(f"profile_tags:={escape_filter_value(v)}")
                continue
            raise ValueError(f"Normal_search.{key} must be a scalar or list")

        if key not in DESIGNER_FIELD_MAP:
            continue

        schema_field = DESIGNER_FIELD_MAP[key]
        if isinstance(value, bool):
            value = str(value).lower()
        filters.append(f"{schema_field}:={escape_filter_value(value)}")

    return " && ".join(filters) if filters else None


def validate_designer_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")

    normal_search = payload.get("Normal_search") or {}
    filter_search = payload.get("Filter_search") or {}
    pagination = payload.get("pagination") or {}

    if not isinstance(normal_search, dict):
        raise ValueError("Normal_search must be a JSON object")
    if not isinstance(filter_search, dict):
        raise ValueError("Filter_search must be a JSON object")
    if not isinstance(pagination, dict):
        raise ValueError("pagination must be a JSON object")

    try:
        skip = int(pagination.get("skip", 0))
        limit = int(pagination.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError) as exc:
        raise ValueError("pagination.skip and pagination.limit must be integers") from exc

    if skip < 0:
        raise ValueError("pagination.skip must be >= 0")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"pagination.limit must be between 1 and {MAX_LIMIT}")

    semantic_query = (payload.get("Semantic_search") or "").strip()
    region = (payload.get("region") or "").strip().upper() or "US"
    return semantic_query, normal_search, filter_search, skip, limit, region


def search_designers_core(payload):
    """
    Search designers collection.
    query_by priority (weights):
      search_text (store_name + store_description + store_genres + more) >
      first_name, last_name > bio > profile_tags > state
    """
    semantic_query, normal_search, filter_search, skip, limit, region = (
        validate_designer_payload(payload)
    )
    filter_by = build_designer_filter_by(normal_search, region)

    page = (skip // limit) + 1
    offset = skip % limit
    fetch_limit = limit + offset
    if fetch_limit > MAX_LIMIT:
        raise ValueError(
            "skip is not aligned with limit and would require fetching more than MAX_LIMIT results."
        )

    params = {
        "collection": DESIGNERS_COLLECTION,
        "query_by": DESIGNER_QUERY_BY,
        "query_by_weights": DESIGNER_QUERY_WEIGHTS,
        "per_page": fetch_limit,
        "page": page,
        "exclude_fields": "embedding",
    }

    if semantic_query:
        query_embedding = generate_query_embedding(semantic_query)
        vector_k = min(max(skip + limit, fetch_limit), MAX_VECTOR_K)
        params["q"] = semantic_query
        params["vector_query"] = f"embedding:({query_embedding}, k:{vector_k})"
    else:
        params["q"] = "*"

    if filter_by:
        params["filter_by"] = filter_by

    logger.info(
        "designer search q=%r filter_by=%r page=%s per_page=%s",
        params.get("q"),
        params.get("filter_by"),
        page,
        fetch_limit,
    )

    client = get_client()
    response = client.multi_search.perform({"searches": [params]}, {})
    results = response.get("results") or []
    if not results:
        raise RuntimeError("Typesense returned no designer search result")
    result = results[0]
    if result.get("error"):
        raise RuntimeError(result["error"])

    hits = result.get("hits", [])[offset : offset + limit]
    designers = []
    for hit in hits:
        designer = dict(hit.get("document") or {})
        designer.pop("embedding", None)
        if designer.get("profile_image_key"):
            designer["profile_image_url"] = generate_s3_url(
                MODEL_DATA_BUCKET, designer["profile_image_key"]
            )
        # enrich stores with S3 URLs when keys are present
        stores = designer.get("stores") or []
        if isinstance(stores, list):
            enriched = []
            for store in stores:
                if isinstance(store, dict):
                    store = dict(store)
                    if store.get("main_image_key") and not store.get("main_image_url"):
                        store["main_image_url"] = generate_s3_url(
                            MODEL_DATA_BUCKET, store["main_image_key"]
                        )
                    if store.get("cover_image_key") and not store.get("cover_image_url"):
                        store["cover_image_url"] = generate_s3_url(
                            MODEL_DATA_BUCKET, store["cover_image_key"]
                        )
                enriched.append(store)
            designer["stores"] = enriched
        if "vector_distance" in hit:
            designer["score"] = hit["vector_distance"]
        designers.append(designer)

    return {
        "search_mode": "semantic" if semantic_query else "filter",
        "query": semantic_query,
        "count": len(designers),
        "found": result.get("found", len(designers)),
        "pagination": {"skip": skip, "limit": limit, "next_skip": skip + len(designers)},
        "designers": designers,
    }


def fetch_designers_by_ids(user_ids, limit=50):
    if not user_ids:
        return []

    ids = [escape_filter_value(uid) for uid in user_ids]
    params = {
        "collection": DESIGNERS_COLLECTION,
        "q": "*",
        "filter_by": f"user_id:=[{','.join(ids)}]",
        "per_page": min(len(user_ids), limit),
        "exclude_fields": "embedding",
    }

    client = get_client()
    response = client.multi_search.perform({"searches": [params]}, {})
    results = response.get("results") or []
    if not results or results[0].get("error"):
        return []

    designers = []
    for hit in results[0].get("hits", []):
        designer = dict(hit.get("document") or {})
        designer.pop("embedding", None)
        if designer.get("profile_image_key"):
            designer["profile_image_url"] = generate_s3_url(
                MODEL_DATA_BUCKET, designer["profile_image_key"]
            )
        designers.append(designer)
    return designers


def empty_designers_block(skip=0, limit=DEFAULT_LIMIT):
    return {
        "search_mode": "empty",
        "query": "",
        "count": 0,
        "found": 0,
        "pagination": {"skip": skip, "limit": limit, "next_skip": skip},
        "designers": [],
    }


def search_designers(payload):
    """
    Designer search priority:
    1. Designers collection — search_text (includes store_name / description / genres)
       then first_name, last_name, bio, profile_tags, state
    2. Designers linked via products collection matches (secondary)
    """
    if not has_search_criteria(payload):
        return empty_designers_block()

    # 1) Primary: designers collection
    designer_result = search_designers_core(payload)
    direct = designer_result["designers"]
    seen = {str(d.get("user_id")) for d in direct if d.get("user_id")}

    # 2) Secondary: products collection → designer_ids not already found
    _, product_designer_ids = search_products(payload, return_designer_ids=True)
    missing = [uid for uid in product_designer_ids if uid not in seen]
    extra = fetch_designers_by_ids(missing)

    merged = direct + extra
    designer_result["designers"] = merged
    designer_result["count"] = len(merged)
    return designer_result
