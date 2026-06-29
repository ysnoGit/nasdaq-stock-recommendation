-- Public screening API for Stock Sherlock. Underlying serving tables remain private.
CREATE SCHEMA IF NOT EXISTS screening_private;
REVOKE ALL ON SCHEMA screening_private FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION screening_private.validate_screen_request(
    p_start_date date,
    p_end_date date,
    p_use_fundamental boolean,
    p_use_volume boolean,
    p_use_daily_price boolean,
    p_use_weekly_price boolean,
    p_annual_growth_pct double precision,
    p_annual_years integer,
    p_quarterly_growth_pct double precision,
    p_quarter_count integer,
    p_volume_ratio_threshold double precision,
    p_volume_surge_min_days integer,
    p_daily_ma_tolerance_pct double precision,
    p_weekly_ma_tolerance_pct double precision
) RETURNS void
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
BEGIN
    IF p_start_date IS NULL OR p_end_date IS NULL OR p_start_date > p_end_date THEN
        RAISE EXCEPTION 'A valid inclusive inspection window is required';
    END IF;
    IF p_end_date > CURRENT_DATE THEN
        RAISE EXCEPTION 'Inspection dates cannot be in the future';
    END IF;
    IF p_end_date - p_start_date > 89 THEN
        RAISE EXCEPTION 'Inspection window cannot exceed 90 calendar days';
    END IF;
    IF NOT (p_use_fundamental OR p_use_volume OR p_use_daily_price OR p_use_weekly_price) THEN
        RAISE EXCEPTION 'Select at least one condition group';
    END IF;
    IF p_use_fundamental AND (p_use_volume OR p_use_daily_price OR p_use_weekly_price) THEN
        RAISE EXCEPTION 'Fundamental screening must be selected alone';
    END IF;
    IF p_annual_growth_pct < 0 OR p_annual_years NOT BETWEEN 1 AND 10
       OR p_quarterly_growth_pct < 0 OR p_quarter_count NOT BETWEEN 1 AND 20
       OR p_volume_ratio_threshold <= 0 OR p_volume_surge_min_days NOT BETWEEN 1 AND 100
       OR p_daily_ma_tolerance_pct < 0 OR p_daily_ma_tolerance_pct > 100
       OR p_weekly_ma_tolerance_pct < 0 OR p_weekly_ma_tolerance_pct > 100 THEN
        RAISE EXCEPTION 'One or more screening parameters are outside the allowed range';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION screening_private.fundamental_passes(
    p_evaluation_date date,
    p_annual_growth_pct double precision,
    p_annual_years integer,
    p_quarterly_growth_pct double precision,
    p_quarter_count integer
) RETURNS TABLE (gvkey text)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $$
    WITH annual_ranked AS MATERIALIZED (
        SELECT
            a.*,
            row_number() OVER (
                PARTITION BY a.gvkey ORDER BY a.fyear DESC, a.datadate DESC NULLS LAST
            ) AS period_rank
        FROM public.annual_growth_history AS a
        WHERE a.datadate <= p_evaluation_date
    ),
    annual_pass AS MATERIALIZED (
        SELECT a.gvkey
        FROM annual_ranked AS a
        WHERE a.period_rank <= p_annual_years
        GROUP BY a.gvkey
        HAVING count(*) = p_annual_years
           AND max(a.fyear) - min(a.fyear) = p_annual_years - 1
           AND bool_and(a.annual_revenue_growth IS NOT NULL)
           AND bool_and(a.annual_operating_income_growth IS NOT NULL)
           AND bool_and(a.annual_revenue_growth >= p_annual_growth_pct / 100.0)
           AND bool_and(a.annual_operating_income_growth >= p_annual_growth_pct / 100.0)
    ),
    quarterly_ranked AS MATERIALIZED (
        SELECT
            q.*,
            row_number() OVER (
                PARTITION BY q.gvkey
                ORDER BY q.fyearq DESC, q.fqtr DESC, q.datadate DESC NULLS LAST
            ) AS period_rank,
            q.fyearq * 4 + q.fqtr AS period_number
        FROM public.quarterly_growth_history AS q
        WHERE q.datadate <= p_evaluation_date
    ),
    quarterly_pass AS MATERIALIZED (
        SELECT q.gvkey
        FROM quarterly_ranked AS q
        WHERE q.period_rank <= p_quarter_count
        GROUP BY q.gvkey
        HAVING count(*) = p_quarter_count
           AND max(q.period_number) - min(q.period_number) = p_quarter_count - 1
           AND bool_and(q.quarterly_revenue_growth IS NOT NULL)
           AND bool_and(q.quarterly_operating_income_growth IS NOT NULL)
           AND bool_and(q.quarterly_revenue_growth >= p_quarterly_growth_pct / 100.0)
           AND bool_and(q.quarterly_operating_income_growth >= p_quarterly_growth_pct / 100.0)
    )
    SELECT a.gvkey
    FROM annual_pass AS a
    JOIN quarterly_pass AS q USING (gvkey);
$$;

CREATE OR REPLACE FUNCTION screening_private.evaluation_status(
    p_anchor_date date,
    p_use_fundamental boolean,
    p_use_volume boolean,
    p_use_daily_price boolean,
    p_use_weekly_price boolean
) RETURNS text
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $$
    SELECT CASE
        WHEN p_use_fundamental THEN 'complete'
        WHEN p_use_weekly_price
             AND NOT p_use_volume
             AND NOT p_use_daily_price
             AND NOT EXISTS (
                 SELECT 1 FROM public.security_weekly_feature_snapshot w
                 WHERE w.week_end_date = p_anchor_date
             ) THEN 'no_market_session'
        WHEN NOT p_use_fundamental
             AND NOT EXISTS (
                 SELECT 1 FROM public.security_daily_feature_snapshot d
                 WHERE d.snapshot_date = p_anchor_date
             ) THEN 'no_market_session'
        WHEN p_use_daily_price
             AND NOT EXISTS (
                 SELECT 1 FROM public.security_daily_feature_snapshot d
                 WHERE d.snapshot_date > p_anchor_date
             ) THEN 'pending_f'
        WHEN p_use_weekly_price
             AND (
                 (NOT p_use_daily_price AND EXISTS (
                     SELECT 1 FROM public.security_weekly_feature_snapshot w
                     WHERE w.week_end_date = p_anchor_date
                 ))
                 OR
                 (p_use_daily_price AND EXISTS (
                     SELECT 1 FROM public.security_weekly_feature_snapshot w
                     WHERE w.week_end_date = p_anchor_date
                 ))
             )
             AND NOT EXISTS (
                 SELECT 1 FROM public.security_weekly_feature_snapshot w
                 WHERE w.week_end_date > p_anchor_date
             ) THEN 'pending_h'
        ELSE 'complete'
    END;
$$;

CREATE OR REPLACE FUNCTION screening_private.market_passes(
    p_anchor_date date,
    p_use_volume boolean,
    p_use_daily_price boolean,
    p_use_weekly_price boolean,
    p_volume_ratio_threshold double precision,
    p_volume_surge_min_days integer,
    p_daily_ma_tolerance_pct double precision,
    p_weekly_ma_tolerance_pct double precision,
    p_exclude_universe boolean
) RETURNS TABLE (
    gvkey text,
    iid text,
    open_price double precision,
    high_price double precision,
    low_price double precision,
    close_price double precision,
    volume double precision
)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $$
    WITH settings AS (
        SELECT
            1.0 - p_daily_ma_tolerance_pct / 100.0 AS daily_lower,
            1.0 + p_daily_ma_tolerance_pct / 100.0 AS daily_upper,
            1.0 - p_weekly_ma_tolerance_pct / 100.0 AS weekly_lower,
            1.0 + p_weekly_ma_tolerance_pct / 100.0 AS weekly_upper
    ),
    volume_counts AS (
        SELECT d.gvkey, d.iid, count(*) AS surge_days
        FROM public.security_daily_feature_snapshot d
        WHERE p_use_volume
          AND d.snapshot_date BETWEEN p_anchor_date - interval '3 months' AND p_anchor_date
          AND d.volume_ratio >= p_volume_ratio_threshold
        GROUP BY d.gvkey, d.iid
    ),
    daily_candidates AS (
        SELECT
            d.*,
            coalesce(v.surge_days, 0) AS surge_days,
            w.week_end_date IS NOT NULL AS is_official_week_end,
            w.weekly_ma5,
            w.weekly_ma10,
            w.weekly_ma30,
            w.weekly_h_confirmed_using_date,
            w.future_weekly_ma10,
            w.future_weekly_ma30
        FROM public.security_daily_feature_snapshot d
        LEFT JOIN volume_counts v USING (gvkey, iid)
        LEFT JOIN public.security_weekly_feature_snapshot w
          ON w.week_end_date = d.snapshot_date
         AND w.gvkey = d.gvkey
         AND w.iid = d.iid
        WHERE d.snapshot_date = p_anchor_date
    ),
    standalone_weekly AS (
        SELECT
            w.week_end_date AS snapshot_date,
            w.gvkey,
            w.iid,
            w.weekly_open_price AS open_price,
            w.weekly_high_price AS high_price,
            w.weekly_low_price AS low_price,
            w.weekly_close_price AS close_price,
            w.weekly_volume AS volume,
            NULL::double precision AS volume_ratio,
            NULL::double precision AS ma20,
            NULL::double precision AS ma50,
            NULL::double precision AS ma100,
            NULL::date AS daily_f_confirmed_using_date,
            NULL::double precision AS future_daily_ma20,
            NULL::double precision AS future_daily_ma50,
            0::bigint AS surge_days,
            true AS is_official_week_end,
            w.weekly_ma5,
            w.weekly_ma10,
            w.weekly_ma30,
            w.weekly_h_confirmed_using_date,
            w.future_weekly_ma10,
            w.future_weekly_ma30
        FROM public.security_weekly_feature_snapshot w
        WHERE w.week_end_date = p_anchor_date
    ),
    candidates AS (
        SELECT
            d.snapshot_date, d.gvkey, d.iid,
            d.open_price, d.high_price, d.low_price, d.close_price, d.volume,
            d.volume_ratio, d.ma20, d.ma50, d.ma100,
            d.daily_f_confirmed_using_date, d.future_daily_ma20, d.future_daily_ma50,
            d.surge_days, d.is_official_week_end,
            d.weekly_ma5, d.weekly_ma10, d.weekly_ma30,
            d.weekly_h_confirmed_using_date, d.future_weekly_ma10, d.future_weekly_ma30
        FROM daily_candidates d
        WHERE p_use_volume OR p_use_daily_price
        UNION ALL
        SELECT * FROM standalone_weekly
        WHERE p_use_weekly_price AND NOT p_use_volume AND NOT p_use_daily_price
    ),
    passing AS (
        SELECT c.*
        FROM candidates c
        CROSS JOIN settings s
        JOIN public.security_master sm USING (gvkey, iid)
        WHERE (NOT p_exclude_universe OR NOT coalesce(sm.is_excluded_universe, false))
          AND c.close_price >= 5.0
          AND (
              NOT p_use_volume OR (
                  c.volume_ratio >= p_volume_ratio_threshold
                  AND c.surge_days >= p_volume_surge_min_days
              )
          )
          AND (
              NOT p_use_daily_price OR (
                  c.ma20 IS NOT NULL AND c.ma50 IS NOT NULL AND c.ma100 IS NOT NULL
                  AND c.ma50 <> 0 AND c.ma100 <> 0
                  AND c.ma20 / c.ma50 BETWEEN s.daily_lower AND s.daily_upper
                  AND c.ma20 / c.ma100 BETWEEN s.daily_lower AND s.daily_upper
                  AND c.ma50 / c.ma100 BETWEEN s.daily_lower AND s.daily_upper
                  AND c.daily_f_confirmed_using_date IS NOT NULL
                  AND c.future_daily_ma20 IS NOT NULL AND c.future_daily_ma50 IS NOT NULL
                  AND c.ma20 <= c.ma50
                  AND c.future_daily_ma20 > c.future_daily_ma50
              )
          )
          AND (
              NOT p_use_weekly_price
              OR ((p_use_volume OR p_use_daily_price) AND NOT c.is_official_week_end)
              OR (
                  c.is_official_week_end
                  AND c.weekly_ma5 IS NOT NULL AND c.weekly_ma10 IS NOT NULL
                  AND c.weekly_ma30 IS NOT NULL
                  AND c.weekly_ma10 <> 0 AND c.weekly_ma30 <> 0
                  AND c.weekly_ma5 / c.weekly_ma10 BETWEEN s.weekly_lower AND s.weekly_upper
                  AND c.weekly_ma5 / c.weekly_ma30 BETWEEN s.weekly_lower AND s.weekly_upper
                  AND c.weekly_ma10 / c.weekly_ma30 BETWEEN s.weekly_lower AND s.weekly_upper
                  AND c.weekly_h_confirmed_using_date IS NOT NULL
                  AND c.future_weekly_ma10 IS NOT NULL AND c.future_weekly_ma30 IS NOT NULL
                  AND c.weekly_ma10 <= c.weekly_ma30
                  AND c.future_weekly_ma10 > c.future_weekly_ma30
              )
          )
    )
    SELECT p.gvkey, p.iid, p.open_price, p.high_price, p.low_price, p.close_price, p.volume
    FROM passing p;
$$;

CREATE OR REPLACE FUNCTION public.screen_company_counts(
    p_start_date date,
    p_end_date date,
    p_use_fundamental boolean,
    p_use_volume boolean,
    p_use_daily_price boolean,
    p_use_weekly_price boolean,
    p_annual_growth_pct double precision,
    p_annual_years integer,
    p_quarterly_growth_pct double precision,
    p_quarter_count integer,
    p_volume_ratio_threshold double precision,
    p_volume_surge_min_days integer,
    p_daily_ma_tolerance_pct double precision,
    p_weekly_ma_tolerance_pct double precision,
    p_exclude_universe boolean DEFAULT false
) RETURNS TABLE (
    inspection_date date,
    selected_company_count bigint,
    evaluation_status text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, screening_private
AS $$
BEGIN
    PERFORM screening_private.validate_screen_request(
        p_start_date, p_end_date, p_use_fundamental, p_use_volume,
        p_use_daily_price, p_use_weekly_price, p_annual_growth_pct,
        p_annual_years, p_quarterly_growth_pct, p_quarter_count,
        p_volume_ratio_threshold, p_volume_surge_min_days,
        p_daily_ma_tolerance_pct, p_weekly_ma_tolerance_pct
    );

    IF p_use_fundamental THEN
        RETURN QUERY
        SELECT
            p_end_date,
            count(*)::bigint,
            'complete'::text
        FROM screening_private.fundamental_passes(
            p_end_date, p_annual_growth_pct, p_annual_years,
            p_quarterly_growth_pct, p_quarter_count
        );
        RETURN;
    END IF;

    RETURN QUERY
    WITH anchors AS (
        SELECT d.snapshot_date
        FROM public.security_daily_feature_snapshot d
        WHERE NOT (p_use_weekly_price AND NOT p_use_volume AND NOT p_use_daily_price)
          AND d.snapshot_date BETWEEN p_start_date AND p_end_date
        GROUP BY d.snapshot_date
        UNION
        SELECT w.week_end_date
        FROM public.security_weekly_feature_snapshot w
        WHERE p_use_weekly_price AND NOT p_use_volume AND NOT p_use_daily_price
          AND w.week_end_date BETWEEN p_start_date AND p_end_date
        GROUP BY w.week_end_date
    )
    SELECT
        a.snapshot_date,
        CASE WHEN st.status = 'complete' THEN count(DISTINCT m.gvkey) ELSE NULL END,
        st.status
    FROM anchors a
    CROSS JOIN LATERAL (
        SELECT screening_private.evaluation_status(
            a.snapshot_date, false, p_use_volume, p_use_daily_price, p_use_weekly_price
        ) AS status
    ) st
    LEFT JOIN LATERAL screening_private.market_passes(
        a.snapshot_date, p_use_volume, p_use_daily_price, p_use_weekly_price,
        p_volume_ratio_threshold, p_volume_surge_min_days,
        p_daily_ma_tolerance_pct, p_weekly_ma_tolerance_pct,
        p_exclude_universe
    ) m ON st.status = 'complete'
    GROUP BY a.snapshot_date, st.status
    ORDER BY a.snapshot_date;
END;
$$;

CREATE OR REPLACE FUNCTION public.screen_companies_for_date(
    p_inspection_date date,
    p_use_fundamental boolean,
    p_use_volume boolean,
    p_use_daily_price boolean,
    p_use_weekly_price boolean,
    p_annual_growth_pct double precision,
    p_annual_years integer,
    p_quarterly_growth_pct double precision,
    p_quarter_count integer,
    p_volume_ratio_threshold double precision,
    p_volume_surge_min_days integer,
    p_daily_ma_tolerance_pct double precision,
    p_weekly_ma_tolerance_pct double precision,
    p_exclude_universe boolean DEFAULT false
) RETURNS TABLE (
    evaluation_status text,
    inspection_date date,
    gvkey text,
    iid text,
    ticker text,
    company_name text,
    open_price double precision,
    high_price double precision,
    low_price double precision,
    close_price double precision,
    volume double precision
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, screening_private
AS $$
DECLARE
    v_status text;
BEGIN
    PERFORM screening_private.validate_screen_request(
        p_inspection_date, p_inspection_date, p_use_fundamental, p_use_volume,
        p_use_daily_price, p_use_weekly_price, p_annual_growth_pct,
        p_annual_years, p_quarterly_growth_pct, p_quarter_count,
        p_volume_ratio_threshold, p_volume_surge_min_days,
        p_daily_ma_tolerance_pct, p_weekly_ma_tolerance_pct
    );

    IF p_use_fundamental THEN
        RETURN QUERY
        SELECT
            'complete'::text, p_inspection_date, f.gvkey, NULL::text,
            cm.ticker, cm.company_name,
            NULL::double precision, NULL::double precision, NULL::double precision,
            NULL::double precision, NULL::double precision
        FROM screening_private.fundamental_passes(
            p_inspection_date, p_annual_growth_pct, p_annual_years,
            p_quarterly_growth_pct, p_quarter_count
        ) f
        JOIN public.company_master cm USING (gvkey)
        ORDER BY cm.company_name, cm.ticker;
        RETURN;
    END IF;

    v_status := screening_private.evaluation_status(
        p_inspection_date, false, p_use_volume, p_use_daily_price, p_use_weekly_price
    );
    IF v_status <> 'complete' THEN
        RETURN QUERY SELECT
            v_status, p_inspection_date, NULL::text, NULL::text, NULL::text, NULL::text,
            NULL::double precision, NULL::double precision, NULL::double precision,
            NULL::double precision, NULL::double precision;
        RETURN;
    END IF;

    RETURN QUERY
    WITH passing AS (
        SELECT m.*, sm.ticker, sm.company_name, sm.last_seen_date,
               row_number() OVER (
                   PARTITION BY m.gvkey
                   ORDER BY (m.iid = '01') DESC, sm.last_seen_date DESC NULLS LAST, m.iid
               ) AS preference_rank
        FROM screening_private.market_passes(
            p_inspection_date, p_use_volume, p_use_daily_price, p_use_weekly_price,
            p_volume_ratio_threshold, p_volume_surge_min_days,
            p_daily_ma_tolerance_pct, p_weekly_ma_tolerance_pct,
            p_exclude_universe
        ) m
        JOIN public.security_master sm USING (gvkey, iid)
    )
    SELECT
        'complete'::text, p_inspection_date, p.gvkey, p.iid, p.ticker, p.company_name,
        p.open_price, p.high_price, p.low_price, p.close_price, p.volume
    FROM passing p
    WHERE p.preference_rank = 1
    ORDER BY p.company_name, p.ticker;
END;
$$;

REVOKE ALL ON FUNCTION public.screen_company_counts(
    date, date, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.screen_companies_for_date(
    date, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.screen_company_counts(
    date, date, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.screen_companies_for_date(
    date, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) TO anon, authenticated;

COMMENT ON FUNCTION public.screen_company_counts(
    date, date, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) IS 'Returns distinct-company screening counts and explicit complete/pending status by inspection anchor.';

COMMENT ON FUNCTION public.screen_companies_for_date(
    date, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) IS 'Returns one preferred passing security per company for an inspection anchor, or a pending status row.';

-- Version 2: separate annual and quarterly fundamental screens with calendar-quarter anchors.
CREATE OR REPLACE FUNCTION screening_private.validate_screen_request_v2(
    p_start_date date,
    p_end_date date,
    p_fundamental_through_date date,
    p_fundamental_inspection_periods integer,
    p_use_annual_fundamental boolean,
    p_use_quarterly_fundamental boolean,
    p_use_volume boolean,
    p_use_daily_price boolean,
    p_use_weekly_price boolean,
    p_annual_growth_pct double precision,
    p_annual_years integer,
    p_quarterly_growth_pct double precision,
    p_quarter_count integer,
    p_volume_ratio_threshold double precision,
    p_volume_surge_min_days integer,
    p_daily_ma_tolerance_pct double precision,
    p_weekly_ma_tolerance_pct double precision
) RETURNS void
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $$
DECLARE
    v_use_fundamental boolean := p_use_annual_fundamental OR p_use_quarterly_fundamental;
BEGIN
    IF NOT (
        v_use_fundamental OR p_use_volume OR p_use_daily_price OR p_use_weekly_price
    ) THEN
        RAISE EXCEPTION 'Select at least one condition group';
    END IF;
    IF p_use_annual_fundamental AND p_use_quarterly_fundamental THEN
        RAISE EXCEPTION 'Annual and quarterly fundamental screens are mutually exclusive';
    END IF;
    IF v_use_fundamental AND (p_use_volume OR p_use_daily_price OR p_use_weekly_price) THEN
        RAISE EXCEPTION 'Fundamental screening cannot be combined with market conditions';
    END IF;

    IF v_use_fundamental THEN
        IF p_fundamental_through_date IS NULL
           OR p_fundamental_through_date <> (
               date_trunc('quarter', p_fundamental_through_date)::date
               + interval '3 months - 1 day'
           )::date THEN
            RAISE EXCEPTION 'Fundamental inspection-through date must be a calendar-quarter end';
        END IF;
        IF p_fundamental_through_date >= date_trunc('quarter', CURRENT_DATE)::date THEN
            RAISE EXCEPTION 'Fundamental inspection quarter must be completed';
        END IF;
        IF p_fundamental_inspection_periods NOT BETWEEN 1 AND 12 THEN
            RAISE EXCEPTION 'Fundamental inspection periods must be between 1 and 12';
        END IF;
    ELSE
        IF p_start_date IS NULL OR p_end_date IS NULL OR p_start_date > p_end_date THEN
            RAISE EXCEPTION 'A valid inclusive market inspection window is required';
        END IF;
        IF p_end_date > CURRENT_DATE THEN
            RAISE EXCEPTION 'Inspection dates cannot be in the future';
        END IF;
        IF p_end_date - p_start_date > 89 THEN
            RAISE EXCEPTION 'Inspection window cannot exceed 90 calendar days';
        END IF;
    END IF;

    IF p_annual_growth_pct < 0 OR p_annual_years NOT BETWEEN 1 AND 10
       OR p_quarterly_growth_pct < 0 OR p_quarter_count NOT BETWEEN 1 AND 20
       OR p_volume_ratio_threshold <= 0 OR p_volume_surge_min_days NOT BETWEEN 1 AND 100
       OR p_daily_ma_tolerance_pct < 0 OR p_daily_ma_tolerance_pct > 100
       OR p_weekly_ma_tolerance_pct < 0 OR p_weekly_ma_tolerance_pct > 100 THEN
        RAISE EXCEPTION 'One or more screening parameters are outside the allowed range';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION screening_private.annual_fundamental_passes(
    p_period_end date,
    p_annual_growth_pct double precision,
    p_annual_years integer
) RETURNS TABLE (gvkey text)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $$
    WITH candidates AS MATERIALIZED (
        SELECT gvkey, fyear, datadate
        FROM (
            SELECT
                a.gvkey,
                a.fyear,
                a.datadate,
                row_number() OVER (
                    PARTITION BY a.gvkey ORDER BY a.datadate DESC, a.fyear DESC
                ) AS candidate_rank
            FROM public.annual_growth_history a
            WHERE a.datadate >= date_trunc('quarter', p_period_end)::date
              AND a.datadate <= p_period_end
        ) ranked_candidates
        WHERE candidate_rank = 1
    ),
    history AS MATERIALIZED (
        SELECT
            a.*,
            row_number() OVER (
                PARTITION BY a.gvkey ORDER BY a.fyear DESC, a.datadate DESC NULLS LAST
            ) AS period_rank
        FROM public.annual_growth_history a
        JOIN candidates c ON c.gvkey = a.gvkey AND a.fyear <= c.fyear
    )
    SELECT h.gvkey
    FROM history h
    WHERE h.period_rank <= p_annual_years
    GROUP BY h.gvkey
    HAVING count(*) = p_annual_years
       AND max(h.fyear) - min(h.fyear) = p_annual_years - 1
       AND bool_and(h.annual_revenue_growth IS NOT NULL)
       AND bool_and(h.annual_operating_income_growth IS NOT NULL)
       AND bool_and(h.annual_revenue_growth >= p_annual_growth_pct / 100.0)
       AND bool_and(h.annual_operating_income_growth >= p_annual_growth_pct / 100.0);
$$;

CREATE OR REPLACE FUNCTION screening_private.quarterly_fundamental_passes(
    p_period_end date,
    p_quarterly_growth_pct double precision,
    p_quarter_count integer
) RETURNS TABLE (gvkey text)
LANGUAGE sql
STABLE
SET search_path = pg_catalog, public
AS $$
    WITH candidates AS MATERIALIZED (
        SELECT gvkey, fyearq, fqtr, datadate, fyearq * 4 + fqtr AS period_number
        FROM (
            SELECT
                q.*,
                row_number() OVER (
                    PARTITION BY q.gvkey
                    ORDER BY q.datadate DESC, q.fyearq DESC, q.fqtr DESC
                ) AS candidate_rank
            FROM public.quarterly_growth_history q
            WHERE q.datadate >= date_trunc('quarter', p_period_end)::date
              AND q.datadate <= p_period_end
        ) ranked_candidates
        WHERE candidate_rank = 1
    ),
    history AS MATERIALIZED (
        SELECT
            q.*,
            q.fyearq * 4 + q.fqtr AS period_number,
            row_number() OVER (
                PARTITION BY q.gvkey
                ORDER BY q.fyearq DESC, q.fqtr DESC, q.datadate DESC NULLS LAST
            ) AS period_rank
        FROM public.quarterly_growth_history q
        JOIN candidates c
          ON c.gvkey = q.gvkey
         AND q.fyearq * 4 + q.fqtr <= c.period_number
    )
    SELECT h.gvkey
    FROM history h
    WHERE h.period_rank <= p_quarter_count
    GROUP BY h.gvkey
    HAVING count(*) = p_quarter_count
       AND max(h.period_number) - min(h.period_number) = p_quarter_count - 1
       AND bool_and(h.quarterly_revenue_growth IS NOT NULL)
       AND bool_and(h.quarterly_operating_income_growth IS NOT NULL)
       AND bool_and(h.quarterly_revenue_growth >= p_quarterly_growth_pct / 100.0)
       AND bool_and(h.quarterly_operating_income_growth >= p_quarterly_growth_pct / 100.0);
$$;

CREATE OR REPLACE FUNCTION public.screen_company_counts(
    p_start_date date,
    p_end_date date,
    p_fundamental_through_date date,
    p_fundamental_inspection_periods integer,
    p_use_annual_fundamental boolean,
    p_use_quarterly_fundamental boolean,
    p_use_volume boolean,
    p_use_daily_price boolean,
    p_use_weekly_price boolean,
    p_annual_growth_pct double precision,
    p_annual_years integer,
    p_quarterly_growth_pct double precision,
    p_quarter_count integer,
    p_volume_ratio_threshold double precision,
    p_volume_surge_min_days integer,
    p_daily_ma_tolerance_pct double precision,
    p_weekly_ma_tolerance_pct double precision,
    p_exclude_universe boolean DEFAULT false
) RETURNS TABLE (
    inspection_date date,
    selected_company_count bigint,
    evaluation_status text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, screening_private
SET statement_timeout = '10s'
AS $$
DECLARE
    v_use_fundamental boolean := p_use_annual_fundamental OR p_use_quarterly_fundamental;
BEGIN
    PERFORM screening_private.validate_screen_request_v2(
        p_start_date, p_end_date, p_fundamental_through_date,
        p_fundamental_inspection_periods, p_use_annual_fundamental,
        p_use_quarterly_fundamental, p_use_volume, p_use_daily_price,
        p_use_weekly_price, p_annual_growth_pct, p_annual_years,
        p_quarterly_growth_pct, p_quarter_count, p_volume_ratio_threshold,
        p_volume_surge_min_days, p_daily_ma_tolerance_pct,
        p_weekly_ma_tolerance_pct
    );

    IF v_use_fundamental THEN
        RETURN QUERY
        WITH anchors AS (
            SELECT (
                p_fundamental_through_date
                - make_interval(months => 3 * offset_number)
            )::date AS period_end
            FROM generate_series(0, p_fundamental_inspection_periods - 1) offset_number
        )
        SELECT
            a.period_end,
            CASE
                WHEN p_use_annual_fundamental THEN (
                    SELECT count(*) FROM screening_private.annual_fundamental_passes(
                        a.period_end, p_annual_growth_pct, p_annual_years
                    )
                )
                ELSE (
                    SELECT count(*) FROM screening_private.quarterly_fundamental_passes(
                        a.period_end, p_quarterly_growth_pct, p_quarter_count
                    )
                )
            END::bigint,
            CASE
                WHEN p_use_annual_fundamental AND NOT EXISTS (
                    SELECT 1 FROM public.annual_growth_history h
                    WHERE h.datadate >= date_trunc('quarter', a.period_end)::date
                      AND h.datadate <= a.period_end
                ) THEN 'no_data'
                WHEN p_use_quarterly_fundamental AND NOT EXISTS (
                    SELECT 1 FROM public.quarterly_growth_history h
                    WHERE h.datadate >= date_trunc('quarter', a.period_end)::date
                      AND h.datadate <= a.period_end
                ) THEN 'no_data'
                ELSE 'complete'
            END::text
        FROM anchors a
        ORDER BY a.period_end;
        RETURN;
    END IF;

    RETURN QUERY
    WITH anchors AS (
        SELECT d.snapshot_date
        FROM public.security_daily_feature_snapshot d
        WHERE NOT (p_use_weekly_price AND NOT p_use_volume AND NOT p_use_daily_price)
          AND d.snapshot_date BETWEEN p_start_date AND p_end_date
        GROUP BY d.snapshot_date
        UNION
        SELECT w.week_end_date
        FROM public.security_weekly_feature_snapshot w
        WHERE p_use_weekly_price AND NOT p_use_volume AND NOT p_use_daily_price
          AND w.week_end_date BETWEEN p_start_date AND p_end_date
        GROUP BY w.week_end_date
    )
    SELECT
        a.snapshot_date,
        CASE WHEN st.status = 'complete' THEN count(DISTINCT m.gvkey) ELSE NULL END,
        st.status
    FROM anchors a
    CROSS JOIN LATERAL (
        SELECT screening_private.evaluation_status(
            a.snapshot_date, false, p_use_volume, p_use_daily_price, p_use_weekly_price
        ) AS status
    ) st
    LEFT JOIN LATERAL screening_private.market_passes(
        a.snapshot_date, p_use_volume, p_use_daily_price, p_use_weekly_price,
        p_volume_ratio_threshold, p_volume_surge_min_days,
        p_daily_ma_tolerance_pct, p_weekly_ma_tolerance_pct,
        p_exclude_universe
    ) m ON st.status = 'complete'
    GROUP BY a.snapshot_date, st.status
    ORDER BY a.snapshot_date;
END;
$$;

CREATE OR REPLACE FUNCTION public.screen_companies_for_date(
    p_inspection_date date,
    p_use_annual_fundamental boolean,
    p_use_quarterly_fundamental boolean,
    p_use_volume boolean,
    p_use_daily_price boolean,
    p_use_weekly_price boolean,
    p_annual_growth_pct double precision,
    p_annual_years integer,
    p_quarterly_growth_pct double precision,
    p_quarter_count integer,
    p_volume_ratio_threshold double precision,
    p_volume_surge_min_days integer,
    p_daily_ma_tolerance_pct double precision,
    p_weekly_ma_tolerance_pct double precision,
    p_exclude_universe boolean DEFAULT false
) RETURNS TABLE (
    evaluation_status text,
    inspection_date date,
    gvkey text,
    iid text,
    ticker text,
    company_name text,
    open_price double precision,
    high_price double precision,
    low_price double precision,
    close_price double precision,
    volume double precision
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, screening_private
SET statement_timeout = '10s'
AS $$
DECLARE
    v_status text;
    v_use_fundamental boolean := p_use_annual_fundamental OR p_use_quarterly_fundamental;
BEGIN
    IF p_use_annual_fundamental AND p_use_quarterly_fundamental THEN
        RAISE EXCEPTION 'Annual and quarterly fundamental screens are mutually exclusive';
    END IF;
    IF v_use_fundamental AND (p_use_volume OR p_use_daily_price OR p_use_weekly_price) THEN
        RAISE EXCEPTION 'Fundamental screening cannot be combined with market conditions';
    END IF;

    IF v_use_fundamental THEN
        v_status := CASE
            WHEN p_use_annual_fundamental AND NOT EXISTS (
                SELECT 1 FROM public.annual_growth_history h
                WHERE h.datadate >= date_trunc('quarter', p_inspection_date)::date
                  AND h.datadate <= p_inspection_date
            ) THEN 'no_data'
            WHEN p_use_quarterly_fundamental AND NOT EXISTS (
                SELECT 1 FROM public.quarterly_growth_history h
                WHERE h.datadate >= date_trunc('quarter', p_inspection_date)::date
                  AND h.datadate <= p_inspection_date
            ) THEN 'no_data'
            ELSE 'complete'
        END;
        IF v_status = 'no_data' THEN
            RETURN QUERY SELECT
                v_status, p_inspection_date, NULL::text, NULL::text, NULL::text, NULL::text,
                NULL::double precision, NULL::double precision, NULL::double precision,
                NULL::double precision, NULL::double precision;
            RETURN;
        END IF;

        RETURN QUERY
        SELECT
            'complete'::text, p_inspection_date, f.gvkey, NULL::text,
            cm.ticker, cm.company_name,
            NULL::double precision, NULL::double precision, NULL::double precision,
            NULL::double precision, NULL::double precision
        FROM (
            SELECT * FROM screening_private.annual_fundamental_passes(
                p_inspection_date, p_annual_growth_pct, p_annual_years
            ) WHERE p_use_annual_fundamental
            UNION ALL
            SELECT * FROM screening_private.quarterly_fundamental_passes(
                p_inspection_date, p_quarterly_growth_pct, p_quarter_count
            ) WHERE p_use_quarterly_fundamental
        ) f
        JOIN public.company_master cm USING (gvkey)
        ORDER BY cm.company_name, cm.ticker;
        RETURN;
    END IF;

    v_status := screening_private.evaluation_status(
        p_inspection_date, false, p_use_volume, p_use_daily_price, p_use_weekly_price
    );
    IF v_status <> 'complete' THEN
        RETURN QUERY SELECT
            v_status, p_inspection_date, NULL::text, NULL::text, NULL::text, NULL::text,
            NULL::double precision, NULL::double precision, NULL::double precision,
            NULL::double precision, NULL::double precision;
        RETURN;
    END IF;

    RETURN QUERY
    WITH passing AS (
        SELECT m.*, sm.ticker, sm.company_name, sm.last_seen_date,
               row_number() OVER (
                   PARTITION BY m.gvkey
                   ORDER BY (m.iid = '01') DESC, sm.last_seen_date DESC NULLS LAST, m.iid
               ) AS preference_rank
        FROM screening_private.market_passes(
            p_inspection_date, p_use_volume, p_use_daily_price, p_use_weekly_price,
            p_volume_ratio_threshold, p_volume_surge_min_days,
            p_daily_ma_tolerance_pct, p_weekly_ma_tolerance_pct,
            p_exclude_universe
        ) m
        JOIN public.security_master sm USING (gvkey, iid)
    )
    SELECT
        'complete'::text, p_inspection_date, p.gvkey, p.iid, p.ticker, p.company_name,
        p.open_price, p.high_price, p.low_price, p.close_price, p.volume
    FROM passing p
    WHERE p.preference_rank = 1
    ORDER BY p.company_name, p.ticker;
END;
$$;

CREATE OR REPLACE FUNCTION public.screen_data_availability()
RETURNS TABLE (
    latest_daily_date date,
    latest_weekly_date date,
    latest_annual_fundamental_date date,
    latest_quarterly_fundamental_date date
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET statement_timeout = '5s'
AS $$
    SELECT
        (SELECT max(snapshot_date) FROM public.security_daily_feature_snapshot),
        (SELECT max(week_end_date) FROM public.security_weekly_feature_snapshot),
        (SELECT max(datadate) FROM public.annual_growth_history),
        (SELECT max(datadate) FROM public.quarterly_growth_history);
$$;

REVOKE ALL ON FUNCTION public.screen_company_counts(
    date, date, date, integer, boolean, boolean, boolean, boolean, boolean,
    double precision, integer, double precision, integer, double precision,
    integer, double precision, double precision, boolean
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.screen_companies_for_date(
    date, boolean, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.screen_company_counts(
    date, date, date, integer, boolean, boolean, boolean, boolean, boolean,
    double precision, integer, double precision, integer, double precision,
    integer, double precision, double precision, boolean
) TO anon, authenticated;
GRANT EXECUTE ON FUNCTION public.screen_companies_for_date(
    date, boolean, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) TO anon, authenticated;
REVOKE ALL ON FUNCTION public.screen_data_availability() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.screen_data_availability() TO anon, authenticated;

-- Retire browser access to the obsolete combined A+B overloads.
REVOKE ALL ON FUNCTION public.screen_company_counts(
    date, date, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) FROM anon, authenticated;
REVOKE ALL ON FUNCTION public.screen_companies_for_date(
    date, boolean, boolean, boolean, boolean, double precision, integer,
    double precision, integer, double precision, integer, double precision,
    double precision, boolean
) FROM anon, authenticated;
