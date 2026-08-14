"""Collecte des enjeux : masse des pools et montants par combinaison.

Volontairement séparé de `collecte.py`. Rejouer le backfill complet pour
ajouter ces deux appels re-téléchargerait 2,8 millions de participants déjà
en base — dix-huit heures de travail pour rien, et autant de charge inutile
sur l'API du PMU. Ce module ne lit que les courses déjà connues et n'ajoute
que ce qui manque.

Le journal utilise `source = 'PMU_ENJEUX'` : la reprise de cette collecte est
alors indépendante de celle des courses, et une date peut être complète pour
l'une et pas pour l'autre.

    python -m collector.enjeux --debut 2013-03-01 --fin 2013-12-31
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta

from . import parse
from .db import Db
from .pmu_api import PREMIERE_DATE, PmuApi

log = logging.getLogger("enjeux")

SOURCE = "PMU_ENJEUX"


def collecter_journee(api: PmuApi, db: Db, d: date) -> dict:
    t0 = time.monotonic()
    stats = {"nb_courses": 0, "nb_masses": 0, "nb_combinaisons": 0}

    courses = db.courses_du_jour(d)
    if not courses:
        db.journaliser(d, "VIDE", source=SOURCE,
                       duree_ms=int((time.monotonic() - t0) * 1000))
        return stats

    for (num_reunion, num_course), (course_id, _depart) in sorted(courses.items()):
        try:
            masses = api.masse_enjeu(d, num_reunion, num_course)
            combis = api.combinaisons(d, num_reunion, num_course)
        except Exception as e:                           # noqa: BLE001
            # Une course qui refuse de répondre ne doit pas condamner la
            # journée : les autres sont indépendantes.
            log.warning("%s R%sC%s : %s", d, num_reunion, num_course, e)
            continue

        stats["nb_courses"] += 1
        if masses:
            stats["nb_masses"] += db.upsert_masse_enjeu(
                parse.parse_masse_enjeu(masses, course_id))
        if combis:
            stats["nb_combinaisons"] += db.upsert_enjeux_combinaisons(
                parse.parse_combinaisons(combis, course_id))

    db.commit()
    db.journaliser(d, "OK", source=SOURCE,
                   duree_ms=int((time.monotonic() - t0) * 1000),
                   nb_courses=stats["nb_courses"])
    log.info("%s : %d courses, %d masses, %d combinaisons (%.1fs)",
             d, stats["nb_courses"], stats["nb_masses"],
             stats["nb_combinaisons"], time.monotonic() - t0)
    return stats


def plage(debut: date, fin: date):
    d = debut
    while d <= fin:
        yield d
        d += timedelta(days=1)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collecte des enjeux PMU")
    p.add_argument("--debut", required=True, type=date.fromisoformat)
    p.add_argument("--fin", required=True, type=date.fromisoformat)
    p.add_argument("--force", action="store_true")
    p.add_argument("--intervalle", type=float, default=0.5)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        stream=sys.stdout)

    debut = max(args.debut, PREMIERE_DATE)
    api = PmuApi(intervalle_min=args.intervalle)

    with Db() as db:
        deja = set() if args.force else db.dates_deja_collectees(SOURCE)
        dates = [d for d in plage(debut, args.fin) if d not in deja]
        log.info("Shard %s -> %s : %d jours à traiter", debut, args.fin, len(dates))

        echecs = 0
        for i, d in enumerate(dates, 1):
            try:
                collecter_journee(api, db, d)
            except Exception as e:                       # noqa: BLE001
                echecs += 1
                log.exception("%s : échec", d)
                db.rollback()
                db.journaliser(d, "ERREUR", source=SOURCE,
                               erreur=f"{type(e).__name__}: {e}")
            if i % 25 == 0:
                log.info("… %d/%d", i, len(dates))

        log.info("Shard terminé : %d jours, %d échecs", len(dates), echecs)

    return 1 if dates and echecs > len(dates) * 0.1 else 0


if __name__ == "__main__":
    raise SystemExit(main())
