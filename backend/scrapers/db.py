import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

UPLOAD_CHUNK_SIZE = 500

_client = None


def get_client():
    global _client
    if _client is None:
        _client = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client


def get_or_create_store(store_key, store):
    client = get_client()

    client.table("stores").upsert({
        "store_key": store_key,
        "address": store["address"],
        "fulfilment_store_id": store["fulfilmentStoreId"],
        "area_id": store.get("areaId"),
        "pickup_address_id": store.get("pickupAddressId"),
    }, on_conflict="store_key").execute()

    result = client.table("stores").select("id").eq("store_key", store_key).execute()
    return result.data[0]["id"]


def to_number(value):
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def catalog_row(product):
    """Store-independent product info, stored once per unique product."""
    return {
        "product_id": str(product["product_id"]),
        "name": product["name"],
        "brand": product.get("brand"),
        "size": product.get("size"),
        "department": product.get("department"),
        "aisle": product.get("aisle"),
        "image_url": product.get("image_url"),
    }


def price_row(product, store_id):
    """Per-store prices for one product."""
    return {
        "product_id": str(product["product_id"]),
        "store_id": store_id,
        "price": to_number(product.get("price")),
        "original_price": to_number(product.get("original_price")),
        "sale_price": to_number(product.get("sale_price")),
        "unit_price": product.get("unit_price"),
    }


def upsert_chunked(client, table, rows, on_conflict, label):
    for start in range(0, len(rows), UPLOAD_CHUNK_SIZE):
        chunk = rows[start:start + UPLOAD_CHUNK_SIZE]
        client.table(table).upsert(chunk, on_conflict=on_conflict).execute()
        print(f"Uploaded {start + len(chunk)}/{len(rows)} {label}")


def upload_products(store_key, store, products):
    client = get_client()
    store_id = get_or_create_store(store_key, store)

    # keyed by product_id: upserting the same key twice in one statement
    # is a Postgres error
    unique = {
        str(p["product_id"]): p
        for p in products
        if p.get("product_id")
    }

    upsert_chunked(
        client, "products",
        [catalog_row(p) for p in unique.values()],
        on_conflict="product_id", label="products",
    )
    upsert_chunked(
        client, "store_prices",
        [price_row(p, store_id) for p in unique.values()],
        on_conflict="product_id,store_id", label="prices",
    )

    # scrape time lives on the store, stamped once the upload succeeded
    client.table("stores").update({
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", store_id).execute()

    print(f"Upload complete: {len(unique)} products for {store['address']}")
    return len(unique)
