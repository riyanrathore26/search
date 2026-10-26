"""
Home search module.
Returns both products and designers for the same query.
"""
from product_search import search_products, has_search_criteria
from designer_search import search_designers_core, empty_designers_block


def search_home(payload):
    """
    home_search entry point.
    Runs product search + designer search independently and returns both.
    """
    if not has_search_criteria(payload):
        from product_search import search_products as _
        empty_products = search_products({})  # will hit empty path via has_search_criteria
        # safer explicit empty:
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

    products_block = search_products(payload)
    designers_block = search_designers_core(payload)
    return products_block, designers_block