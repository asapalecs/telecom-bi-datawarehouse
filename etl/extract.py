"""
EXTRACT - genereaza fisierele sursa brute (date sintetice realiste cu Faker).

Iesire (data/raw/):
    customers.csv          un rand per abonat
    plans.csv              catalogul de planuri tarifare
    subscriptions.csv      un rand per abonat-luna
    complaints.csv         un rand per reclamatie
    customer_changes.csv   schimbari de segment/regiune (SCD Tip 2)
"""

from __future__ import annotations

import csv
import logging
import random
import unicodedata
from datetime import date, timedelta

import numpy as np
from faker import Faker

from config import END_DATE, N_CUSTOMERS, RANDOM_SEED, RAW_DIR, START_DATE

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("extract")

fake = Faker("ro_RO")
Faker.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)


# Judete grupate pe cele opt regiuni de dezvoltare.
COUNTIES = {
    "Bucuresti": "Bucuresti-Ilfov", "Ilfov": "Bucuresti-Ilfov",
    "Cluj": "Nord-Vest", "Bihor": "Nord-Vest", "Maramures": "Nord-Vest",
    "Timis": "Vest", "Arad": "Vest", "Hunedoara": "Vest",
    "Brasov": "Centru", "Sibiu": "Centru", "Mures": "Centru",
    "Iasi": "Nord-Est", "Suceava": "Nord-Est", "Bacau": "Nord-Est",
    "Constanta": "Sud-Est", "Galati": "Sud-Est", "Braila": "Sud-Est",
    "Prahova": "Sud-Muntenia", "Arges": "Sud-Muntenia", "Dambovita": "Sud-Muntenia",
    "Dolj": "Sud-Vest", "Gorj": "Sud-Vest", "Valcea": "Sud-Vest",
}

PLANS = [
    # plan_id, nume, familie, abonament, date_gb, minute, sms, luni_contract, factor_churn
    (1,  "Prepaid Start",     "Preplatit",  5.00,   2,   100,  50,  0, 3.20),
    (2,  "Prepaid Plus",      "Preplatit",  9.00,   6,   300, 100,  0, 2.60),
    (3,  "Mobil S",           "Abonament", 12.00,  10,  500, 200, 12, 1.10),
    (4,  "Mobil M",           "Abonament", 18.00,  30, 1000, 500, 24, 0.75),
    (5,  "Mobil L",           "Abonament", 25.00,  60, 2000, 999, 24, 0.55),
    (6,  "Mobil Nelimitat",   "Abonament", 35.00, 200, 9999, 999, 24, 0.40),
    (7,  "Familie 2",         "Familie",   30.00,  50, 2000, 999, 24, 0.45),
    (8,  "Familie 4",         "Familie",   48.00, 120, 9999, 999, 24, 0.35),
    (9,  "Business Basic",    "Business",  22.00,  40, 2000, 999, 24, 0.50),
    (10, "Business Pro",      "Business",  45.00, 150, 9999, 999, 24, 0.30),
]

SEGMENTS = ["Persoane fizice", "Tineri", "Familie", "IMM", "Corporate"]
CHANNELS = ["Magazin", "Online", "Televanzari", "Partener", "Agent teren"]
COMPLAINT_CATEGORIES = [
    "Acoperire retea", "Disputa facturare", "Viteza date",
    "Relatii clienti", "Problema terminal", "Roaming",
]


def fara_diacritice(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def month_range(start: date, end: date) -> list[date]:
    months, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        months.append(cur)
        cur = date(cur.year + 1, 1, 1) if cur.month == 12 else date(cur.year, cur.month + 1, 1)
    return months


COMPLAINT_FIELDS = [
    "complaint_id", "customer_id", "complaint_date", "category",
    "resolution_days", "resolved", "satisfaction_score",
]


def write_csv(name: str, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    path = RAW_DIR / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames or list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    log.info("%-22s %7d randuri", name, len(rows))


def generate_plans() -> list[dict]:
    return [
        {
            "plan_id": p[0], "plan_name": p[1], "plan_family": p[2],
            "monthly_fee": p[3], "data_allowance_gb": p[4],
            "voice_allowance_min": p[5], "sms_allowance": p[6],
            "contract_months": p[7],
        }
        for p in PLANS
    ]


def generate_customers(start: date, end: date) -> list[dict]:
    rows = []
    span_days = (end - start).days

    for cid in range(1, N_CUSTOMERS + 1):
        # Activari mai dese la inceput, ca baza sa creasca in timp.
        activation = start + timedelta(days=int(np.random.beta(1.6, 2.4) * span_days))
        county = random.choice(list(COUNTIES))

        rows.append({
            "customer_id": cid,
            "full_name": fara_diacritice(fake.name()),
            "birth_date": fake.date_of_birth(minimum_age=18, maximum_age=80).isoformat(),
            "gender": random.choice(["M", "F"]),
            "segment": random.choices(
                SEGMENTS, weights=[45, 18, 20, 12, 5], k=1
            )[0],
            "county": county,
            "region": COUNTIES[county],
            "city": fara_diacritice(fake.city()),
            "acquisition_channel": random.choices(
                CHANNELS, weights=[35, 30, 15, 15, 5], k=1
            )[0],
            "activation_date": activation.isoformat(),
            "plan_id": random.choices(
                [p[0] for p in PLANS],
                weights=[14, 12, 15, 18, 12, 8, 7, 5, 5, 4], k=1,
            )[0],
        })
    return rows


def generate_subscriptions_and_complaints(
    customers: list[dict], start: date, end: date
) -> tuple[list[dict], list[dict], list[dict]]:
    """Parcurge fiecare client luna cu luna; churn-ul e un hazard lunar
    dependent de plan, vechime, contract si reclamatii."""
    plan_by_id = {p[0]: p for p in PLANS}
    months = month_range(start, end)

    subscriptions: list[dict] = []
    complaints: list[dict] = []
    changes: list[dict] = []
    complaint_id = 1

    for cust in customers:
        plan = plan_by_id[cust["plan_id"]]
        _, _, _, fee, data_gb, voice_min, sms_allow, contract_m, churn_factor = plan

        activation = date.fromisoformat(cust["activation_date"])
        active_months = [m for m in months if m >= date(activation.year, activation.month, 1)]

        complaints_to_date = 0
        churned = False
        segment = cust["segment"]
        county = cust["county"]

        # 8% dintre clienti isi schimba segmentul/judetul (sursa pentru SCD Tip 2).
        change_month = None
        if random.random() < 0.08 and len(active_months) > 6:
            change_month = random.choice(active_months[3:-1])

        for tenure, month in enumerate(active_months):
            if churned:
                break

            if change_month and month == change_month:
                new_segment = random.choice([s for s in SEGMENTS if s != segment])
                new_county = random.choice([c for c in COUNTIES if c != county])
                changes.append({
                    "customer_id": cust["customer_id"],
                    "change_date": month.isoformat(),
                    "old_segment": segment, "new_segment": new_segment,
                    "old_county": county, "new_county": new_county,
                    "old_region": COUNTIES[county], "new_region": COUNTIES[new_county],
                })
                segment, county = new_segment, new_county

            # Consum lognormal in jurul pachetului inclus.
            data_used = max(0.0, float(np.random.lognormal(np.log(max(data_gb, 1) * 0.60), 0.42)))
            voice_used = max(0, int(np.random.lognormal(np.log(max(voice_min, 1) * 0.45), 0.50)))
            sms_used = max(0, int(np.random.lognormal(np.log(max(sms_allow, 1) * 0.30), 0.70)))

            # Calibrat pentru un ARPU mediu de ~30 RON.
            overage = 0.0
            if data_used > data_gb:
                overage += (data_used - data_gb) * 0.45      # RON per GB suplimentar
            if voice_used > voice_min:
                overage += (voice_used - voice_min) * 0.06   # RON per minut suplimentar
            roaming = round(random.uniform(4, 60), 2) if random.random() < 0.035 else 0.0
            discount = round(fee * random.choice([0.10, 0.15, 0.25]), 2) if random.random() < 0.12 else 0.0

            revenue = round(fee + overage + roaming - discount, 2)

            # ~4%/luna, mai mult pentru consumatorii mari de date.
            p_complaint = 0.040 + (0.030 if data_used > data_gb * 1.5 else 0.0)
            n_complaints = np.random.binomial(1, min(p_complaint, 0.5))
            for _ in range(n_complaints):
                complaints_to_date += 1
                opened = month + timedelta(days=random.randint(0, 27))
                resolution_days = max(0, int(np.random.gamma(2.0, 1.6)))
                complaints.append({
                    "complaint_id": complaint_id,
                    "customer_id": cust["customer_id"],
                    "complaint_date": opened.isoformat(),
                    "category": random.choices(
                        COMPLAINT_CATEGORIES, weights=[28, 22, 18, 14, 10, 8], k=1
                    )[0],
                    "resolution_days": resolution_days,
                    "resolved": 1 if resolution_days <= 14 else 0,
                    "satisfaction_score": random.randint(1, 5),
                })
                complaint_id += 1

            # Calibrat pentru un churn lunar mediu de 1.5-2%.
            base_hazard = 0.013 * churn_factor
            tenure_mult = 1.9 if tenure < 3 else (1.25 if tenure < 12 else 0.85)
            contract_mult = 0.12 if tenure < contract_months_of(contract_m) else 1.0
            complaint_mult = 1.0 + 0.42 * complaints_to_date

            hazard = min(base_hazard * tenure_mult * contract_mult * complaint_mult, 0.45)
            is_churn = 1 if random.random() < hazard else 0

            subscriptions.append({
                "customer_id": cust["customer_id"],
                "month": month.isoformat(),
                "plan_id": cust["plan_id"],
                "segment": segment,
                "county": county,
                "region": COUNTIES[county],
                "tenure_months": tenure,
                "data_used_gb": round(data_used, 3),
                "voice_used_min": voice_used,
                "sms_used": sms_used,
                "plan_fee": fee,
                "overage_amount": round(overage, 2),
                "roaming_amount": roaming,
                "discount_amount": discount,
                "total_revenue": revenue,
                "complaints_in_month": int(n_complaints),
                "is_churn": is_churn,
                "is_active": 0 if is_churn else 1,
            })

            if is_churn:
                churned = True

    return subscriptions, complaints, changes


def contract_months_of(contract_m: int) -> int:
    return contract_m


def main() -> None:
    start = date.fromisoformat(START_DATE)
    end = date.fromisoformat(END_DATE)

    log.info("Generare extrase sursa (%d clienti, %s - %s)...",
             N_CUSTOMERS, START_DATE, END_DATE)

    plans = generate_plans()
    customers = generate_customers(start, end)
    subs, complaints, changes = generate_subscriptions_and_complaints(customers, start, end)

    write_csv("plans.csv", plans)
    write_csv("customers.csv", customers)
    write_csv("subscriptions.csv", subs)
    write_csv("complaints.csv", complaints, COMPLAINT_FIELDS)
    write_csv("customer_changes.csv", changes or [{
        "customer_id": 0, "change_date": "", "old_segment": "", "new_segment": "",
        "old_county": "", "new_county": "", "old_region": "", "new_region": "",
    }])

    churn_total = sum(r["is_churn"] for r in subs)
    log.info("Control: %d abonat-luni, %d evenimente churn (%.2f%% lunar)",
             len(subs), churn_total, 100 * churn_total / max(len(subs), 1))
    log.info("Extract finalizat -> %s", RAW_DIR)


if __name__ == "__main__":
    main()
