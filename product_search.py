"""
Product search module.
Use your proven Lambda product-search logic here.
"""
import json
import math
import os
import logging
from lambda_function import generate_s3_url, get_client, get_model

logger = logging.getLogger(__name__)


COLLECTION_NAME = "products"
MODEL_DATA_BUCKET = "wyidesigns-in"
DATE_FIELD = os.environ.get("DATE_FIELD", "action_date_time")
DEFAULT_LIMIT = 20
MAX_LIMIT = 250
MAX_VECTOR_K = 1000

FIELD_MAP = {
    "country": "country",
    "node_1": "Node-1 Art Style",
    "fit": "fit",
    "primary_color_code": "primary_color_code",
    "selectedClothingType": "selectedClothingType",
    "designer_country": "designer_country",
    "node_0": "node_0",
    "node_2": "node_2",
    "color": "color",
    "selectedCategory": "selectedCategory",
    "target_audience": "target_audience",
    "store_name": "store_name",
    "designer_name": "designer_name",
    "RASIN": "RASIN",
    "Node-0 Art Style": "Node-0 Art Style",
    "Node-1 Art Style": "Node-1 Art Style",
    "Node-2 Art Style": "Node-2 Art Style",
}



def generate_query_embedding(query):
    model = get_model()
    vectors = model.embed([query])
    vector = [float(value) for value in next(vectors)]
    if len(vector) != 384:
        raise ValueError(f"Expected 384 embedding dimensions, got {len(vector)}")
    return vector


def escape_filter_value(value):
    value = str(value)
    value = value.replace("\\", "\\\\")
    value = value.replace("`", "\\`")
    return f"`{value}`"


def parse_number(value, field_name):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def resolve_price_field(payload):
    region = (payload.get("region") or "").strip().upper()
    return "price_inr" if region == "IN" else "price_usd"


def build_filter_by(normal_search, filter_search, price_field):
    filters = []
    if not isinstance(normal_search, dict):
        raise ValueError("Normal_search must be a JSON object")

    for payload_key, value in normal_search.items():
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            raise ValueError(f"Normal_search.{payload_key} must be a scalar value")
        if payload_key not in FIELD_MAP:
            raise ValueError(
                f"Unsupported Normal_search field: {payload_key}. Add it to FIELD_MAP."
            )
        schema_field = FIELD_MAP[payload_key]
        if isinstance(value, bool):
            value = str(value).lower()
        filters.append(f"{schema_field}:={escape_filter_value(value)}")

    if not isinstance(filter_search, dict):
        raise ValueError("Filter_search must be a JSON object")

    filters.append("on_sale:=`yes`")

    range_search = filter_search.get("range_search") or {}
    if not isinstance(range_search, dict):
        raise ValueError("Filter_search.range_search must be a JSON object")

    min_price = parse_number(range_search.get("minPrice"), "Filter_search.range_search.minPrice")
    max_price = parse_number(range_search.get("maxPrice"), "Filter_search.range_search.maxPrice")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ValueError("minPrice cannot be greater than maxPrice")
    if min_price is not None and max_price is not None:
        filters.append(f"{price_field}:[{min_price}..{max_price}]")
    elif min_price is not None:
        filters.append(f"{price_field}:>={min_price}")
    elif max_price is not None:
        filters.append(f"{price_field}:<={max_price}")

    return " && ".join(filters) if filters else None


def build_sort_by(filter_search, price_field, semantic_query):
    if not isinstance(filter_search, dict):
        raise ValueError("Filter_search must be a JSON object")

    sort_options = filter_search.get("sort") or {}
    if not isinstance(sort_options, dict):
        raise ValueError("Filter_search.sort must be a JSON object")

    for legacy_key in ("low_to_hight", "hight_to_low"):
        if legacy_key in filter_search:
            sort_options.setdefault(legacy_key, filter_search[legacy_key])

    # Price sorts only — action_date_time is not in the products schema
    sort_mapping = {
        "low_to_hight": f"{price_field}:asc",
        "hight_to_low": f"{price_field}:desc",
        "price_low_to_high": f"{price_field}:asc",
        "price_high_to_low": f"{price_field}:desc",
    }

    enabled = [name for name, value in sort_options.items() if value is True]
    if len(enabled) > 1:
        raise ValueError("Enable only one sort option. Enabled: " + ", ".join(enabled))

    if not enabled or enabled[0] == "relevance":
        if semantic_query:
            return None
        if enabled and enabled[0] == "relevance":
            return "_text_match:desc"
        return None

    selected = enabled[0]
    if selected not in sort_mapping:
        raise ValueError(f"Unsupported sort option: {selected}")
    return sort_mapping[selected]


def validate_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object")

    normal_search = payload.get("Normal_search", {}) or {}
    filter_search = payload.get("Filter_search", {}) or {}
    pagination = payload.get("pagination", {}) or {}

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

    semantic_query = payload.get("Semantic_search", "")
    if semantic_query is None:
        semantic_query = ""
    if not isinstance(semantic_query, str):
        raise ValueError("Semantic_search must be a string")
    semantic_query = semantic_query.strip()

    return semantic_query, normal_search, filter_search, skip, limit


def has_search_criteria(payload):
    semantic_query = payload.get("Semantic_search", "")
    if isinstance(semantic_query, str) and semantic_query.strip():
        return True
    if semantic_query is not None and not isinstance(semantic_query, str):
        return True

    normal_search = payload.get("Normal_search", {}) or {}
    filter_search = payload.get("Filter_search", {}) or {}
    if not isinstance(normal_search, dict) or not isinstance(filter_search, dict):
        return True

    for value in normal_search.values():
        if value is not None and value != "":
            return True

    range_search = filter_search.get("range_search") or {}
    if isinstance(range_search, dict):
        for value in range_search.values():
            if value is not None and value != "":
                return True

    sort_search = filter_search.get("sort") or {}
    if isinstance(sort_search, dict):
        for value in sort_search.values():
            if value is True:
                return True

    return False


def search_products(payload, return_designer_ids=False):
    """
    Main product search entry point.
    If return_designer_ids=True, also returns a set of designer_id values
    (used by designer_search for priority merge).
    """
    if not has_search_criteria(payload):
        empty = {
            "Semantic_search": "",
            "region": "US",
            "price_field": "price_usd",
            "search_mode": "empty",
            "filters_applied": None,
            "sort_applied": "default order",
            "count": 0,
            "found": 0,
            "pagination": {"skip": 0, "limit": DEFAULT_LIMIT, "next_skip": 0},
            "products": [],
        }
        if return_designer_ids:
            return empty, set()
        return empty

    semantic_query, normal_search, filter_search, skip, limit = validate_payload(payload)
    price_field = resolve_price_field(payload)
    region = (payload.get("region") or "").strip().upper() or "US"

    filter_by = build_filter_by(normal_search, filter_search, price_field)
    sort_by = build_sort_by(filter_search, price_field, semantic_query)

    page = (skip // limit) + 1
    offset = skip % limit
    fetch_limit = limit + offset
    if fetch_limit > MAX_LIMIT:
        raise ValueError(
            "skip is not aligned with limit and would require fetching more than MAX_LIMIT results."
        )

    params = {
        "collection": COLLECTION_NAME,
        "query_by": (
            "design_headline,design_hashtags,design_description,"
            "RASIN,designer_name,store_name,country"
        ),
        "query_by_weights": "10,8,6,5,4,1,1",
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
    if sort_by:
        params["sort_by"] = sort_by

    client = get_client()
    response = client.multi_search.perform({"searches": [params]}, {})
    results = response.get("results", [])
    if not results:
        raise RuntimeError("Typesense returned no search result object")
    result = results[0]
    if result.get("error"):
        raise RuntimeError(result["error"])

    hits = result.get("hits", [])[offset : offset + limit]
    products = []
    designer_ids = set()

    for hit in hits:
        document = dict(hit.get("document", {}))
        document.pop("embedding", None)

        model_data = document.get("model_data", [])
        if isinstance(model_data, list):
            updated = []
            for model in model_data:
                if isinstance(model, dict):
                    model = dict(model)
                    if model.get("mockup_key"):
                        model["mockup_url"] = generate_s3_url(
                            MODEL_DATA_BUCKET, model["mockup_key"]
                        )
                    if model.get("resized_mockup_key"):
                        model["resized_mockup_url"] = generate_s3_url(
                            MODEL_DATA_BUCKET, model["resized_mockup_key"]
                        )
                updated.append(model)
            document["model_data"] = updated

        if "vector_distance" in hit:
            document["score"] = hit["vector_distance"]

        did = document.get("designer_id")
        if did:
            designer_ids.add(str(did))

        products.append(document)

    body = {
        "Semantic_search": semantic_query,
        "region": region,
        "price_field": price_field,
        "search_mode": "semantic" if semantic_query else "filter",
        "filters_applied": filter_by,
        "sort_applied": sort_by or "default order",
        "count": len(products),
        "found": result.get("found", len(products)),
        "pagination": {
            "skip": skip,
            "limit": limit,
            "next_skip": skip + len(products),
        },
        "products": products,
    }

    if return_designer_ids:
        return body, designer_ids
    return body