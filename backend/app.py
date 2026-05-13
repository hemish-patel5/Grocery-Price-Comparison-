from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
CORS(app)

WOOLWORTHS_STORE_ID = 9023
PAKNSAVE_STORE_ID   = "e1925ea7-01bc-4358-ae7c-c6502da5ab12"
NEWWORLD_STORE_ID   = "7508cf88-9fd0-4e71-b2f2-d564b1decf8d"

def search_woolworths(query):
    try:
        with httpx.Client(
            headers={
                "accept": "application/json",
                "user-agent": "Mozilla/5.0",
                "x-requested-with": "OnlineShopping.WebApp",
                "referer": "https://www.woolworths.co.nz/shop/searchproducts"
            },
            timeout=10.0
        ) as client:
            client.get("https://www.woolworths.co.nz")
            client.cookies.set("fulfilmentStoreId", str(WOOLWORTHS_STORE_ID), domain=".woolworths.co.nz")
            res = client.get("https://www.woolworths.co.nz/api/v1/products", params={
                "target": "search", "search": query, "size": 24
            })
            products = res.json().get("products", {}).get("items", [])

            def get_price(p):
                price = p.get("price", {})
                return price.get("salePrice") or price.get("originalPrice")

            return [
                {"name": p["name"], "price": f"{get_price(p):.2f}", "store": "Woolworths"}
                for p in products if get_price(p) is not None
            ]
    except Exception as e:
        print(f"Woolworths error: {e}")
        return []


def search_paknsave(query):
    try:
        with httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            timeout=15.0
        ) as client:
            token_res = client.post("https://www.paknsave.co.nz/api/user/get-current-user")
            token_res.raise_for_status()
            token = token_res.json().get("access_token")

            search_res = client.post(
                "https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products",
                json={
                    "storeId": PAKNSAVE_STORE_ID,
                    "hitsPerPage": 48,
                    "page": 0,
                    "sortOrder": "NI_POPULARITY_ASC",
                    "algoliaFacetQueries": [],
                    "algoliaQuery": {
                        "query": query,
                        "hitsPerPage": 48,
                        "page": 0,
                        "filters": f"stores:{PAKNSAVE_STORE_ID}",
                        "attributesToHighlight": [],
                    },
                },
                headers={"authorization": f"Bearer {token}"}
            )
            search_res.raise_for_status()

            return [
                {
                    "name": p.get("name", "Unknown"),
                    "price": f"{p.get('singlePrice', {}).get('price', 0) / 100:.2f}",
                    "store": "PAK'nSAVE"
                }
                for p in search_res.json().get("products", [])
            ]
    except Exception as e:
        print(f"PAK'nSAVE error: {e}")
        return []


def search_newworld(query):
    try:
        with httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            timeout=15.0
        ) as client:
            token_res = client.post("https://www.newworld.co.nz/api/user/get-current-user")
            token_res.raise_for_status()
            token = token_res.json().get("access_token")

            search_res = client.post(
                "https://api-prod.newworld.co.nz/v1/edge/search/paginated/products",
                json={
                    "storeId": NEWWORLD_STORE_ID,
                    "hitsPerPage": 48,
                    "page": 0,
                    "sortOrder": "NI_POPULARITY_ASC",
                    "algoliaFacetQueries": [],
                    "algoliaQuery": {
                        "query": query,
                        "hitsPerPage": 48,
                        "page": 0,
                        "filters": f"stores:{NEWWORLD_STORE_ID}",
                        "attributesToHighlight": [],
                    },
                },
                headers={"authorization": f"Bearer {token}"}
            )
            search_res.raise_for_status()

            return [
                {
                    "name": p.get("name", "Unknown"),
                    "price": f"{p.get('singlePrice', {}).get('price', 0) / 100:.2f}",
                    "store": "New World"
                }
                for p in search_res.json().get("products", [])
            ]
    except Exception as e:
        print(f"New World error: {e}")
        return []


@app.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    with ThreadPoolExecutor() as executor:
        woolworths_future = executor.submit(search_woolworths, query)
        paknsave_future   = executor.submit(search_paknsave, query)
        newworld_future   = executor.submit(search_newworld, query)
        results = (
            woolworths_future.result() +
            paknsave_future.result() +
            newworld_future.result()
        )

    results.sort(key=lambda x: float(x["price"]))
    return jsonify(results)


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
