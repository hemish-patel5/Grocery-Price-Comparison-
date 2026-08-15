import { useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000";

const DEFAULT_CATEGORIES = [
  { value: "fruit_vegetables", label: "Fruit & Vegetables" },
  { value: "meat_seafood", label: "Meat, Poultry & Seafood" },
  { value: "dairy_deli", label: "Dairy, Deli & Eggs" },
  { value: "pantry", label: "Pantry" },
  { value: "bakery", label: "Bakery" },
  { value: "drinks", label: "Drinks" },
  { value: "frozen", label: "Frozen" },
  { value: "snacks_ready_meals", label: "Snacks & Easy Meals" },
  { value: "household", label: "Household & Cleaning" },
  { value: "health_body", label: "Health & Body" },
  { value: "baby", label: "Baby & Toddler" },
  { value: "pets", label: "Pets" },
  { value: "beer_wine", label: "Beer, Wine & Cider" },
  { value: "featured", label: "Featured & Deals" },
];

const DEFAULT_SORTS = [
  { value: "relevance", label: "Relevance" },
  { value: "price_asc", label: "Lowest price" },
  { value: "price_desc", label: "Highest price" },
];

const storeColor = (store) => {
  if (store === "PAK'nSAVE") return "text-black bg-yellow-300";
  if (store === "New World") return "text-white bg-red-500 ";
  return "text-white bg-green-600";
};

const formatPrice = (value) => {
  if (value === null || value === undefined || value === "") return "N/A";
  const number = Number(value);
  return Number.isNaN(number) ? value : `$${number.toFixed(2)}`;
};

const priceUnit = (item) => {
  const size = String(item.size || "").trim();
  if (!size) return "";

  const isPerKilogram =
    size.toLowerCase() === "kg" ||
    String(item.product_id || "").toUpperCase().includes("-KGM-");
  if (isPerKilogram) return "per kg";
  if (size.toLowerCase() === "ea") return "each";
  return size.replace(/ml$/i, "mL").replace(/l$/i, "L");
};

const PriceBlock = ({ item, compact }) => (
  <div className="flex min-w-16 sm:min-w-28 flex-col items-end gap-0.5 sm:gap-1 text-right shrink-0">
    <span className="text-[10px] sm:text-xs font-bold uppercase text-gray-400">
      Price
    </span>
    <div
      className={`flex items-baseline justify-end gap-1 font-black tracking-tight ${
        item.sale_price != null
          ? "text-blue-600"
          : item.is_on_special
            ? "text-yellow-600"
            : "text-gray-900"
      }`}
    >
      <strong className={compact ? "text-base sm:text-xl" : "text-lg sm:text-2xl"}>
        {formatPrice(item.price)}
      </strong>
      {priceUnit(item) && (
        <span className="text-[10px] sm:text-xs font-bold whitespace-nowrap">
          {priceUnit(item)}
        </span>
      )}
    </div>
    {item.sale_price != null &&
      Number(item.original_price) > Number(item.sale_price) && (
        <span className="text-[11px] sm:text-sm font-semibold text-gray-400 line-through">
          was {formatPrice(item.original_price)}
        </span>
      )}
    {item.is_club_price && (
      <span className="text-[10px] sm:text-xs font-black uppercase text-red-600">
        Clubcard price
      </span>
    )}
    {item.is_on_special && (
      <span className="text-[10px] sm:text-xs font-black uppercase text-yellow-700">
        Special
      </span>
    )}
  </div>
);

const ProductInfo = ({ item }) => (
  <div className="min-w-0 flex-1">
    <div className="mb-1.5 sm:mb-2 flex flex-wrap items-center gap-1.5 sm:gap-2">
      <span
        className={`inline-flex text-[10px] font-black px-2.5 sm:px-3 py-1 rounded-full tracking-widest shadow-sm ${storeColor(item.store)}`}
      >
        {item.store}
      </span>
      <span className="text-[11px] sm:text-xs font-semibold text-gray-500 truncate">
        {item.store_address || "Store address unavailable"}
      </span>
    </div>
    {item.brand && (
      <p className="text-xs sm:text-sm font-bold uppercase text-blue-600 truncate">
        {item.brand}
      </p>
    )}
    <h2 className="text-sm sm:text-lg font-semibold text-gray-800 group-hover:text-blue-900 transition-colors leading-tight capitalize">
      {item.name}
    </h2>
  </div>
);

const App = () => {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [sortOrder, setSortOrder] = useState("relevance");
  const [location, setLocation] = useState("");
  const [products, setProducts] = useState([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [expanded, setExpanded] = useState({});
  const [storePrices, setStorePrices] = useState({});
  const [searchOptions, setSearchOptions] = useState({
    categories: DEFAULT_CATEGORIES,
    sorts: DEFAULT_SORTS,
    locations: [],
  });

  useEffect(() => {
    let cancelled = false;

    const loadSearchOptions = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/search/options`);
        if (!response.ok) throw new Error("Could not load search filters");
        const data = await response.json();
        if (!cancelled) {
          setSearchOptions({
            categories: data.categories?.length ? data.categories : DEFAULT_CATEGORIES,
            sorts: data.sorts?.length ? data.sorts : DEFAULT_SORTS,
            locations: Array.isArray(data.locations) ? data.locations : [],
          });
        }
      } catch (error) {
        console.error("Search filters failed", error);
      }
    };

    loadSearchOptions();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSearch = async (event) => {
    event?.preventDefault();
    try {
      setHasSearched(true);
      setIsLoading(true);
      setSearchError("");
      setExpanded({});
      setStorePrices({});
      setProducts([]);

      const parameters = new URLSearchParams({ q: query, sort: sortOrder });
      if (category) parameters.set("category", category);
      if (location) parameters.set("location", location);

      const res = await fetch(`${API_BASE_URL}/api/search?${parameters}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Search failed");
      setProducts(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error("Search failed", error);
      setSearchError(error.message || "Search failed. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const locationsByRetailer = searchOptions.locations.reduce((groups, option) => {
    const retailer = option.retailer || "Stores";
    return { ...groups, [retailer]: [...(groups[retailer] || []), option] };
  }, {});

  const toggleStores = async (productId) => {
    setExpanded((prev) => ({ ...prev, [productId]: !prev[productId] }));
    if (storePrices[productId]) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/api/product/${encodeURIComponent(productId)}/prices`
      );
      const data = await res.json();
      setStorePrices((prev) => ({
        ...prev,
        [productId]: Array.isArray(data) ? data : [],
      }));
    } catch (error) {
      console.error("Store prices failed", error);
    }
  };

  return (
    <div className="font-er min-h-screen bg-blue-50 flex flex-col items-center px-4 py-6 sm:p-8 text-gray-900">
      <h1 className="text-4xl sm:text-5xl font-black mb-6 sm:mb-10 text-blue-600 tracking-tighter">
        Grocerybook
      </h1>

      <form onSubmit={handleSearch} className="w-full max-w-3xl">
        {/* --- ROUNDED SEARCH BAR CONTAINER --- */}
        <div className="relative w-full max-w-xl mx-auto group">
          <input
            type="search"
            placeholder="Search for a product..."
            aria-label="Product name"
            className="w-full py-4 pl-6 pr-16 text-base sm:py-6 sm:pl-8 sm:pr-20 sm:text-xl rounded-full border-2 border-white bg-white focus:outline-none focus:border-blue-400 focus:ring-blue-100 transition-all placeholder:text-gray-400"
            value={query}
            maxLength={100}
            onChange={(e) => setQuery(e.target.value)}
          />

          {/* --- MAGNIFYING GLASS BUTTON --- */}
          <button
            type="submit"
            aria-label="Search"
            disabled={isLoading}
            className="absolute right-2 sm:right-3 top-1/2 -translate-y-1/2 p-3 sm:p-4 bg-blue-600 text-white rounded-full hover:bg-blue-700 disabled:bg-blue-300 transition-colors shadow-lg active:scale-95"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className="h-5 w-5 sm:h-6 sm:w-6"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={3}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
          </button>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="grid gap-1 text-xs font-bold uppercase tracking-wide text-gray-500">
            Category
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value)}
              className="w-full rounded-xl border border-white bg-white px-3 py-3 text-sm font-semibold normal-case tracking-normal text-gray-800 shadow-sm outline-none focus:border-blue-400"
            >
              <option value="">All categories</option>
              {searchOptions.categories.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="grid gap-1 text-xs font-bold uppercase tracking-wide text-gray-500">
            Sort by
            <select
              value={sortOrder}
              onChange={(event) => setSortOrder(event.target.value)}
              className="w-full rounded-xl border border-white bg-white px-3 py-3 text-sm font-semibold normal-case tracking-normal text-gray-800 shadow-sm outline-none focus:border-blue-400"
            >
              {searchOptions.sorts.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>

          <label className="grid gap-1 text-xs font-bold uppercase tracking-wide text-gray-500">
            Location
            <select
              value={location}
              onChange={(event) => setLocation(event.target.value)}
              className="w-full rounded-xl border border-white bg-white px-3 py-3 text-sm font-semibold normal-case tracking-normal text-gray-800 shadow-sm outline-none focus:border-blue-400"
            >
              <option value="">All Auckland stores</option>
              {Object.entries(locationsByRetailer).map(([retailer, options]) => (
                <optgroup key={retailer} label={retailer}>
                  {options.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
        </div>
      </form>

      {/* --- RESULTS SECTION --- */}
      <div className="w-full max-w-3xl mt-8 sm:mt-12">
        {isLoading && (
          <p className="text-center text-gray-500 font-semibold animate-pulse">
            Loading...
          </p>
        )}
        {searchError && !isLoading && (
          <p className="text-center text-red-600 font-semibold">{searchError}</p>
        )}
        {hasSearched && !isLoading && !searchError && products.length === 0 && (
          <p className="text-center text-gray-500 font-semibold">No products found.</p>
        )}
        {hasSearched && !isLoading && products.length > 0 && (
          <p className="mb-3 text-sm font-semibold text-gray-500">
            Showing {products.length} products
          </p>
        )}

        <ul className="grid gap-3 sm:gap-4 w-full">
          {products.map((p, i) => (
            <li
              key={p.product_id || i}
              className="group bg-white p-3 sm:p-5 rounded-2xl shadow-sm border border-gray-100 hover:shadow-md hover:border-blue-200 transition-all"
            >
              <div className="flex gap-3 sm:gap-5 items-center">
                <div className="h-16 w-16 sm:h-24 sm:w-24 shrink-0 overflow-hidden rounded-xl bg-gray-100 border border-gray-100">
                  {p.image_url ? (
                    <img
                      src={p.image_url}
                      alt={p.name}
                      className="h-full w-full object-contain p-1.5 sm:p-2"
                      loading="lazy"
                    />
                  ) : (
                    <div className="h-full w-full flex items-center justify-center text-[10px] sm:text-xs font-bold uppercase text-gray-400">
                      No image
                    </div>
                  )}
                </div>

                <ProductInfo item={p} />

                <PriceBlock item={p} />
              </div>

              {/* --- PER-STORE COMPARISON DROPDOWN --- */}
              <button
                onClick={() => toggleStores(p.product_id)}
                className="mt-2 sm:mt-3 w-full flex items-center justify-center gap-1 text-[11px] sm:text-xs font-bold uppercase tracking-wider text-blue-600 hover:text-blue-800 transition-colors"
              >
                {expanded[p.product_id] ? "Hide stores" : "Compare stores"}
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  className={`h-3.5 w-3.5 transition-transform ${expanded[p.product_id] ? "rotate-180" : ""}`}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {expanded[p.product_id] && (
                <ul className="mt-2 sm:mt-3 grid gap-2 border-t border-gray-100 pt-2 sm:pt-3">
                  {!storePrices[p.product_id] && (
                    <li className="text-center text-xs sm:text-sm font-semibold text-gray-400 py-2">
                      Loading stores...
                    </li>
                  )}
                  {(storePrices[p.product_id] || [])
                    .filter((sp) => sp.store_key !== p.store_key)
                    .map((sp, j) => (
                      <li
                        key={sp.store_key || j}
                        className="flex gap-3 sm:gap-5 items-center bg-gray-50 rounded-xl border border-gray-100 p-2.5 sm:p-3"
                      >
                        <ProductInfo item={{ ...p, ...sp }} />
                        <PriceBlock item={{ ...p, ...sp }} compact />
                      </li>
                    ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default App;
