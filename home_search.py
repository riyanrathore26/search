"""Home search: returns both products and designers for the same query.

Product text priority (query_by_weights):
  design_headline > design_description > design_hashtags > RASIN
  > store_name > designer_name > country

Designer text priority:
  search_text (store_name, store_description, store_genres, store_tags, …)
  > first_name, last_name > bio > profile_tags > state
"""
from product_search import search_products, has_search_criteria
from designer_search import search_designers_core, empty_designers_block


def search_home(payload):
    if not has_search_criteria(payload):
        empty_products = {
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
        return empty_products, empty_designers_block()

    return search_products(payload), search_designers_core(payload)
