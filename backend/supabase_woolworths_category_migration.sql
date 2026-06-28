alter table woolworths_prices
  add column if not exists mode text not null default 'categories',
  alter column query drop not null,
  add column if not exists category_key text,
  add column if not exists category_label text,
  add column if not exists category_level text,
  add column if not exists department_id integer,
  add column if not exists department_name text,
  add column if not exists aisle_id integer,
  add column if not exists aisle_name text,
  add column if not exists shelf_id integer,
  add column if not exists shelf_name text;

create index if not exists woolworths_prices_category_idx
  on woolworths_prices (category_key);
