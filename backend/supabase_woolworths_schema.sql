create table if not exists woolworths_prices (
  id bigserial primary key,
  scrape_run_id text not null,
  mode text not null default 'categories',
  query text,
  scraped_at timestamptz not null,
  store_key text not null,
  store_address text,
  area_id integer,
  fulfilment_store_id integer,
  pickup_address_id integer,
  category_key text,
  category_label text,
  category_level text,
  department_id integer,
  department_name text,
  aisle_id integer,
  aisle_name text,
  shelf_id integer,
  shelf_name text,
  product_id text,
  barcode text,
  name text not null,
  brand text,
  price numeric(10, 2),
  original_price numeric(10, 2),
  sale_price numeric(10, 2),
  save_price numeric(10, 2),
  size text,
  unit_price text,
  image_url text,
  product_url text,
  is_on_special boolean,
  availability text,
  stock_level integer,
  department text,
  raw jsonb not null,
  created_at timestamptz not null default now()
);

create index if not exists woolworths_prices_query_idx
  on woolworths_prices (query);

create index if not exists woolworths_prices_category_idx
  on woolworths_prices (category_key);

create index if not exists woolworths_prices_store_idx
  on woolworths_prices (store_key);

create index if not exists woolworths_prices_product_idx
  on woolworths_prices (product_id);

create index if not exists woolworths_prices_scrape_run_idx
  on woolworths_prices (scrape_run_id);
