"""Collecte quotidienne.

Repasse volontairement sur les jours précédents : au moment où une course est
collectée pour la première fois, elle n'a ni arrivée ni rapports définitifs.
C'est le second passage qui les récupère. `--recul 2` couvre les arrivées
tardives et les rapports rectifiés après enquête des commissaires.

    python -m collector.daily --recul 2
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from .collecte import collecter_journee
from .db import Db
from .pmu_api import PmuApi

log = logging.getLogger("daily")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collecte quotidienne PMU")
    p.add_argument("--recul", type=int, default=2,
                   help="nombre de jours en arrière à recollecter (défaut : 2)")
    p.add_argument("--avance", type=int, default=1,
                   help="nombre de jours en avant (programmes publiés à J+3)")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )

    aujourdhui = date.today()
    dates = [
        aujourdhui + timedelta(days=n)
        for n in range(-args.recul, args.avance + 1)
    ]

    api = PmuApi()
    echecs = 0
    with Db() as db:
        for d in dates:
            try:
                collecter_journee(api, db, d)
            except Exception as e:                       # noqa: BLE001
                echecs += 1
                log.exception("%s : échec", d)
                db.conn.rollback()
                db.journaliser(d, "ERREUR", erreur=f"{type(e).__name__}: {e}")

    return 1 if echecs else 0


if __name__ == "__main__":
    raise SystemExit(main())
