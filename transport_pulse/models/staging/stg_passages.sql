with source as (
    select * from {{ source('raw', 'raw_passages') }}
),

renamed as (
    select
        response_ts::timestamptz                  as response_ts,
        line_id,
        split_part(line_id, ':', 4)               as line_code,   -- C01100
        line_name,
        direction,
        destination,
        mode,
        operator,
        journey_id,
        split_part(stop_id, ':', 4)               as stop_code,   -- 26352
        expected_departure::timestamptz           as expected_departure_utc,
        departure_status
    from source
)

select * from renamed
