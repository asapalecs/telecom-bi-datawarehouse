"""
TRANSFORM - construieste dimensiunile (cu DIM_CUSTOMER ca SCD Tip 2) si tabela
de fapte, apoi ruleaza verificarile de calitate.

Iesire (data/processed/): un CSV per tabela tinta.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from config import PROCESSED_DIR, RAW_DIR, END_DATE, START_DATE

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("transform")

# Cheie rezervata pentru "Necunoscut", ca un lookup esuat sa nu piarda randuri.
UNKNOWN_KEY = -1
UNKNOWN = "Necunoscut"

MONTH_NAMES = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie", 5: "Mai", 6: "Iunie",
    7: "Iulie", 8: "August", 9: "Septembrie", 10: "Octombrie", 11: "Noiembrie",
    12: "Decembrie",
}
DAY_NAMES = {
    1: "Luni", 2: "Marti", 3: "Miercuri", 4: "Joi", 5: "Vineri", 6: "Sambata",
    7: "Duminica",
}


def build_dim_date(start: date, end: date) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    df = pd.DataFrame({"full_date": days})

    df["date_key"] = df.full_date.dt.strftime("%Y%m%d").astype(int)
    df["year"] = df.full_date.dt.year
    df["quarter"] = df.full_date.dt.quarter
    df["month"] = df.full_date.dt.month
    df["month_name"] = df.month.map(MONTH_NAMES)
    df["week_of_year"] = df.full_date.dt.isocalendar().week.astype(int)
    df["day_of_month"] = df.full_date.dt.day
    df["day_of_week"] = df.full_date.dt.dayofweek + 1        # 1 = luni
    df["day_name"] = df.day_of_week.map(DAY_NAMES)
    df["is_weekend"] = (df.full_date.dt.dayofweek >= 5).astype(int)
    df["is_month_end"] = df.full_date.dt.is_month_end.astype(int)
    df["year_month"] = df.full_date.dt.strftime("%Y-%m")

    df["full_date"] = df.full_date.dt.strftime("%Y-%m-%d")
    return df[[
        "date_key", "full_date", "year", "quarter", "month", "month_name",
        "week_of_year", "day_of_month", "day_of_week", "day_name",
        "is_weekend", "is_month_end", "year_month",
    ]]


def build_dim_plan(plans: pd.DataFrame) -> pd.DataFrame:
    df = plans.copy()
    df.insert(0, "plan_key", range(1, len(df) + 1))

    df["price_tier"] = pd.cut(
        df.monthly_fee,
        bins=[0, 10, 20, 35, np.inf],
        labels=["Economic", "Mediu", "Premium", "Top"],
    ).astype(str)

    df["is_contract"] = (df.contract_months > 0).astype(int)

    unknown = {c: UNKNOWN for c in df.columns}
    unknown.update({
        "plan_key": UNKNOWN_KEY, "plan_id": UNKNOWN_KEY, "monthly_fee": 0.0,
        "data_allowance_gb": 0, "voice_allowance_min": 0, "sms_allowance": 0,
        "contract_months": 0, "is_contract": 0,
    })
    return pd.concat([pd.DataFrame([unknown]), df], ignore_index=True)


def build_dim_geography(customers: pd.DataFrame, changes: pd.DataFrame) -> pd.DataFrame:
    """Toate judetele, inclusiv cele in care s-au mutat clientii."""
    pairs = customers[["county", "region"]]
    if not changes.empty and "new_county" in changes.columns:
        moved = changes[["new_county", "new_region"]].rename(
            columns={"new_county": "county", "new_region": "region"}
        )
        pairs = pd.concat([pairs, moved], ignore_index=True)

    df = pairs.dropna().drop_duplicates().sort_values("county").reset_index(drop=True)
    df = df[df.county.astype(str).str.len() > 0]
    df.insert(0, "geography_key", range(1, len(df) + 1))

    df["is_metro"] = (df.region == "Bucuresti-Ilfov").astype(int)

    unknown = pd.DataFrame([{
        "geography_key": UNKNOWN_KEY, "county": UNKNOWN,
        "region": UNKNOWN, "is_metro": 0,
    }])
    return pd.concat([unknown, df], ignore_index=True)


def build_dim_channel(customers: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({"channel_name": sorted(customers.acquisition_channel.unique())})
    df.insert(0, "channel_key", range(1, len(df) + 1))
    df["channel_type"] = np.where(
        df.channel_name.isin(["Online"]), "Digital", "Fizic"
    )
    unknown = pd.DataFrame([{
        "channel_key": UNKNOWN_KEY, "channel_name": UNKNOWN, "channel_type": UNKNOWN,
    }])
    return pd.concat([unknown, df], ignore_index=True)


def build_dim_customer(customers: pd.DataFrame, changes: pd.DataFrame) -> pd.DataFrame:
    """DIM_CUSTOMER ca SCD Tip 2: o versiune noua la fiecare schimbare,
    cu valid_from/valid_to inclusive si is_current pe ultima versiune."""
    changes = changes[changes.customer_id != 0] if not changes.empty else changes
    change_map: dict[int, list] = {}
    if not changes.empty:
        for _, r in changes.iterrows():
            change_map.setdefault(int(r.customer_id), []).append(r)

    FAR_FUTURE = "9999-12-31"
    rows, key = [], 0

    for _, c in customers.iterrows():
        cid = int(c.customer_id)
        base = {
            "customer_id": cid,
            "full_name": c.full_name,
            "birth_date": c.birth_date,
            "gender": c.gender,
            "city": c.city,
            "activation_date": c.activation_date,
            "acquisition_channel": c.acquisition_channel,
        }

        try:
            age = (date.fromisoformat(END_DATE) - date.fromisoformat(str(c.birth_date))).days // 365
        except (ValueError, TypeError):
            age = 0
        base["age_band"] = (
            "18-24" if age < 25 else "25-34" if age < 35 else
            "35-49" if age < 50 else "50-64" if age < 65 else "65+"
        )

        versions = change_map.get(cid, [])
        current_from = str(c.activation_date)
        segment, county, region = c.segment, c.county, c.region
        version_no = 1

        for ch in versions:
            change_date = str(ch.change_date)
            valid_to = (date.fromisoformat(change_date) - timedelta(days=1)).isoformat()

            key += 1
            rows.append({
                **base, "customer_key": key, "segment": segment,
                "county": county, "region": region,
                "valid_from": current_from, "valid_to": valid_to,
                "is_current": 0, "version": version_no,
            })

            segment, county, region = ch.new_segment, ch.new_county, ch.new_region
            current_from = change_date
            version_no += 1

        key += 1
        rows.append({
            **base, "customer_key": key, "segment": segment,
            "county": county, "region": region,
            "valid_from": current_from, "valid_to": FAR_FUTURE,
            "is_current": 1, "version": version_no,
        })

    df = pd.DataFrame(rows)

    unknown = {c: UNKNOWN for c in df.columns}
    unknown.update({
        "customer_key": UNKNOWN_KEY, "customer_id": UNKNOWN_KEY,
        # NULL: coloane DATE / CHAR(1) in DDL.
        "birth_date": None, "gender": None, "activation_date": None,
        "valid_from": "1900-01-01", "valid_to": FAR_FUTURE,
        "is_current": 1, "version": 1,
    })
    df = pd.concat([pd.DataFrame([unknown]), df], ignore_index=True)

    ordered = [
        "customer_key", "customer_id", "full_name", "birth_date", "age_band",
        "gender", "segment", "county", "region", "city", "acquisition_channel",
        "activation_date", "valid_from", "valid_to", "is_current", "version",
    ]
    return df[ordered]


def build_fact(
    subs: pd.DataFrame, complaints: pd.DataFrame, dim_customer: pd.DataFrame,
    dim_plan: pd.DataFrame, dim_geo: pd.DataFrame, dim_channel: pd.DataFrame,
    customers: pd.DataFrame,
) -> pd.DataFrame:
    """Granularitate: un rand per client per luna."""
    f = subs.copy()
    f["month"] = pd.to_datetime(f.month)
    f["date_key"] = f.month.dt.strftime("%Y%m01").astype(int)

    dc = dim_customer[dim_customer.customer_key != UNKNOWN_KEY].copy()
    dc["vf"] = pd.to_datetime(dc.valid_from)
    dc["vt"] = pd.to_datetime(dc.valid_to.replace("9999-12-31", "2262-04-10"))

    rows_in = len(f)

    # Suprapunere de interval la nivel de luna: o comparatie directa
    # `month >= valid_from` ar pierde prima luna a fiecarui client.
    f["month_start"] = f.month
    f["month_end"] = f.month + pd.offsets.MonthEnd(0)

    f = f.merge(
        dc[["customer_key", "customer_id", "vf", "vt"]],
        on="customer_id", how="left",
    )
    overlaps = (f.vf <= f.month_end) & (f.vt >= f.month_start)
    f = f[overlaps | f.customer_key.isna()].copy()

    # Luna cu schimbare se atribuie versiunii valabile la final de luna.
    f = (f.sort_values(["customer_id", "month", "vf"])
           .drop_duplicates(subset=["customer_id", "month"], keep="last"))

    f["customer_key"] = f.customer_key.fillna(UNKNOWN_KEY).astype(int)
    f = f.drop(columns=["vf", "vt", "month_start", "month_end"])

    if len(f) != rows_in:
        raise ValueError(
            f"Numarul de randuri s-a schimbat la rezolvarea dimensiunilor: "
            f"{rows_in} intrare, {len(f)} iesire. Un join pierde sau dubleaza randuri."
        )

    f = f.merge(dim_plan[["plan_key", "plan_id"]], on="plan_id", how="left")
    f = f.merge(dim_geo[["geography_key", "county"]], on="county", how="left")

    chan = customers[["customer_id", "acquisition_channel"]]
    f = f.merge(chan, on="customer_id", how="left")
    f = f.merge(
        dim_channel[["channel_key", "channel_name"]],
        left_on="acquisition_channel", right_on="channel_name", how="left",
    )

    for col in ["plan_key", "geography_key", "channel_key"]:
        f[col] = f[col].fillna(UNKNOWN_KEY).astype(int)

    if not complaints.empty:
        c = complaints.copy()
        c["month"] = pd.to_datetime(c.complaint_date).dt.to_period("M").dt.to_timestamp()
        agg = c.groupby(["customer_id", "month"]).agg(
            complaint_count=("complaint_id", "count"),
            avg_resolution_days=("resolution_days", "mean"),
            complaints_resolved=("resolved", "sum"),
        ).reset_index()
        f = f.merge(agg, on=["customer_id", "month"], how="left")
    else:
        f["complaint_count"] = 0
        f["avg_resolution_days"] = 0.0
        f["complaints_resolved"] = 0

    f["complaint_count"] = f.complaint_count.fillna(0).astype(int)
    f["avg_resolution_days"] = f.avg_resolution_days.fillna(0).round(2)
    f["complaints_resolved"] = f.complaints_resolved.fillna(0).astype(int)

    f["total_usage_units"] = (
        f.data_used_gb * 1000 + f.voice_used_min + f.sms_used * 0.5
    ).round(2)

    # Marja de contributie standard de 68%.
    f["gross_margin"] = (f.total_revenue * 0.68).round(2)

    f.insert(0, "fact_key", range(1, len(f) + 1))

    ordered = [
        "fact_key", "date_key", "customer_key", "plan_key", "geography_key",
        "channel_key",
        "customer_id",  # dimensiune degenerata
        "tenure_months", "data_used_gb", "voice_used_min", "sms_used",
        "total_usage_units", "plan_fee", "overage_amount", "roaming_amount",
        "discount_amount", "total_revenue", "gross_margin",
        "complaint_count", "complaints_resolved", "avg_resolution_days",
        "is_active", "is_churn",
    ]
    return f[ordered]


def quality_checks(fact: pd.DataFrame, dims: dict[str, pd.DataFrame]) -> list[str]:
    """Returneaza lista invariantilor incalcati."""
    problems: list[str] = []

    if fact.fact_key.duplicated().any():
        problems.append("FACT: valori fact_key duplicate")

    if fact[["date_key", "customer_key"]].duplicated().any():
        n = int(fact[["date_key", "customer_key"]].duplicated().sum())
        problems.append(f"FACT: {n} randuri incalca granularitatea client-luna")

    if (fact.total_revenue < 0).any():
        problems.append(f"FACT: {int((fact.total_revenue < 0).sum())} randuri cu venit negativ")

    for measure in ["data_used_gb", "voice_used_min", "sms_used"]:
        if (fact[measure] < 0).any():
            problems.append(f"FACT: {measure} negativ")

    if not fact.is_churn.isin([0, 1]).all():
        problems.append("FACT: is_churn nu este strict 0/1")

    fk_map = {
        "customer_key": ("dim_customer", "customer_key"),
        "plan_key": ("dim_plan", "plan_key"),
        "geography_key": ("dim_geography", "geography_key"),
        "channel_key": ("dim_channel", "channel_key"),
        "date_key": ("dim_date", "date_key"),
    }
    for fk, (dim_name, pk) in fk_map.items():
        valid = set(dims[dim_name][pk])
        orphans = int((~fact[fk].isin(valid)).sum())
        if orphans:
            problems.append(f"FACT: {orphans} randuri cu {fk} nerezolvabil")

    # Prea multe randuri pe "Necunoscut" indica lookup-uri esuate.
    for fk in ["customer_key", "plan_key", "geography_key", "channel_key"]:
        rate = (fact[fk] == UNKNOWN_KEY).mean()
        if rate > 0.01:
            problems.append(f"FACT: {rate:.1%} din randuri cad pe {UNKNOWN} la {fk}")

    dc = dims["dim_customer"]
    dc = dc[dc.customer_key != UNKNOWN_KEY]
    multi = dc[dc.is_current == 1].groupby("customer_id").size()
    if (multi > 1).any():
        problems.append(f"DIM_CUSTOMER: {int((multi > 1).sum())} clienti au mai mult de un rand curent")

    return problems


def main() -> None:
    log.info("Citire extrase brute...")
    customers = pd.read_csv(RAW_DIR / "customers.csv")
    plans = pd.read_csv(RAW_DIR / "plans.csv")
    subs = pd.read_csv(RAW_DIR / "subscriptions.csv")
    complaints = pd.read_csv(RAW_DIR / "complaints.csv")
    changes = pd.read_csv(RAW_DIR / "customer_changes.csv")

    log.info("Construire dimensiuni...")
    dim_date = build_dim_date(date.fromisoformat(START_DATE), date.fromisoformat(END_DATE))
    dim_plan = build_dim_plan(plans)
    dim_geo = build_dim_geography(customers, changes)
    dim_channel = build_dim_channel(customers)
    dim_customer = build_dim_customer(customers, changes)

    scd_versions = len(dim_customer) - 1 - len(customers)
    log.info("  dim_date      %6d randuri", len(dim_date))
    log.info("  dim_plan      %6d randuri", len(dim_plan))
    log.info("  dim_geography %6d randuri", len(dim_geo))
    log.info("  dim_channel   %6d randuri", len(dim_channel))
    log.info("  dim_customer  %6d randuri  (%d clienti, %d versiuni SCD suplimentare)",
             len(dim_customer), len(customers), scd_versions)

    log.info("Construire tabela de fapte...")
    fact = build_fact(subs, complaints, dim_customer, dim_plan, dim_geo,
                      dim_channel, customers)
    log.info("  fact_subscription_monthly %6d randuri", len(fact))

    dims = {
        "dim_date": dim_date, "dim_plan": dim_plan, "dim_geography": dim_geo,
        "dim_channel": dim_channel, "dim_customer": dim_customer,
    }

    log.info("Verificari de calitate a datelor...")
    problems = quality_checks(fact, dims)
    if problems:
        for p in problems:
            log.error("  ESEC  %s", p)
        raise SystemExit("Verificarile de calitate au esuat - nu se scrie nimic.")
    log.info("  toate verificarile au trecut")

    for name, df in {**dims, "fact_subscription_monthly": fact}.items():
        df.to_csv(PROCESSED_DIR / f"{name}.csv", index=False)
    log.info("Transform finalizat -> %s", PROCESSED_DIR)


if __name__ == "__main__":
    main()
