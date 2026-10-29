/*
   DEPOZIT DE DATE TELECOM - DDL SCHEMA STEA (SQL Server / T-SQL)
   O tabela de fapte (granularitate abonat-luna) si cinci dimensiuni.
   Ordine: create_tables.sql, ETL-ul Python, views.sql
*/

IF DB_ID('TelecomDW') IS NULL
    CREATE DATABASE TelecomDW;
GO

USE TelecomDW;
GO


/*
   DIM_DATE
   Cheie INT YYYYMMDD; atribute precalculate ca filtrele sa ramana sargable.
*/
IF OBJECT_ID('dbo.DIM_DATE', 'U') IS NOT NULL DROP TABLE dbo.DIM_DATE;
GO
CREATE TABLE dbo.DIM_DATE (
    date_key        INT           NOT NULL,
    full_date       DATE          NOT NULL,
    year            SMALLINT      NOT NULL,
    quarter         TINYINT       NOT NULL,
    month           TINYINT       NOT NULL,
    month_name      VARCHAR(20)   NOT NULL,
    week_of_year    TINYINT       NOT NULL,
    day_of_month    TINYINT       NOT NULL,
    day_of_week     TINYINT       NOT NULL,
    day_name        VARCHAR(20)   NOT NULL,
    is_weekend      BIT           NOT NULL DEFAULT 0,
    is_month_end    BIT           NOT NULL DEFAULT 0,
    year_month      CHAR(7)       NOT NULL,   -- 'YYYY-MM'
    CONSTRAINT PK_DIM_DATE PRIMARY KEY CLUSTERED (date_key),
    CONSTRAINT CK_DIM_DATE_month   CHECK (month BETWEEN 1 AND 12),
    CONSTRAINT CK_DIM_DATE_quarter CHECK (quarter BETWEEN 1 AND 4)
);
GO
CREATE NONCLUSTERED INDEX IX_DIM_DATE_year_month ON dbo.DIM_DATE (year_month) INCLUDE (year, month, quarter);
GO


/*
   DIM_PLAN
   SCD Tip 1: un plan reevaluat primeste un plan_id nou.
*/
IF OBJECT_ID('dbo.DIM_PLAN', 'U') IS NOT NULL DROP TABLE dbo.DIM_PLAN;
GO
CREATE TABLE dbo.DIM_PLAN (
    plan_key            INT           NOT NULL,   -- surogat
    plan_id             INT           NOT NULL,   -- cheie naturala
    plan_name           VARCHAR(60)   NOT NULL,
    plan_family         VARCHAR(30)   NOT NULL,   -- Preplatit / Abonament / Familie / Business
    monthly_fee         DECIMAL(10,2) NOT NULL,
    data_allowance_gb   INT           NOT NULL,
    voice_allowance_min INT           NOT NULL,
    sms_allowance       INT           NOT NULL,
    contract_months     TINYINT       NOT NULL,
    price_tier          VARCHAR(20)   NOT NULL,   -- Economic / Mediu / Premium / Top
    is_contract         BIT           NOT NULL,
    CONSTRAINT PK_DIM_PLAN PRIMARY KEY CLUSTERED (plan_key),
    CONSTRAINT CK_DIM_PLAN_fee CHECK (monthly_fee >= 0)
);
GO
CREATE NONCLUSTERED INDEX IX_DIM_PLAN_family ON dbo.DIM_PLAN (plan_family) INCLUDE (plan_name, monthly_fee);
GO


/*
   DIM_GEOGRAPHY
   Judet si regiune in aceeasi tabela (fara snowflake).
*/
IF OBJECT_ID('dbo.DIM_GEOGRAPHY', 'U') IS NOT NULL DROP TABLE dbo.DIM_GEOGRAPHY;
GO
CREATE TABLE dbo.DIM_GEOGRAPHY (
    geography_key   INT          NOT NULL,
    county          VARCHAR(50)  NOT NULL,
    region          VARCHAR(50)  NOT NULL,
    is_metro        BIT          NOT NULL DEFAULT 0,
    CONSTRAINT PK_DIM_GEOGRAPHY PRIMARY KEY CLUSTERED (geography_key)
);
GO
CREATE NONCLUSTERED INDEX IX_DIM_GEOGRAPHY_region ON dbo.DIM_GEOGRAPHY (region) INCLUDE (county);
GO


/* DIM_CHANNEL */
IF OBJECT_ID('dbo.DIM_CHANNEL', 'U') IS NOT NULL DROP TABLE dbo.DIM_CHANNEL;
GO
CREATE TABLE dbo.DIM_CHANNEL (
    channel_key   INT          NOT NULL,
    channel_name  VARCHAR(50)  NOT NULL,
    channel_type  VARCHAR(20)  NOT NULL,   -- Digital / Fizic
    CONSTRAINT PK_DIM_CHANNEL PRIMARY KEY CLUSTERED (channel_key)
);
GO


/*
   DIM_CUSTOMER - SCD TIP 2
   customer_key e unic per versiune; clientii distincti se numara pe customer_id.
*/
IF OBJECT_ID('dbo.DIM_CUSTOMER', 'U') IS NOT NULL DROP TABLE dbo.DIM_CUSTOMER;
GO
CREATE TABLE dbo.DIM_CUSTOMER (
    customer_key        INT          NOT NULL,   -- surogat, unul per versiune
    customer_id         INT          NOT NULL,   -- cheie naturala
    full_name           VARCHAR(120) NOT NULL,
    birth_date          DATE         NULL,
    age_band            VARCHAR(10)  NOT NULL,
    gender              CHAR(1)      NULL,
    segment             VARCHAR(30)  NOT NULL,   -- urmarit SCD
    county              VARCHAR(50)  NOT NULL,   -- urmarit SCD
    region              VARCHAR(50)  NOT NULL,   -- urmarit SCD
    city                VARCHAR(60)  NULL,
    acquisition_channel VARCHAR(50)  NOT NULL,
    activation_date     DATE         NULL,
    valid_from          DATE         NOT NULL,
    valid_to            DATE         NOT NULL,   -- 9999-12-31 pentru versiunea curenta
    is_current          BIT          NOT NULL,
    version             SMALLINT     NOT NULL,
    CONSTRAINT PK_DIM_CUSTOMER PRIMARY KEY CLUSTERED (customer_key),
    CONSTRAINT CK_DIM_CUSTOMER_validity CHECK (valid_to >= valid_from)
);
GO
CREATE NONCLUSTERED INDEX IX_DIM_CUSTOMER_current
    ON dbo.DIM_CUSTOMER (is_current)
    INCLUDE (customer_id, segment, region, age_band);
GO
CREATE NONCLUSTERED INDEX IX_DIM_CUSTOMER_pit
    ON dbo.DIM_CUSTOMER (customer_id, valid_from, valid_to)
    INCLUDE (customer_key);
GO


/*
   FACT_SUBSCRIPTION_MONTHLY
   Granularitate: un rand per client per luna.
   is_active este semi-aditiv, tenure_months este non-aditiv.
*/
IF OBJECT_ID('dbo.FACT_SUBSCRIPTION_MONTHLY', 'U') IS NOT NULL DROP TABLE dbo.FACT_SUBSCRIPTION_MONTHLY;
GO
CREATE TABLE dbo.FACT_SUBSCRIPTION_MONTHLY (
    fact_key            BIGINT        NOT NULL,

    date_key            INT           NOT NULL,
    customer_key        INT           NOT NULL,
    plan_key            INT           NOT NULL,
    geography_key       INT           NOT NULL,
    channel_key         INT           NOT NULL,

    -- Dimensiune degenerata; cheia corecta pentru clienti distincti.
    customer_id         INT           NOT NULL,

    -- Consum
    tenure_months       SMALLINT      NOT NULL,   -- non-aditiv
    data_used_gb        DECIMAL(12,3) NOT NULL,
    voice_used_min      INT           NOT NULL,
    sms_used            INT           NOT NULL,
    total_usage_units   DECIMAL(14,2) NOT NULL,

    -- Venit
    plan_fee            DECIMAL(10,2) NOT NULL,
    overage_amount      DECIMAL(10,2) NOT NULL DEFAULT 0,
    roaming_amount      DECIMAL(10,2) NOT NULL DEFAULT 0,
    discount_amount     DECIMAL(10,2) NOT NULL DEFAULT 0,
    total_revenue       DECIMAL(12,2) NOT NULL,
    gross_margin        DECIMAL(12,2) NOT NULL,

    -- Calitate serviciu
    complaint_count     SMALLINT      NOT NULL DEFAULT 0,
    complaints_resolved SMALLINT      NOT NULL DEFAULT 0,
    avg_resolution_days DECIMAL(6,2)  NOT NULL DEFAULT 0,

    is_active           BIT           NOT NULL,   -- semi-aditiv
    is_churn            BIT           NOT NULL,

    CONSTRAINT PK_FACT_SUB_MONTHLY PRIMARY KEY CLUSTERED (fact_key),

    -- Granularitatea impusa de baza de date.
    CONSTRAINT UQ_FACT_SUB_grain UNIQUE (date_key, customer_key),

    CONSTRAINT FK_FACT_date     FOREIGN KEY (date_key)      REFERENCES dbo.DIM_DATE(date_key),
    CONSTRAINT FK_FACT_customer FOREIGN KEY (customer_key)  REFERENCES dbo.DIM_CUSTOMER(customer_key),
    CONSTRAINT FK_FACT_plan     FOREIGN KEY (plan_key)      REFERENCES dbo.DIM_PLAN(plan_key),
    CONSTRAINT FK_FACT_geo      FOREIGN KEY (geography_key) REFERENCES dbo.DIM_GEOGRAPHY(geography_key),
    CONSTRAINT FK_FACT_channel  FOREIGN KEY (channel_key)   REFERENCES dbo.DIM_CHANNEL(channel_key),

    CONSTRAINT CK_FACT_revenue  CHECK (total_revenue >= 0),
    CONSTRAINT CK_FACT_usage    CHECK (data_used_gb >= 0 AND voice_used_min >= 0 AND sms_used >= 0)
);
GO


/*
   INDECSI PE TABELA DE FAPTE
   Columnstore pentru agregari; cheia primara clustered ramane pentru cautari punctuale.
*/
CREATE NONCLUSTERED COLUMNSTORE INDEX CSI_FACT_SUB_MONTHLY
    ON dbo.FACT_SUBSCRIPTION_MONTHLY (
        date_key, customer_key, plan_key, geography_key, channel_key,
        total_revenue, gross_margin, data_used_gb, voice_used_min,
        complaint_count, is_active, is_churn
    );
GO

CREATE NONCLUSTERED INDEX IX_FACT_date     ON dbo.FACT_SUBSCRIPTION_MONTHLY (date_key)      INCLUDE (total_revenue, is_active, is_churn);
GO
CREATE NONCLUSTERED INDEX IX_FACT_customer ON dbo.FACT_SUBSCRIPTION_MONTHLY (customer_key)  INCLUDE (total_revenue, tenure_months);
GO
CREATE NONCLUSTERED INDEX IX_FACT_plan     ON dbo.FACT_SUBSCRIPTION_MONTHLY (plan_key)      INCLUDE (total_revenue, is_churn);
GO
CREATE NONCLUSTERED INDEX IX_FACT_geo      ON dbo.FACT_SUBSCRIPTION_MONTHLY (geography_key) INCLUDE (total_revenue);
GO
CREATE NONCLUSTERED INDEX IX_FACT_channel  ON dbo.FACT_SUBSCRIPTION_MONTHLY (channel_key)   INCLUDE (total_revenue, is_churn);
GO


/*
   PARTITIONARE (productie)
   Comentat: necesita filegroup-uri. Partitionare lunara pe date_key.
   CREATE PARTITION FUNCTION PF_FACT_MONTH (INT)
   AS RANGE RIGHT FOR VALUES (20230101, 20230201, ... , 20251201);
   CREATE PARTITION SCHEME PS_FACT_MONTH
   AS PARTITION PF_FACT_MONTH ALL TO ([PRIMARY]);
*/
