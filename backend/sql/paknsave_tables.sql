-- PAK'nSAVE tables used by the PAK'nSAVE scraper and backend API.
-- Product catalogue data is stored once, while prices remain store-specific.

create table public.paknsave_stores (
    id bigint generated always as identity primary key,
    store_key text not null unique,
    retailer_store_id uuid not null unique,
    address text not null,
    chain text not null default 'PAK''nSAVE',
    scraped_at timestamptz
);

create table public.paknsave_products (
    product_id text primary key,
    name text not null,
    brand text,
    size text,
    department text,
    aisle text,
    image_url text
);

create table public.paknsave_store_prices (
    product_id text not null
        references public.paknsave_products(product_id) on delete cascade,
    store_id bigint not null
        references public.paknsave_stores(id) on delete cascade,
    price numeric(10, 2),
    is_on_special boolean not null default false,
    primary key (product_id, store_id)
);

create index paknsave_products_name_idx
    on public.paknsave_products (name);

create index paknsave_products_department_idx
    on public.paknsave_products (department);

create index paknsave_products_aisle_idx
    on public.paknsave_products (aisle);

create index paknsave_store_prices_store_price_idx
    on public.paknsave_store_prices (store_id, price);

create index paknsave_store_prices_product_price_idx
    on public.paknsave_store_prices (product_id, price);

-- Returns the cheapest PAK'nSAVE store for each matching catalogue product.
-- The common columns match the Woolworths and New World search RPCs.
-- PAK'nSAVE has specials rather than Clubcard pricing, so is_club_price is
-- always false and is_on_special is returned as an additional retailer flag.
drop function if exists public.search_paknsave_products(text[], integer);

create function public.search_paknsave_products(
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
    is_on_special boolean,
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
            null::numeric as original_price,
            null::numeric as sale_price,
            null::text as unit_price,
            false as is_club_price,
            cheapest.is_on_special,
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
        from public.paknsave_products p
        join lateral (
            select
                sp.price,
                sp.is_on_special,
                s.store_key,
                s.address as store_address
            from public.paknsave_store_prices sp
            join public.paknsave_stores s on s.id = sp.store_id
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
        d.is_on_special,
        d.store_key,
        d.store_address
    from deduplicated d
    where d.duplicate_number = 1
    order by d.relevance, d.price, d.name
    limit greatest(0, least(coalesce(p_limit, 100), 500));
$$;

grant execute on function public.search_paknsave_products(text[], integer)
    to anon, authenticated, service_role;
