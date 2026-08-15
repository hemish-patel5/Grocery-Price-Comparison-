import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

UPLOAD_CHUNK_SIZE = 500
PROJECT_ROOT = Path(__file__).resolve().parents[2]

SCRAPER_COMMANDS = (
    (
        "Woolworths Central and West Auckland",
        ("-m", "backend.scrapers.woolies"),
    ),
    (
        "New World Auckland",
        ("-m", "backend.scrapers.newworld", "--upload", "--no-json"),
    ),
    (
        "PAK'nSAVE Auckland",
        ("-m", "backend.scrapers.paknsave", "--upload", "--no-json"),
    ),
)

_client = None


def get_client():
    global _client
    if _client is None:
        supabase_url = os.environ["SUPABASE_URL"].rstrip("/")
        if supabase_url.endswith("/rest/v1"):
            supabase_url = supabase_url.removesuffix("/rest/v1")
        _client = create_client(
            supabase_url,
            os.environ["SUPABASE_SERVICE_KEY"],
        )
    return _client


def newworld_store_name(store_key, store):
    address = store.get("address") or store.get("name")
    if address:
        return address
    return f"New World {store_key.replace('_', ' ').title()}"


def paknsave_store_name(store_key, store):
    display_name = store.get("address") or store.get("name")
    if display_name:
        return display_name
    return f"PAK'nSAVE {store_key.replace('_', ' ').title()}"


def get_or_create_store(store_key, store):
    client = get_client()

    client.table("woolies_stores").upsert({
        "store_key": store_key,
        "address": store["address"],
        "fulfilment_store_id": store["fulfilmentStoreId"],
        "area_id": store.get("areaId"),
        "pickup_address_id": store.get("pickupAddressId"),
    }, on_conflict="store_key").execute()

    result = (
        client.table("woolies_stores")
        .select("id")
        .eq("store_key", store_key)
        .execute()
    )
    return result.data[0]["id"]


def get_or_create_newworld_store(store_key, store):
    """Upsert a New World store without touching the Woolworths store table."""
    client = get_client()
    retailer_store_id = store.get("storeId") or store.get("store_id") or store.get("id")
    if not retailer_store_id:
        raise ValueError(f"Missing New World store ID for {store_key}")

    client.table("newworld_stores").upsert({
        "store_key": store_key,
        "retailer_store_id": str(retailer_store_id),
        "address": newworld_store_name(store_key, store),
    }, on_conflict="store_key").execute()

    result = (
        client.table("newworld_stores")
        .select("id")
        .eq("store_key", store_key)
        .execute()
    )
    return result.data[0]["id"]


def get_or_create_paknsave_store(store_key, store):
    """Upsert a PAK'nSAVE store into its retailer-specific store table."""
    client = get_client()
    retailer_store_id = store.get("storeId") or store.get("store_id") or store.get("id")
    if not retailer_store_id:
        raise ValueError(f"Missing PAK'nSAVE store ID for {store_key}")

    client.table("paknsave_stores").upsert({
        "store_key": store_key,
        "retailer_store_id": str(retailer_store_id),
        "address": paknsave_store_name(store_key, store),
    }, on_conflict="store_key").execute()

    result = (
        client.table("paknsave_stores")
        .select("id")
        .eq("store_key", store_key)
        .execute()
    )
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


def newworld_price_row(product, store_id):
    """Only the New World price data requested by the scraper contract."""
    return {
        "product_id": str(product["product_id"]),
        "store_id": store_id,
        "price": to_number(product.get("price")),
        "is_club_price": bool(product.get("is_club_price", False)),
    }


def paknsave_price_row(product, store_id):
    """Store the effective PAK'nSAVE price and its promotion flag."""
    return {
        "product_id": str(product["product_id"]),
        "store_id": store_id,
        "price": to_number(product.get("price")),
        "is_on_special": bool(product.get("is_on_special", False)),
    }


def upsert_chunked(client, table, rows, on_conflict, label):
    for start in range(0, len(rows), UPLOAD_CHUNK_SIZE):
        chunk = rows[start:start + UPLOAD_CHUNK_SIZE]
        client.table(table).upsert(chunk, on_conflict=on_conflict).execute()
        print(f"Uploaded {start + len(chunk)}/{len(rows)} {label}")


def upload_products(store_key, store, products):
    """Upload Woolworths data to its existing three tables."""
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
        client, "woolies_products",
        [catalog_row(p) for p in unique.values()],
        on_conflict="product_id", label="products",
    )
    upsert_chunked(
        client, "woolies_store_prices",
        [price_row(p, store_id) for p in unique.values()],
        on_conflict="product_id,store_id", label="prices",
    )

    # scrape time lives on the store, stamped once the upload succeeded
    client.table("woolies_stores").update({
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", store_id).execute()

    print(f"Upload complete: {len(unique)} products for {store['address']}")
    return len(unique)


def upload_newworld_products(store_key, store, products):
    """Upload New World data to its own products, prices and stores tables."""
    client = get_client()
    store_id = get_or_create_newworld_store(store_key, store)
    unique = {
        str(product["product_id"]): product
        for product in products
        if product.get("product_id")
    }

    upsert_chunked(
        client,
        "newworld_products",
        [catalog_row(product) for product in unique.values()],
        on_conflict="product_id",
        label="New World products",
    )
    upsert_chunked(
        client,
        "newworld_store_prices",
        [newworld_price_row(product, store_id) for product in unique.values()],
        on_conflict="product_id,store_id",
        label="New World prices",
    )
    client.table("newworld_stores").update({
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", store_id).execute()

    print(
        f"Upload complete: {len(unique)} New World products for "
        f"{newworld_store_name(store_key, store)}"
    )
    return len(unique)


def upload_paknsave_products(store_key, store, products):
    """Upload PAK'nSAVE data to its separate catalogue, price and store tables."""
    client = get_client()
    store_id = get_or_create_paknsave_store(store_key, store)
    unique = {
        str(product["product_id"]): product
        for product in products
        if product.get("product_id")
    }

    upsert_chunked(
        client,
        "paknsave_products",
        [catalog_row(product) for product in unique.values()],
        on_conflict="product_id",
        label="PAK'nSAVE products",
    )
    upsert_chunked(
        client,
        "paknsave_store_prices",
        [paknsave_price_row(product, store_id) for product in unique.values()],
        on_conflict="product_id,store_id",
        label="PAK'nSAVE prices",
    )
    client.table("paknsave_stores").update({
        "scraped_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", store_id).execute()

    print(
        f"Upload complete: {len(unique)} PAK'nSAVE products for "
        f"{paknsave_store_name(store_key, store)}"
    )
    return len(unique)


def validate_supabase_connection():
    """Fail before scraping if credentials or the database are unavailable."""
    missing = [
        name
        for name in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
        if not os.environ.get(name)
    ]
    if missing:
        raise RuntimeError(
            f"Missing {', '.join(missing)} in backend/.env"
        )

    try:
        (
            get_client()
            .table("woolies_stores")
            .select("id")
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise RuntimeError(
            "Could not connect to the configured Supabase database"
        ) from exc


def run_all_scrapers():
    """Scrape every configured retailer store and upload without JSON output."""
    validate_supabase_connection()
    failed = []

    print(
        "Starting all grocery scrapers. Products will be uploaded directly "
        "to Supabase.",
        flush=True,
    )
    for position, (label, arguments) in enumerate(SCRAPER_COMMANDS, 1):
        print(
            f"\n===== RETAILER [{position}/{len(SCRAPER_COMMANDS)}]: "
            f"{label} =====",
            flush=True,
        )
        result = subprocess.run(
            (sys.executable, *arguments),
            cwd=PROJECT_ROOT,
            check=False,
        )
        if result.returncode:
            failed.append(label)
            print(
                f"{label} exited with status {result.returncode}; "
                "continuing to the next retailer.",
                flush=True,
            )

    if failed:
        raise RuntimeError(
            "Scraper run finished with failures: " + ", ".join(failed)
        )

    print("\nAll retailer scrapers completed successfully.", flush=True)


if __name__ == "__main__":
    try:
        run_all_scrapers()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
