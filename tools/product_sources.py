"""Product metadata: Open Beauty Facts. Safety reports: openFDA cosmetics."""

from collections import Counter
import time

import requests

from tools.common import HEADERS

BEAUTY = "https://world.openbeautyfacts.org"
FDA = "https://api.fda.gov/cosmetic/event.json"
FIELDS = "code,product_name,brands,categories,ingredients_text,ingredients,image_url"


def search_beauty_products(query: str, limit: int = 5) -> dict:
    """Search the community-maintained cosmetics database by product name."""
    try:
        response = requests.get(
            f"{BEAUTY}/cgi/search.pl",
            params={"search_terms": query, "search_simple": 1, "action": "process",
                    "json": 1, "page_size": min(max(limit, 1), 10), "fields": FIELDS},
            headers=HEADERS, timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return {"query": query, "total": data.get("count"),
                "products": [
                    {"barcode": p.get("code"), "name": p.get("product_name"),
                     "brand": p.get("brands"), "has_ingredients": bool(p.get("ingredients_text"))}
                    for p in data.get("products", [])
                ], "source": BEAUTY}
    except (requests.RequestException, ValueError) as exc:
        return {"query": query, "error": str(exc), "products": []}


def get_beauty_product(barcode: str) -> dict:
    """Look up one product. Original ingredient text is kept for verification."""
    try:
        response = requests.get(
            f"{BEAUTY}/api/v2/product/{barcode}",
            params={"fields": FIELDS}, headers=HEADERS, timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") != 1:
            return {"barcode": barcode, "error": "Product not found"}
        p = data.get("product", {})
        return {"barcode": barcode, "name": p.get("product_name"),
                "brand": p.get("brands"), "categories": p.get("categories"),
                "ingredients_text": p.get("ingredients_text"),
                "ingredients": [{"id": x.get("id"), "text": x.get("text")}
                                for x in p.get("ingredients", [])],
                "image_url": p.get("image_url"),
                "source": f"{BEAUTY}/product/{barcode}",
                "note": "Crowdsourced entries may be incomplete, outdated or incorrectly parsed."}
    except (requests.RequestException, ValueError) as exc:
        return {"barcode": barcode, "error": str(exc)}


def search_fda_cosmetic_reports(product_name: str, limit: int = 100) -> dict:
    """Search cosmetic adverse-event reports; not a causal finding or risk rate."""
    product_name = product_name.replace('"', " ").strip()
    try:
        response = requests.get(
            FDA,
            params={"search": f'products.product_name:"{product_name}"',
                    "limit": min(max(limit, 1), 100)},
            timeout=30,
        )
        if response.status_code == 404:
            return {"query": product_name, "total_matching_reports": 0,
                    "reports_retrieved": 0, "reactions": [], "products": [],
                    "source": "https://open.fda.gov/apis/cosmetic/event/"}
        response.raise_for_status()
        data = response.json()
        reports = data.get("results", [])
        reactions, products = Counter(), Counter()
        for report in reports:
            reactions.update(x for x in report.get("reactions", []) if isinstance(x, str))
            products.update(x.get("product_name") for x in report.get("products", [])
                            if x.get("product_name"))
        return {"query": product_name,
                "total_matching_reports": data.get("meta", {}).get("results", {}).get("total", 0),
                "reports_retrieved": len(reports),
                "reactions": [{"name": name, "count": count} for name, count in reactions.most_common(12)],
                "products": [{"name": name, "count": count} for name, count in products.most_common(12)],
                "source": "https://open.fda.gov/apis/cosmetic/event/",
                "warning": "Reports do not establish causation or product-specific incidence rates. Multiple products/reactions can appear in one report."}
    except (requests.RequestException, ValueError) as exc:
        return {"query": product_name, "error": str(exc)}
