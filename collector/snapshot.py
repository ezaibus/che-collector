"""Relevé des cotes en direct, avant le départ.

C'est la seule donnée du projet qui ne se rattrape pas. L'historique PMU ne
conserve que deux points par cheval : la cote de référence (~H-30) et la cote
finale (~H+2, donc après le départ — inutilisable en entrée de modèle). Toute
la trajectoire entre les deux est perdue si personne ne la relève sur le
moment.

Or c'est là que se trouve l'information. Exemple relevé le 13/08/2026 à
Deauville : I WILL BE KING cotait 34,0 à H-30 et 5,6 au départ — il a gagné.
L'argent est arrivé dans les trente dernières minutes.

Conçu pour tourner en job long (GitHub Actions plafonne à 6 h) plutôt qu'en
cron : le cron GitHub descend à 5 min au mieux et se fait décaler sous charge,
ce qui est trop grossier et trop incertain ici.

    python -m collector.snapshot --duree-min 350 --intervalle-sec 60
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

from .collecte import collecter_journee
from .db import Db
from .pmu_api import PmuApi

log = logging.getLogger("snapshot")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Relevé des cotes avant départ")
    p.add_argument("--duree-min", type=float, default=350,
                   help="durée de vie du job en minutes (limite GitHub : 360)")
    p.add_argument("--intervalle-sec", type=float, default=60,
                   help="période entre deux relevés")
    p.add_argument("--fenetre-min", type=float, default=45,
                   help="on relève une course à partir de H-fenetre")
    p.add_argument("--marge-apres-min", type=float, default=2,
                   help="on continue un peu après l'heure théorique (départs décalés)")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )

    api = PmuApi(intervalle_min=0.25)
    fin_job = time.monotonic() + args.duree_min * 60
    aujourdhui = date.today()

    with Db() as db:
        # Les courses doivent exister en base pour qu'un snapshot puisse les
        # référencer. On garantit ça une fois, au démarrage.
        try:
            collecter_journee(api, db, aujourdhui)
        except Exception:                                # noqa: BLE001
            log.exception("Collecte initiale du %s en échec, on tente quand même",
                          aujourdhui)
            db.conn.rollback()

        courses = db.courses_du_jour(aujourdhui)
        derniere_relecture = time.monotonic()
        log.info("%d courses connues pour le %s", len(courses), aujourdhui)

        total = 0
        while time.monotonic() < fin_job:
            debut_tick = time.monotonic()
            maintenant = datetime.now(timezone.utc)

            # Relecture périodique : la collecte quotidienne a pu ajouter des
            # réunions depuis le démarrage du job.
            if time.monotonic() - derniere_relecture > 600:
                courses = db.courses_du_jour(aujourdhui)
                derniere_relecture = time.monotonic()

            a_relever = [
                (rc, cid, dep)
                for rc, (cid, dep) in courses.items()
                if dep is not None
                and maintenant >= dep - timedelta(minutes=args.fenetre_min)
                and maintenant <= dep + timedelta(minutes=args.marge_apres_min)
            ]

            lignes = []
            for (num_reunion, num_course), course_id, depart in a_relever:
                try:
                    pj = api.participants(aujourdhui, num_reunion, num_course, live=True)
                except Exception as e:                   # noqa: BLE001
                    log.warning("R%sC%s : %s", num_reunion, num_course, e)
                    continue
                if not pj:
                    continue
                releve = datetime.now(timezone.utc)
                for part in pj.get("participants") or []:
                    direct = part.get("dernierRapportDirect") or {}
                    cote = direct.get("rapport")
                    if cote is None or part.get("numPmu") is None:
                        continue
                    lignes.append({
                        "course_id": course_id,
                        "num_pmu": part["numPmu"],
                        "releve_at": releve,
                        "cote": cote,
                        # négatif = avant le départ
                        "minutes_avant_depart":
                            (releve - depart).total_seconds() / 60.0,
                    })

            if lignes:
                total += db.inserer_snapshots(lignes)
                db.commit()
                log.info("%d courses en fenêtre, %d cotes relevées (cumul %d)",
                         len(a_relever), len(lignes), total)

            reste = args.intervalle_sec - (time.monotonic() - debut_tick)
            if reste > 0:
                time.sleep(min(reste, max(0.0, fin_job - time.monotonic())))

        log.info("Job terminé : %d cotes enregistrées", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
