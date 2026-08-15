# Grocerybook

A full-stack web application designed to help New Zealand shoppers compare real-time prices across major local retailers, including **PAK'nSAVE**, **New World**, and **Woolworths**.



## 🛠️ Tech Stack

### Frontend
* **React.js** (Vite)
* **Tailwind CSS** (Styling & Responsive Design)

### Backend
* **Python / Flask** (REST API)
* **HTTPX** (Asynchronous web requests for high-performance scraping)
* **Flask-CORS** (Cross-Origin Resource Sharing)
  
### Database
* **Supabase** (PostgreSQL)

---

## Database setup

Run the SQL files in the Supabase SQL editor in this order:

1. `backend/sql/woolworths_tables.sql`
2. `backend/sql/newworld_tables.sql`
3. `backend/sql/paknsave_tables.sql`
4. `backend/sql/search_engine.sql`

The final migration enables PostgreSQL full-text and trigram search, creates
the search indexes, normalizes retailer departments into shared categories,
and installs the `search_grocery_products` RPC used by `backend/api.py`.

## Scraping and uploading

After adding `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` to `backend/.env`, run:

```bash
python -m backend.scrapers.db
```

This runs Woolworths Central/West Auckland, every Auckland New World, and every
Auckland PAK'nSAVE scraper sequentially. Products are uploaded directly to
their retailer-specific Supabase tables without generating product JSON files.
