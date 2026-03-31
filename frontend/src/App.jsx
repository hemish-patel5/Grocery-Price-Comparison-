import { useState } from "react";

const App = () => {
  const [query, setQuery] = useState("");

  const handleSearch = () => {
    console.log("searching for...", query);
  };

  return (
    <div>
      <h1>Grocer Price Comparison</h1>
      <input
        placeholder="Search for a product..."
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      ></input>
      <button onClick={handleSearch}>Search</button>
    </div>
  );
};
export default App;
