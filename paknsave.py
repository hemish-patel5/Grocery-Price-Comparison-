from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx

app = Flask(__name__)
CORS(app)

STORE_ID = "e1925ea7-01bc-4358-ae7c-c6502da5ab12"

def fetch_paknsave_data(search_query):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }

    # 1. Use httpx.Client() instead of AsyncClient()
    with httpx.Client(headers=headers, timeout=15.0) as client:
        # Step 1: Get the access token
        token_url = "https://www.paknsave.co.nz/api/user/get-current-user"
        token_res = client.post(token_url) # Removed 'await'
        token_res.raise_for_status()
        token = token_res.json().get("access_token")

        # Step 2: Search for products
        search_url = "https://api-prod.paknsave.co.nz/v1/edge/search/paginated/products"
        search_payload = {
            "storeId": STORE_ID,
            "hitsPerPage": 48,
            "page": 0,
            "sortOrder": "NI_POPULARITY_ASC",
            "algoliaFacetQueries": [],
            "algoliaQuery": {
                "query": search_query,
                "hitsPerPage": 48,
                "page": 0,
                "filters": f"stores:{STORE_ID}",
                "attributesToHighlight": [],
            },
        }
        
        search_headers = {"authorization": f"Bearer {token}"}
        search_res = client.post(search_url, json=search_payload, headers=search_headers) # Removed 'await'
        search_res.raise_for_status()
        
        raw_products = search_res.json().get("products", [])
        
        formatted_products = []
        for p in raw_products:
            # Safer way to get price in case an item is missing it
            price_data = p.get("singlePrice", {}).get("price", 0)
            formatted_products.append({
                "name": p.get("name", "Unknown Product"),
                "price": f"{price_data / 100:.2f}",
                "store": "PAK'nSAVE"
            })
            
        formatted_products.sort(key=lambda x: float(x['price']))
        return formatted_products

@app.route('/api/search', methods=['GET'])
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify([])

    try:
        results = fetch_paknsave_data(query) # Removed 'await'
        return jsonify(results)
    except Exception as e:
        # This will print the EXACT error in your terminal/cmd
        print(f"DEBUG ERROR: {e}") 
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)