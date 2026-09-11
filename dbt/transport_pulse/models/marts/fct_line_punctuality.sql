with passages as (
    select * from {{ ref('stg_passages') }}
),

kpi as (
    select
        response_ts,
        line_code,
        line_name,
        mode,
        count(*)                                                          as total_calls,
        count(*) filter (where departure_status = 'ON_TIME')              as on_time,
        count(*) filter (where departure_status = 'DELAYED')              as delayed,
        count(*) filter (where departure_status = 'EARLY')                as early,
        count(*) filter (where departure_status = 'CANCELLED')            as cancelled,
        count(*) filter (where departure_status = 'NO_REPORT'
                           or departure_status is null)                   as no_report,

        -- Ponctualité : uniquement les passages réellement supervisés
        -- (CANCELLED et NO_REPORT exclus du dénominateur)
        round(100.0 * count(*) filter (where departure_status = 'ON_TIME')
              / nullif(count(*) filter (where departure_status in ('ON_TIME','DELAYED','EARLY')), 0), 2)
                                                                          as punctuality_pct,

        -- KPI séparés : perturbations et qualité de supervision
        round(100.0 * count(*) filter (where departure_status = 'CANCELLED')
              / nullif(count(*), 0), 2)                                   as cancellation_pct,
        round(100.0 * count(*) filter (where departure_status = 'NO_REPORT'
                           or departure_status is null)
              / nullif(count(*), 0), 2)                                   as no_report_pct

    from passages
    group by response_ts, line_code, line_name, mode
)

select *
from kpi
where total_calls >= 30          -- seuil de fiabilité statistique