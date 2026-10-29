"""
Orchestrator ETL - ruleaza extract, transform si load, in aceasta ordine.

    python etl/main.py                # pipeline complet
    python etl/main.py --skip-extract # refoloseste fisierele brute existente
    python etl/main.py --stage load   # o singura etapa
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import config
import extract
import load
import transform

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")

STAGES = {
    "extract": extract.main,
    "transform": transform.main,
    "load": load.main,
}


def run_stage(name: str) -> float:
    log.info("")
    log.info("=" * 66)
    log.info("ETAPA: %s", name.upper())
    log.info("=" * 66)
    t0 = time.perf_counter()
    STAGES[name]()
    elapsed = time.perf_counter() - t0
    log.info("Etapa '%s' finalizata in %.2fs", name, elapsed)
    return elapsed


def main() -> int:
    p = argparse.ArgumentParser(description="Pipeline ETL pentru depozitul de date telecom")
    p.add_argument("--stage", choices=list(STAGES),
                   help="Ruleaza o singura etapa in locul pipeline-ului complet")
    p.add_argument("--skip-extract", action="store_true",
                   help="Refoloseste fisierele brute existente din data/raw")
    args = p.parse_args()

    log.info("Depozit de date telecom - pipeline ETL")
    log.info("-" * 66)
    for line in config.describe().splitlines():
        log.info("  %s", line)

    stages = [args.stage] if args.stage else list(STAGES)
    if args.skip_extract and "extract" in stages and not args.stage:
        stages.remove("extract")
        log.info("  Extract omis; se refoloseste %s", config.RAW_DIR)

    timings: dict[str, float] = {}
    try:
        for name in stages:
            timings[name] = run_stage(name)
    except (Exception, SystemExit) as exc:
        # Cod de iesire nenul, ca un scheduler sa vada esecul.
        log.error("")
        log.error("PIPELINE ESUAT in etapa '%s': %s", name, exc)
        return 1

    log.info("")
    log.info("=" * 66)
    log.info("PIPELINE FINALIZAT")
    for name, secs in timings.items():
        log.info("  %-12s %6.2fs", name, secs)
    log.info("  %-12s %6.2fs", "TOTAL", sum(timings.values()))
    log.info("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
