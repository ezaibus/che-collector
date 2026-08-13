"""Backfill historique — un shard = une plage de dates.

Découpé par année dans le workflow GitHub Actions : un job dépasserait sinon
la limite de 6 h. Les shards sont indépendants (aucune date partagée) et
peuvent tourner en parallèle sans se marcher dessus.

    python -m collector.backfill --debut 2013-03-01 --fin 2013-12-31
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from .collecte import collecter_journee
from .db import Db
from .pmu_api import PREMIERE_DATE, PmuApi

log = logging.getLogger("backfill")


def plage(debut: date, fin: date):
    d = debut
    while d <= fin:
        yield d
        d += timedelta(days=1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Backfill de l'historique PMU")
    p.add_argument("--debut", required=True, type=date.fromisoformat)
    p.add_argument("--fin", required=True, type=date.fromisoformat)
    p.add_argument("--force", action="store_true",
                   help="recollecter même les dates déjà marquées OK/VIDE")
    p.add_argument("--intervalle", type=float, default=0.35,
                   help="délai minimum entre deux appels API, en secondes")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )

    debut = max(args.debut, PREMIERE_DATE)
    if debut != args.debut:
        log.warning(
            "Début ramené à %s : l'API ne sert rien avant cette date.", PREMIERE_DATE
        )

    api = PmuApi(intervalle_min=args.intervalle)
    with Db() as db:
        deja = set() if args.force else db.dates_deja_collectees()
        dates = [d for d in plage(debut, args.fin) if d not in deja]
        total = len(dates)
        log.info(
            "Shard %s -> %s : %d jours à traiter (%d déjà collectés)",
            debut, args.fin, total, (args.fin - debut).days + 1 - total,
        )

        echecs = 0
        for i, d in enumerate(dates, 1):
            try:
                collecter_journee(api, db, d)
            except Exception as e:                       # noqa: BLE001
                echecs += 1
                log.exception("%s : échec", d)
                db.rollback()
                # On journalise l'échec pour pouvoir cibler une reprise, et on
                # continue : un jour en erreur ne doit pas condamner le shard.
                db.journaliser(d, "ERREUR", erreur=f"{type(e).__name__}: {e}")
            if i % 25 == 0:
                log.info("… %d/%d (%.0f %%)", i, total, 100 * i / total)

        log.info("Shard terminé : %d jours, %d échecs", total, echecs)

    # Un shard qui échoue partout doit faire échouer le job ; quelques trous
    # ponctuels (API indisponible ce jour-là) ne doivent pas.
    return 1 if total and echecs > total * 0.1 else 0


if __name__ == "__main__":
    raise SystemExit(main())
