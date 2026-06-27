/* pip install flask flask-cors httpx */
import { useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000";

const App = () => {
  const [query, setQuery] = useState("");
  const [products, setProducts] = useState([]);

  const handleSearch = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/search?q=${encodeURIComponent(query)}`);
      const data = await res.json();
      setProducts(Array.isArray(data) ? data : []);
    } catch (error) {
      console.error("Search failed", error);
    }
  };

  const storeColor = (store) => {
    if (store === "PAK'nSAVE") return "text-black bg-yellow-300";
    if (store === "New World") return "text-white bg-red-500 ";
    return "text-white bg-green-600";
  };

  return (
    <div className="font-er min-h-screen bg-blue-50 flex flex-col items-center p-8 text-gray-900">
      <h1 className="text-5xl font-black mb-10 text-blue-600 tracking-tighter">
        Grocery Price Comparison
      </h1>

      {/* --- ROUNDED SEARCH BAR CONTAINER --- */}
      <div className="relative w-full max-w-xl group">
        <input
          type="text"
          placeholder="Search for a product..."
          className="w-full py-6 pl-8 pr-20 text-xl rounded-full border-2 border-white bg-white focus:outline-none focus:border-blue-400  focus:ring-blue-100 transition-all placeholder:text-gray-400"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
        />

        {/* --- MAGNIFYING GLASS BUTTON --- */}
        <button
          onClick={handleSearch}
          className="absolute right-3 top-1/2 -translate-y-1/2 p-4 bg-blue-600 text-white rounded-full hover:bg-blue-700 transition-colors shadow-lg active:scale-95"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-6 w-6"
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

      {/* --- RESULTS SECTION --- */}
      <div className="w-full max-w-2xl mt-12">
        {products.length > 0 && (
          <div className="group bg-blue-100 border border-blue-200 p-8 mb-7 rounded-2xl shadow-md flex flex-col items-start hover:shadow-xl hover:border-blue-300 transition-all cursor-default">
            {/* 1. Small writing at the top */}
            <span className="text-xs uppercase tracking-widest text-blue-600 font-bold mb-3">
              Cheapest Found
            </span>

            {/* 2. Item and Price (Large and Standout) */}
            <div className="flex justify-between items-center w-full">
              <h2 className="uppercase text-2xl font-black text-gray-900 leading-tight">
                {products[0].name}
              </h2>

              {/* The matching Price Tag style with hover effect */}
              <div className="bg-blue-600 text-white px-5 py-3 rounded-xl shadow-lg transform group-hover:scale-110 transition-transform">
                <span className="text-2xl opacity-80 mr-1 font-medium">$</span>
                <span className="text-3xl font-black tracking-tighter">
                  {products[0].price}
                </span>
              </div>
            </div>

            {/* 3. Store name at the bottom */}
            <div className="mt-6 pt-4 border-t border-blue-200 w-full flex items-center justify-between">
              <span
                className={`text-sm font-bold px-4 py-1.5 rounded-full tracking-tight ${storeColor(products[0].store)}`}
              >
                {products[0].store}
              </span>
            </div>
          </div>
        )}

        <ul className="grid gap-4 w-full max-w-2xl mt-8">
          {products.slice(1).map((p, i) => (
            <li
              key={i}
              className="group bg-white p-5 rounded-2xl shadow-sm border border-gray-100 flex justify-between items-center hover:shadow-md hover:border-blue-200 transition-all"
            >
              {/* Product Name & Store Label */}
              <div className="flex flex-col items-start">
                <span
                  className={`text-[10px] font-black px-3 py-1 rounded-full  tracking-widest mb-2 shadow-sm ${storeColor(p.store)}`}
                >
                  {p.store}
                </span>
                <span className="text-lg font-semibold uppercase text-gray-800 group-hover:text-blue-900 transition-colors leading-tight">
                  {p.name}
                </span>
              </div>

              {/* High-Contrast Price Tag */}
              <div className="flex flex-col items-end">
                <div className="bg-blue-600 text-white px-4 py-2 rounded-xl shadow-sm transform group-hover:scale-105 transition-transform">
                  <span className="text-xl opacity-80 mr-1 font-medium">$</span>
                  <span className="text-2xl font-black tracking-tight">
                    {p.price}
                  </span>
                </div>
                <span className="text-[10px] px-2 text-gray-400 mt-1 font-medium uppercase">
                  Final Price
                </span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default App;
