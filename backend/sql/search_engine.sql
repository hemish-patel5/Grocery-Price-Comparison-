-- Unified grocery search for Woolworths, New World and PAK'nSAVE.
--
-- Run this file after the three retailer table scripts. It keeps every
-- retailer's tables separate, but searches them through one ranked RPC.

create extension if not exists pg_trgm with schema extensions;

-- The existing btree indexes are useful for normal sorting, but cannot speed
-- up leading-wildcard searches. These indexes support full-text matching and
-- typo-tolerant trigram matching instead.
create index if not exists woolies_products_search_fts_idx
    on public.woolies_products using gin (
        to_tsvector(
            'english'::regconfig,
            coalesce(name, '') || ' ' ||
            coalesce(brand, '') || ' ' ||
            coalesce(size, '') || ' ' ||
            coalesce(aisle, '')
        )
    );

create index if not exists woolies_products_name_brand_trgm_idx
    on public.woolies_products using gin (
        (lower(coalesce(name, '') || ' ' || coalesce(brand, '')))
        extensions.gin_trgm_ops
    );

create index if not exists newworld_products_search_fts_idx
    on public.newworld_products using gin (
        to_tsvector(
            'english'::regconfig,
            coalesce(name, '') || ' ' ||
            coalesce(brand, '') || ' ' ||
            coalesce(size, '') || ' ' ||
            coalesce(aisle, '')
        )
    );

create index if not exists newworld_products_name_brand_trgm_idx
    on public.newworld_products using gin (
        (lower(coalesce(name, '') || ' ' || coalesce(brand, '')))
        extensions.gin_trgm_ops
    );

create index if not exists paknsave_products_search_fts_idx
    on public.paknsave_products using gin (
        to_tsvector(
            'english'::regconfig,
            coalesce(name, '') || ' ' ||
            coalesce(brand, '') || ' ' ||
            coalesce(size, '') || ' ' ||
            coalesce(aisle, '')
        )
    );

create index if not exists paknsave_products_name_brand_trgm_idx
    on public.paknsave_products using gin (
        (lower(coalesce(name, '') || ' ' || coalesce(brand, '')))
        extensions.gin_trgm_ops
    );

-- Convert each retailer's department names into the common categories shown
-- by the frontend filters.
create or replace function public.grocery_category_key(
    p_retailer text,
    p_department text
)
returns text
language sql
immutable
parallel safe
as $$
    select case
        when p_department in ('Baby & Child', 'Baby & Toddler')
            then 'baby'
        when p_department = 'Bakery'
            then 'bakery'
        when p_department in ('Beer & Wine', 'Beer, Wine & Cider')
            then 'beer_wine'
        when p_department in ('Drinks', 'Hot & Cold Drinks')
            then 'drinks'
        when p_department in ('Fridge & Deli', 'Fridge, Deli & Eggs')
            then 'dairy_deli'
        when p_department = 'Frozen'
            then 'frozen'
        when p_department in ('Fruit & Veg', 'Fruit & Vegetables')
            then 'fruit_vegetables'
        when p_department = 'Health & Body'
            then 'health_body'
        when p_department in ('Household', 'Household & Cleaning')
            then 'household'
        when p_department in (
            'Fish & Seafood',
            'Meat & Poultry',
            'Meat, Poultry & Seafood'
        )
            then 'meat_seafood'
        when p_department = 'Pantry'
            then 'pantry'
        when p_department in ('Pet', 'Pets')
            then 'pets'
        when p_department = 'Snacks, Treats & Easy Meals'
            then 'snacks_ready_meals'
        when p_retailer = 'PAK''nSAVE'
             and p_department in ('Featured', '99c Week')
            then 'featured'
        else null
    end;
$$;

grant execute on function public.grocery_category_key(text, text)
    to anon, authenticated, service_role;

drop function if exists public.search_grocery_products(
    text, text, text, text, text, integer, integer
);

create function public.search_grocery_products(
    p_query text default '',
    p_category text default null,
    p_retailer text default null,
    p_store_key text default null,
    p_sort text default 'relevance',
    p_limit integer default 100,
    p_offset integer default 0
)
returns table (
    retailer text,
    product_id text,
    name text,
    brand text,
    size text,
    department text,
    aisle text,
    category_key text,
    image_url text,
    price numeric,
    original_price numeric,
    sale_price numeric,
    unit_price text,
    is_club_price boolean,
    is_on_special boolean,
    store_key text,
    store_address text,
    relevance_score double precision,
    total_count bigint
)
language sql
stable
security definer
set search_path = public, extensions
as $$
    with params as (
        select
            lower(trim(regexp_replace(
                left(coalesce(p_query, ''), 100),
                '[^[:alnum:]&'']+',
                ' ',
                'g'
            ))) as query_text,
            coalesce(nullif(p_sort, ''), 'relevance') as sort_order
    ),
    query_terms as (
        select distinct
            term,
            plainto_tsquery('english'::regconfig, term) as term_query
        from params
        cross join lateral regexp_split_to_table(params.query_text, '\s+') term
        where term <> ''
        limit 8
    ),
    catalog as (
        select
            'Woolworths'::text as retailer,
            p.product_id,
            p.name,
            p.brand,
            p.size,
            p.department,
            p.aisle,
            public.grocery_category_key('Woolworths', p.department)
                as category_key,
            p.image_url
        from public.woolies_products p
        where p_retailer is null or p_retailer = 'Woolworths'

        union all

        select
            'New World'::text,
            p.product_id,
            p.name,
            p.brand,
            p.size,
            p.department,
            p.aisle,
            public.grocery_category_key('New World', p.department),
            p.image_url
        from public.newworld_products p
        where p_retailer is null or p_retailer = 'New World'

        union all

        select
            'PAK''nSAVE'::text,
            p.product_id,
            p.name,
            p.brand,
            p.size,
            p.department,
            p.aisle,
            public.grocery_category_key('PAK''nSAVE', p.department),
            p.image_url
        from public.paknsave_products p
        where p_retailer is null or p_retailer = 'PAK''nSAVE'
    ),
    prepared as (
        select
            catalog.*,
            lower(coalesce(name, '')) as name_text,
            lower(coalesce(name, '') || ' ' || coalesce(brand, ''))
                as name_brand_text,
            to_tsvector(
                'english'::regconfig,
                coalesce(name, '') || ' ' ||
                coalesce(brand, '') || ' ' ||
                coalesce(size, '') || ' ' ||
                coalesce(aisle, '')
            ) as search_vector,
            setweight(
                to_tsvector('english'::regconfig, coalesce(name, '')),
                'A'
            ) ||
            setweight(
                to_tsvector('english'::regconfig, coalesce(brand, '')),
                'B'
            ) ||
            setweight(
                to_tsvector('english'::regconfig, coalesce(aisle, '')),
                'C'
            ) ||
            setweight(
                to_tsvector('english'::regconfig, coalesce(size, '')),
                'D'
            ) as weighted_vector
        from catalog
        where p_category is null or category_key = p_category
    ),
    scored as (
        select
            prepared.*,
            case
                when params.query_text = '' then 0::double precision
                else (
                    case
                        when name_text = params.query_text then 500
                        when name_text like params.query_text || '%' then 350
                        when name_text like '%' || params.query_text || '%'
                            then 250
                        else 0
                    end
                    + 180 * ts_rank_cd(
                        weighted_vector,
                        plainto_tsquery(
                            'english'::regconfig,
                            params.query_text
                        ),
                        32
                    )
                    + 120 * coalesce(term_scores.average_term_score, 0)
                    + 60 * word_similarity(
                        params.query_text,
                        name_brand_text
                    )
                )::double precision
            end as relevance_score
        from prepared
        cross join params
        cross join lateral (
            select avg(
                case
                    when to_tsvector(
                        'english'::regconfig,
                        coalesce(prepared.name, '')
                    ) @@ query_terms.term_query
                        then 1.0
                    when to_tsvector(
                        'english'::regconfig,
                        coalesce(prepared.brand, '')
                    ) @@ query_terms.term_query
                        then 0.8
                    when to_tsvector(
                        'english'::regconfig,
                        coalesce(prepared.aisle, '')
                    ) @@ query_terms.term_query
                        then 0.45
                    when char_length(query_terms.term) >= 4
                        then 0.7 * word_similarity(
                            query_terms.term,
                            prepared.name_brand_text
                        )
                    else 0
                end
            ) as average_term_score
            from query_terms
        ) term_scores
        where params.query_text = ''
           or prepared.search_vector @@ plainto_tsquery(
                'english'::regconfig,
                params.query_text
           )
           or not exists (
                select 1
                from query_terms
                where not (
                    prepared.search_vector @@ query_terms.term_query
                    or (
                        char_length(query_terms.term) >= 4
                        and word_similarity(
                            query_terms.term,
                            prepared.name_brand_text
                        ) >= 0.55
                    )
                )
           )
    ),
    available as (
        select
            scored.retailer,
            scored.product_id,
            scored.name,
            scored.brand,
            scored.size,
            scored.department,
            scored.aisle,
            scored.category_key,
            scored.image_url,
            sp.price,
            sp.original_price,
            sp.sale_price,
            sp.unit_price,
            false as is_club_price,
            false as is_on_special,
            s.store_key,
            s.address as store_address,
            scored.relevance_score
        from scored
        join public.woolies_store_prices sp
            on sp.product_id = scored.product_id
        join public.woolies_stores s on s.id = sp.store_id
        where scored.retailer = 'Woolworths'
          and sp.price is not null
          and (p_store_key is null or s.store_key = p_store_key)

        union all

        select
            scored.retailer,
            scored.product_id,
            scored.name,
            scored.brand,
            scored.size,
            scored.department,
            scored.aisle,
            scored.category_key,
            scored.image_url,
            sp.price,
            null::numeric,
            null::numeric,
            null::text,
            sp.is_club_price,
            false,
            s.store_key,
            s.address,
            scored.relevance_score
        from scored
        join public.newworld_store_prices sp
            on sp.product_id = scored.product_id
        join public.newworld_stores s on s.id = sp.store_id
        where scored.retailer = 'New World'
          and sp.price is not null
          and (p_store_key is null or s.store_key = p_store_key)

        union all

        select
            scored.retailer,
            scored.product_id,
            scored.name,
            scored.brand,
            scored.size,
            scored.department,
            scored.aisle,
            scored.category_key,
            scored.image_url,
            sp.price,
            null::numeric,
            null::numeric,
            null::text,
            false,
            sp.is_on_special,
            s.store_key,
            s.address,
            scored.relevance_score
        from scored
        join public.paknsave_store_prices sp
            on sp.product_id = scored.product_id
        join public.paknsave_stores s on s.id = sp.store_id
        where scored.retailer = 'PAK''nSAVE'
          and sp.price is not null
          and (p_store_key is null or s.store_key = p_store_key)
    ),
    cheapest as (
        select
            available.*,
            row_number() over (
                partition by retailer, product_id
                order by price, store_key
            ) as store_price_rank
        from available
    ),
    deduplicated as (
        select
            cheapest.*,
            row_number() over (
                partition by
                    retailer,
                    lower(coalesce(name, '')),
                    lower(coalesce(brand, '')),
                    lower(coalesce(size, ''))
                order by relevance_score desc, price, product_id
            ) as duplicate_rank
        from cheapest
        where store_price_rank = 1
    ),
    final_rows as (
        select
            deduplicated.*,
            count(*) over () as matched_count
        from deduplicated
        where duplicate_rank = 1
    )
    select
        final_rows.retailer,
        final_rows.product_id,
        final_rows.name,
        final_rows.brand,
        final_rows.size,
        final_rows.department,
        final_rows.aisle,
        final_rows.category_key,
        final_rows.image_url,
        final_rows.price,
        final_rows.original_price,
        final_rows.sale_price,
        final_rows.unit_price,
        final_rows.is_club_price,
        final_rows.is_on_special,
        final_rows.store_key,
        final_rows.store_address,
        final_rows.relevance_score,
        final_rows.matched_count
    from final_rows
    cross join params
    order by
        case when params.sort_order = 'price_asc'
            then final_rows.price end asc nulls last,
        case when params.sort_order = 'price_desc'
            then final_rows.price end desc nulls last,
        case when params.sort_order = 'relevance'
            then final_rows.relevance_score end desc,
        final_rows.relevance_score desc,
        final_rows.price asc nulls last,
        final_rows.name,
        final_rows.product_id
    limit greatest(0, least(coalesce(p_limit, 100), 500))
    offset greatest(0, least(coalesce(p_offset, 0), 5000));
$$;

grant execute on function public.search_grocery_products(
    text, text, text, text, text, integer, integer
) to anon, authenticated, service_role;

analyze public.woolies_products;
analyze public.newworld_products;
analyze public.paknsave_products;
