-- Woolworths tables used by backend/scrapers/db.py.
-- Run this on a fresh Supabase schema. Prices are stored separately because
-- one catalog product can have a different price at every store.

create table public.stores (
    id bigint generated always as identity primary key,
    store_key text not null unique,
    address text not null,
    chain text not null default 'Woolworths',
    fulfilment_store_id integer not null,
    area_id integer,
    pickup_address_id bigint,
    scraped_at timestamptz
);

create table public.products (
    product_id text primary key,
    name text not null,
    brand text,
    size text,
    department text,
    aisle text,
    image_url text
);

create table public.store_prices (
    product_id text not null
        references public.products(product_id) on delete cascade,
    store_id bigint not null
        references public.stores(id) on delete cascade,
    price numeric(10, 2),
    original_price numeric(10, 2),
    sale_price numeric(10, 2),
    unit_price text,
    primary key (product_id, store_id)
);

create index products_name_idx
    on public.products (name);

create index products_department_idx
    on public.products (department);

create index products_aisle_idx
    on public.products (aisle);

create index store_prices_store_price_idx
    on public.store_prices (store_id, price);

create index store_prices_product_price_idx
    on public.store_prices (product_id, price);

-- Returns the cheapest Woolworths store for each matching catalog product.
-- Its columns deliberately match search_newworld_products so api.py can
-- combine both result sets without retailer-specific display logic.
-- Drop the previous RPC definition so this script can replace an existing
-- function with the same arguments, including one with an older return type.
drop function if exists public.search_products(text[], integer);

create function public.search_products(
    p_stems text[],
    p_limit integer default 100
)
returns table (
    product_id text,
    name text,
    brand text,
    size text,
    department text,
    aisle text,
    image_url text,
    price numeric,
    original_price numeric,
    sale_price numeric,
    unit_price text,
    is_club_price boolean,
    store_key text,
    store_address text
)
language sql
stable
security definer
set search_path = public
as $$
    with matches as (
        select
            p.product_id,
            p.name,
            p.brand,
            p.size,
            p.department,
            p.aisle,
            p.image_url,
            cheapest.price,
            cheapest.original_price,
            cheapest.sale_price,
            cheapest.unit_price,
            false as is_club_price,
            cheapest.store_key,
            cheapest.store_address,
            case
                when exists (
                    select 1 from unnest(p_stems) stem
                    where lower(concat_ws(' ', p.name, p.brand))
                        like '%' || stem || '%'
                ) then 0
                when exists (
                    select 1 from unnest(p_stems) stem
                    where lower(coalesce(p.aisle, '')) like '%' || stem || '%'
                ) then 1
                else 2
            end as relevance
        from public.products p
        join lateral (
            select
                sp.price,
                sp.original_price,
                sp.sale_price,
                sp.unit_price,
                s.store_key,
                s.address as store_address
            from public.store_prices sp
            join public.stores s on s.id = sp.store_id
            where sp.product_id = p.product_id
              and sp.price is not null
            order by sp.price
            limit 1
        ) cheapest on true
        where not exists (
            select 1
            from unnest(p_stems) stem
            where lower(concat_ws(' ', p.name, p.brand, p.size, p.aisle))
                not like '%' || stem || '%'
        )
    ),
    deduplicated as (
        select
            matches.*,
            row_number() over (
                partition by
                    lower(coalesce(name, '')),
                    lower(coalesce(brand, '')),
                    lower(coalesce(size, ''))
                order by relevance, price, product_id
            ) as duplicate_number
        from matches
    )
    select
        d.product_id,
        d.name,
        d.brand,
        d.size,
        d.department,
        d.aisle,
        d.image_url,
        d.price,
        d.original_price,
        d.sale_price,
        d.unit_price,
        d.is_club_price,
        d.store_key,
        d.store_address
    from deduplicated d
    where d.duplicate_number = 1
    order by d.relevance, d.price, d.name
    limit greatest(0, least(coalesce(p_limit, 100), 500));
$$;

grant execute on function public.search_products(text[], integer)
    to anon, authenticated, service_role;
