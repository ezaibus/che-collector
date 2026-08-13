"""Collecte d'une journée de courses PMU, de bout en bout.

Partagé par le backfill (dates passées) et la collecte quotidienne (J et J-1).
L'unité de travail est la journée : c'est la granularité du journal de reprise
et celle du programme côté API.
"""

from __future__ import annotations

import logging
import time
from datetime import date

from . import parse
from .db import Db
from .pmu_api import PmuApi

log = logging.getLogger(__name__)


def collecter_journee(api: PmuApi, db: Db, d: date) -> dict:
    """Collecte et enregistre une journée. Idempotent : rejouable sans risque."""
    t0 = time.monotonic()
    stats = {"nb_reunions": 0, "nb_courses": 0, "nb_participants": 0, "nb_rapports": 0}

    prog = api.programme(d)
    if not prog or not prog.get("programme"):
        # 204 No Content : jour sans courses, ou antérieur au 01/03/2013.
        db.journaliser(d, "VIDE", duree_ms=int((time.monotonic() - t0) * 1000))
        log.info("%s : aucune donnée (204)", d)
        return stats

    reunions = prog["programme"].get("reunions") or []

    for reu in reunions:
        num_reunion = reu.get("numOfficiel")
        if num_reunion is None:
            continue

        hippo = parse.parse_hippodrome(reu)
        if hippo:
            db.upsert_hippodromes([hippo])

        reunion_id = db.upsert_reunion(parse.parse_reunion(reu, d))
        courses_json = reu.get("courses") or []
        if not courses_json:
            continue

        ids_courses = db.upsert_courses(
            [parse.parse_course(c, reunion_id) for c in courses_json]
        )
        stats["nb_reunions"] += 1
        stats["nb_courses"] += len(courses_json)

        # --- participants : on agrège toute la réunion avant d'écrire, pour
        # ne résoudre les dimensions (chevaux, personnes) qu'une seule fois.
        brut: list[tuple[int, list[dict]]] = []
        for c in courses_json:
            num_ordre = c.get("numOrdre")
            course_id = ids_courses.get(num_ordre)
            if course_id is None:
                continue
            pj = api.participants(d, num_reunion, num_ordre)
            if not pj:
                continue
            brut.append((course_id, pj.get("participants") or []))

        tous = [p for _, ps in brut for p in ps]
        if tous:
            ids_chevaux = db.resoudre_chevaux(
                [x for x in (parse.parse_cheval(p) for p in tous) if x]
            )
            noms = [n for p in tous for n in parse.noms_personnes(p)]
            ids_personnes = db.resoudre_personnes(noms)

            lignes = [
                parse.parse_participant(p, course_id, ids_chevaux, ids_personnes)
                for course_id, ps in brut
                for p in ps
                if p.get("numPmu") is not None
            ]
            stats["nb_participants"] += db.upsert_participants(lignes)

        # --- rapports définitifs : seulement si l'arrivée est officielle,
        # sinon c'est une requête pour rien.
        for c in courses_json:
            if not c.get("rapportsDefinitifsDisponibles"):
                continue
            course_id = ids_courses.get(c.get("numOrdre"))
            if course_id is None:
                continue
            try:
                rj = api.rapports_definitifs(d, num_reunion, c["numOrdre"])
            except Exception as e:                      # noqa: BLE001
                log.warning("%s R%sC%s rapports KO : %s", d, num_reunion, c["numOrdre"], e)
                continue
            if rj:
                stats["nb_rapports"] += db.upsert_rapports(
                    parse.parse_rapports(rj, course_id)
                )

        db.commit()

    db.journaliser(d, "OK", duree_ms=int((time.monotonic() - t0) * 1000), **stats)
    log.info(
        "%s : %d réunions, %d courses, %d partants, %d rapports (%.1fs)",
        d, stats["nb_reunions"], stats["nb_courses"],
        stats["nb_participants"], stats["nb_rapports"], time.monotonic() - t0,
    )
    return stats
