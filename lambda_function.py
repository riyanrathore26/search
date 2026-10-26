"""Main Lambda handler. Routes to products / designer / home search."""
import json
import logging
from product_search import search_products
from designer_search import search_designers, empty_designers_block
from home_search import search_home

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def make_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


def parse_payload(event):
    if not isinstance(event, dict):
        raise ValueError("Request payload must be a JSON object")

    if event.get("httpMethod") == "OPTIONS":
        return {"_options_request": True}

    payload = event
    if "body" in event:
        body = event["body"]
        if isinstance(body, str):
            if not body.strip():
                raise ValueError("Request body is empty")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ValueError("Request body contains invalid JSON") from exc
        elif isinstance(body, dict):
            payload = body
        elif body is None:
            raise ValueError("Request body is empty")
        else:
            raise ValueError("Request body must be a JSON object")

    if not isinstance(payload, dict):
        raise ValueError("Request payload must be a JSON object")
    return payload


def detect_search_type(payload):
    keys = [k for k in ("products_search", "designer_search", "home_search") if k in payload]
    if not keys:
        raise ValueError(
            "Payload must contain exactly one of: products_search, designer_search, home_search"
        )
    if len(keys) > 1:
        raise ValueError(f"Only one search type allowed. Found: {', '.join(keys)}")
    return keys[0], payload[keys[0]]


def empty_products_block():
    return {
        "Semantic_search": "",
        "region": "US",
        "price_field": "price_usd",
        "search_mode": "empty",
        "filters_applied": None,
        "sort_applied": "default order",
        "count": 0,
        "found": 0,
        "pagination": {"skip": 0, "limit": 20, "next_skip": 0},
        "products": [],
    }


def lambda_handler(event, context):
    try:
        payload = parse_payload(event)
        if payload.get("_options_request"):
            return make_response(200, {"message": "OK"})

        search_type, inner = detect_search_type(payload)
        if not isinstance(inner, dict):
            raise ValueError(f"{search_type} must be a JSON object")

        logger.info(
            "search_type=%s semantic=%r region=%r",
            search_type,
            (inner.get("Semantic_search") or "")[:80],
            inner.get("region"),
        )

        if search_type == "products_search":
            products_block = search_products(inner)
            designers_block = empty_designers_block()
        elif search_type == "designer_search":
            products_block = empty_products_block()
            designers_block = search_designers(inner)
        else:
            products_block, designers_block = search_home(inner)

        return make_response(200, {
            "search_type": search_type,
            "products": products_block,
            "designers": designers_block,
        })

    except ValueError as exc:
        logger.warning("Invalid search request: %s", exc)
        return make_response(400, {"error": str(exc)})
    except Exception:
        logger.exception("Search failed")
        return make_response(500, {"error": "Search failed. Check Lambda logs for details."})
