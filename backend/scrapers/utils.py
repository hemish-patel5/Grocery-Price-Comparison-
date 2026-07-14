from urllib.parse import urljoin


def get_path(data, path):
    value = data
    for key in path:
        if isinstance(value, dict):
            value = value.get(key)
            continue

        if isinstance(value, list) and isinstance(key, int):
            if key >= len(value):
                return None
            value = value[key]
            continue

        return None
    return value


def first_value(data, paths):
    for path in paths:
        value = get_path(data, path)
        if value not in (None, ""):
            return value
    return None


def strip_brand_prefix(name, brand):
    """Retailer product names repeat the brand as a prefix ('anchor calci
    yum...' with brand 'anchor'); the brand is stored separately, so keep
    only the descriptive part. Only strips at a word boundary (brand 'chef'
    must not eat into 'chefs choice') and falls back to the full name if
    stripping would leave nothing."""
    if name and brand and name.lower().startswith(brand.lower()):
        rest = name[len(brand):]
        if rest[:1] in ("", " "):
            return rest.lstrip() or name
    return name


def format_price(value):
    if value is None:
        return None

    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return None


def find_image_url(data):
    image_keys = {
        "image",
        "imageUrl",
        "imageURL",
        "imageUri",
        "imagePath",
        "productImage",
        "productImageUrl",
        "thumbnail",
        "thumbnailUrl",
    }
    url_keys = ("url", "href", "src", "big", "large", "medium", "small")

    if isinstance(data, dict):
        for url_key in url_keys:
            value = data.get(url_key)
            if isinstance(value, str) and value:
                return value

        for key in image_keys:
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                for url_key in url_keys:
                    nested_value = value.get(url_key)
                    if isinstance(nested_value, str) and nested_value:
                        return nested_value
            if isinstance(value, list):
                found = find_image_url(value)
                if found:
                    return found

        for key in ("images", "productImages", "media"):
            value = data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        for url_key in url_keys:
                            nested_value = item.get(url_key)
                            if isinstance(nested_value, str) and nested_value:
                                return nested_value

                    found = find_image_url(item)
                    if found:
                        return found
            else:
                found = find_image_url(value)
                if found:
                    return found

        for value in data.values():
            found = find_image_url(value)
            if found:
                return found

    if isinstance(data, list):
        for item in data:
            found = find_image_url(item)
            if found:
                return found

    return None


def absolute_url(value, base_url):
    if not value:
        return None
    return urljoin(base_url, str(value))


def format_unit_price(price, measure):
    formatted_price = format_price(price)
    if not formatted_price:
        return None
    if not measure:
        return formatted_price
    return f"{formatted_price} / {measure}"


def parse_store_id(value, default_store_id):
    if value in (None, ""):
        return default_store_id

    try:
        return int(value)
    except (TypeError, ValueError):
        return default_store_id


def dedupe_products(products):
    seen = set()
    deduped = []

    for product in products:
        key = (
            product.get("store"),
            product.get("product_id") or product.get("barcode") or product.get("name"),
        )

        if key in seen:
            continue

        seen.add(key)
        deduped.append(product)

    return deduped
