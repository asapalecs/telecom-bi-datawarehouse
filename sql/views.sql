/*
   DEPOZIT DE DATE TELECOM - VIEW-URI ANALITICE (STRAT KPI)
   Fiecare KPI are o singura definitie. Scris in T-SQL; ETL-ul il traduce
   pentru SQLite.
*/


/*
   V_MONTHLY_KPI - indicatorii lunari principali
   Clientii activi se numara cu COUNT(DISTINCT customer_id), nu pe customer_key.
*/
IF OBJECT_ID('dbo.V_MONTHLY_KPI', 'V') IS NOT NULL DROP VIEW dbo.V_MONTHLY_KPI;
GO
CREATE VIEW dbo.V_MONTHLY_KPI AS
SELECT
    d.year_month,
    d.year,
    d.quarter,
    d.month,
    d.month_name,

    COUNT(DISTINCT f.customer_id)                              AS active_customers,
    COUNT(*)                                                   AS subscriber_months,

    CAST(SUM(f.total_revenue) AS DECIMAL(18,2))                AS total_revenue,
    CAST(SUM(f.gross_margin)  AS DECIMAL(18,2))                AS gross_margin,

    CAST(SUM(f.total_revenue) / NULLIF(COUNT(DISTINCT f.customer_id), 0)
         AS DECIMAL(12,2))                                     AS arpu,

    CAST(100.0 * SUM(CAST(f.is_churn AS INT))
         / NULLIF(COUNT(*), 0) AS DECIMAL(6,3))                AS churn_rate_pct,
    SUM(CAST(f.is_churn AS INT))                               AS churned_customers,

    -- Reclamatii la 100 abonat-luni
    CAST(100.0 * SUM(f.complaint_count)
         / NULLIF(COUNT(*), 0) AS DECIMAL(8,3))                AS complaint_rate_pct,
    SUM(f.complaint_count)                                     AS total_complaints,

    CAST(AVG(f.data_used_gb)   AS DECIMAL(10,3))               AS avg_data_gb,
    CAST(AVG(CAST(f.voice_used_min AS FLOAT)) AS DECIMAL(10,1)) AS avg_voice_min,

    CAST(SUM(f.overage_amount) AS DECIMAL(18,2))               AS overage_revenue,
    CAST(SUM(f.roaming_amount) AS DECIMAL(18,2))               AS roaming_revenue,
    CAST(SUM(f.discount_amount) AS DECIMAL(18,2))              AS total_discounts
FROM dbo.FACT_SUBSCRIPTION_MONTHLY f
JOIN dbo.DIM_DATE d ON d.date_key = f.date_key
GROUP BY d.year_month, d.year, d.quarter, d.month, d.month_name;
GO


/*
   V_ARPU_BY_SEGMENT - ARPU pe segment si familie de plan
   Venitul e atribuit segmentului valabil in luna respectiva (SCD Tip 2).
*/
IF OBJECT_ID('dbo.V_ARPU_BY_SEGMENT', 'V') IS NOT NULL DROP VIEW dbo.V_ARPU_BY_SEGMENT;
GO
CREATE VIEW dbo.V_ARPU_BY_SEGMENT AS
SELECT
    d.year_month,
    c.segment,
    p.plan_family,
    p.price_tier,
    COUNT(DISTINCT f.customer_id)                              AS customers,
    CAST(SUM(f.total_revenue) AS DECIMAL(18,2))                AS revenue,
    CAST(SUM(f.total_revenue) / NULLIF(COUNT(DISTINCT f.customer_id), 0)
         AS DECIMAL(12,2))                                     AS arpu,
    CAST(100.0 * SUM(CAST(f.is_churn AS INT))
         / NULLIF(COUNT(*), 0) AS DECIMAL(6,3))                AS churn_rate_pct,
    CAST(AVG(f.data_used_gb) AS DECIMAL(10,3))                 AS avg_data_gb
FROM dbo.FACT_SUBSCRIPTION_MONTHLY f
JOIN dbo.DIM_DATE     d ON d.date_key     = f.date_key
JOIN dbo.DIM_CUSTOMER c ON c.customer_key = f.customer_key
JOIN dbo.DIM_PLAN     p ON p.plan_key     = f.plan_key
GROUP BY d.year_month, c.segment, p.plan_family, p.price_tier;
GO


/* V_CHURN_ANALYSIS - factorii care determina churn-ul */
IF OBJECT_ID('dbo.V_CHURN_ANALYSIS', 'V') IS NOT NULL DROP VIEW dbo.V_CHURN_ANALYSIS;
GO
CREATE VIEW dbo.V_CHURN_ANALYSIS AS
SELECT
    d.year_month,
    p.plan_family,
    p.is_contract,
    ch.channel_name,
    g.region,
    CASE
        WHEN f.tenure_months < 3  THEN '0-2 luni'
        WHEN f.tenure_months < 6  THEN '3-5 luni'
        WHEN f.tenure_months < 12 THEN '6-11 luni'
        WHEN f.tenure_months < 24 THEN '12-23 luni'
        ELSE '24+ luni'
    END                                                        AS tenure_band,
    CASE
        WHEN f.complaint_count = 0 THEN 'Fara reclamatii'
        WHEN f.complaint_count = 1 THEN '1 reclamatie'
        ELSE '2+ reclamatii'
    END                                                        AS complaint_band,
    COUNT(*)                                                   AS subscriber_months,
    SUM(CAST(f.is_churn AS INT))                               AS churned,
    CAST(100.0 * SUM(CAST(f.is_churn AS INT))
         / NULLIF(COUNT(*), 0) AS DECIMAL(6,3))                AS churn_rate_pct,
    CAST(AVG(f.total_revenue) AS DECIMAL(12,2))                AS avg_monthly_revenue
FROM dbo.FACT_SUBSCRIPTION_MONTHLY f
JOIN dbo.DIM_DATE      d  ON d.date_key      = f.date_key
JOIN dbo.DIM_PLAN      p  ON p.plan_key      = f.plan_key
JOIN dbo.DIM_CHANNEL   ch ON ch.channel_key  = f.channel_key
JOIN dbo.DIM_GEOGRAPHY g  ON g.geography_key = f.geography_key
GROUP BY
    d.year_month, p.plan_family, p.is_contract, ch.channel_name, g.region,
    CASE
        WHEN f.tenure_months < 3  THEN '0-2 luni'
        WHEN f.tenure_months < 6  THEN '3-5 luni'
        WHEN f.tenure_months < 12 THEN '6-11 luni'
        WHEN f.tenure_months < 24 THEN '12-23 luni'
        ELSE '24+ luni'
    END,
    CASE
        WHEN f.complaint_count = 0 THEN 'Fara reclamatii'
        WHEN f.complaint_count = 1 THEN '1 reclamatie'
        ELSE '2+ reclamatii'
    END;
GO


/*
   V_CUSTOMER_LIFETIME_VALUE
   CLV = marja realizata + marja lunara x (1 / rata lunara de churn a segmentului),
   cu durata ramasa plafonata la 60 de luni (ipoteza de hazard constant).
*/
IF OBJECT_ID('dbo.V_CUSTOMER_LIFETIME_VALUE', 'V') IS NOT NULL DROP VIEW dbo.V_CUSTOMER_LIFETIME_VALUE;
GO
CREATE VIEW dbo.V_CUSTOMER_LIFETIME_VALUE AS
WITH customer_history AS (
    SELECT
        f.customer_id,
        MAX(f.tenure_months)                        AS tenure_months,
        COUNT(*)                                    AS months_observed,
        SUM(f.total_revenue)                        AS lifetime_revenue,
        SUM(f.gross_margin)                         AS lifetime_margin,
        AVG(f.total_revenue)                        AS avg_monthly_revenue,
        AVG(f.gross_margin)                         AS avg_monthly_margin,
        SUM(f.complaint_count)                      AS total_complaints,
        MAX(CAST(f.is_churn AS INT))                AS has_churned
    FROM dbo.FACT_SUBSCRIPTION_MONTHLY f
    GROUP BY f.customer_id
),
current_attributes AS (
    SELECT c.customer_id, c.segment, c.region, c.age_band, c.acquisition_channel
    FROM dbo.DIM_CUSTOMER c
    WHERE c.is_current = 1 AND c.customer_key <> -1
),
segment_churn AS (
    SELECT
        c.segment,
        CAST(SUM(CAST(f.is_churn AS INT)) AS FLOAT)
            / NULLIF(COUNT(*), 0)                   AS monthly_churn_rate
    FROM dbo.FACT_SUBSCRIPTION_MONTHLY f
    JOIN dbo.DIM_CUSTOMER c ON c.customer_key = f.customer_key
    GROUP BY c.segment
)
SELECT
    h.customer_id,
    a.segment,
    a.region,
    a.age_band,
    a.acquisition_channel,
    h.tenure_months,
    h.months_observed,
    CAST(h.lifetime_revenue AS DECIMAL(14,2))       AS lifetime_revenue_to_date,
    CAST(h.lifetime_margin  AS DECIMAL(14,2))       AS lifetime_margin_to_date,
    CAST(h.avg_monthly_revenue AS DECIMAL(12,2))    AS avg_monthly_revenue,
    h.total_complaints,
    h.has_churned,
    CAST(s.monthly_churn_rate AS DECIMAL(8,5))      AS segment_monthly_churn,

    CASE WHEN h.has_churned = 1 THEN 0
         ELSE CAST(
            CASE WHEN 1.0 / NULLIF(s.monthly_churn_rate, 0) > 60 THEN 60
                 ELSE 1.0 / NULLIF(s.monthly_churn_rate, 0) END
            AS DECIMAL(8,2))
    END                                             AS expected_remaining_months,

    CAST(
        h.lifetime_margin
        + CASE WHEN h.has_churned = 1 THEN 0
               ELSE h.avg_monthly_margin *
                    CASE WHEN 1.0 / NULLIF(s.monthly_churn_rate, 0) > 60 THEN 60
                         ELSE 1.0 / NULLIF(s.monthly_churn_rate, 0) END
          END
        AS DECIMAL(14,2))                           AS customer_lifetime_value
FROM customer_history h
JOIN current_attributes a ON a.customer_id = h.customer_id
JOIN segment_churn      s ON s.segment     = a.segment;
GO


/* V_REGIONAL_PERFORMANCE - performanta pe regiuni */
IF OBJECT_ID('dbo.V_REGIONAL_PERFORMANCE', 'V') IS NOT NULL DROP VIEW dbo.V_REGIONAL_PERFORMANCE;
GO
CREATE VIEW dbo.V_REGIONAL_PERFORMANCE AS
SELECT
    d.year_month,
    g.region,
    g.county,
    g.is_metro,
    COUNT(DISTINCT f.customer_id)                              AS customers,
    CAST(SUM(f.total_revenue) AS DECIMAL(18,2))                AS revenue,
    CAST(SUM(f.total_revenue) / NULLIF(COUNT(DISTINCT f.customer_id), 0)
         AS DECIMAL(12,2))                                     AS arpu,
    CAST(100.0 * SUM(CAST(f.is_churn AS INT))
         / NULLIF(COUNT(*), 0) AS DECIMAL(6,3))                AS churn_rate_pct,
    CAST(100.0 * SUM(f.complaint_count)
         / NULLIF(COUNT(*), 0) AS DECIMAL(8,3))                AS complaint_rate_pct,
    CAST(SUM(f.data_used_gb) AS DECIMAL(16,2))                 AS total_data_gb
FROM dbo.FACT_SUBSCRIPTION_MONTHLY f
JOIN dbo.DIM_DATE      d ON d.date_key      = f.date_key
JOIN dbo.DIM_GEOGRAPHY g ON g.geography_key = f.geography_key
GROUP BY d.year_month, g.region, g.county, g.is_metro;
GO


/* V_CHANNEL_QUALITY - calitatea canalelor de achizitie */
IF OBJECT_ID('dbo.V_CHANNEL_QUALITY', 'V') IS NOT NULL DROP VIEW dbo.V_CHANNEL_QUALITY;
GO
CREATE VIEW dbo.V_CHANNEL_QUALITY AS
SELECT
    ch.channel_name,
    ch.channel_type,
    COUNT(DISTINCT f.customer_id)                              AS customers_acquired,
    CAST(AVG(f.total_revenue) AS DECIMAL(12,2))                AS avg_monthly_revenue,
    CAST(SUM(f.total_revenue) / NULLIF(COUNT(DISTINCT f.customer_id), 0)
         AS DECIMAL(14,2))                                     AS revenue_per_customer,
    CAST(100.0 * SUM(CAST(f.is_churn AS INT))
         / NULLIF(COUNT(*), 0) AS DECIMAL(6,3))                AS churn_rate_pct,
    CAST(AVG(CAST(f.tenure_months AS FLOAT)) AS DECIMAL(8,2))  AS avg_tenure_months,
    CAST(100.0 * SUM(f.complaint_count)
         / NULLIF(COUNT(*), 0) AS DECIMAL(8,3))                AS complaint_rate_pct
FROM dbo.FACT_SUBSCRIPTION_MONTHLY f
JOIN dbo.DIM_CHANNEL ch ON ch.channel_key = f.channel_key
GROUP BY ch.channel_name, ch.channel_type;
GO
