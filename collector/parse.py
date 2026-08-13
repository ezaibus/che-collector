"""Transformation du JSON PMU en lignes prêtes pour Postgres.

Convention : toute clé issue d'une information connue seulement après le
départ est préfixée `res_`, en miroir du schéma SQL. C'est la barrière
anti-fuite — elle doit rester visible à la lecture.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _ts(ms: int | None) -> datetime | None:
    """Epoch millisecondes -> timestamptz UTC."""
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def _sub(d: Any, *chemin, defaut=None):
    """Accès imbriqué tolérant : _sub(p, 'robe', 'libelleCourt')."""
    for cle in chemin:
        if not isinstance(d, dict):
            return defaut
        d = d.get(cle)
        if d is None:
            return defaut
    return d


# ---------------------------------------------------------------------------
# Réunions / courses
# ---------------------------------------------------------------------------

def parse_hippodrome(reunion: dict) -> dict | None:
    h = reunion.get("hippodrome") or {}
    code = h.get("code")
    if not code:
        return None
    return {
        "code": code,
        "libelle_court": h.get("libelleCourt") or code,
        "libelle_long": h.get("libelleLong"),
        "pays_code": _sub(reunion, "pays", "code"),
        "pays_libelle": _sub(reunion, "pays", "libelle"),
    }


def parse_reunion(reunion: dict, date_programme) -> dict:
    meteo = reunion.get("meteo") or {}
    return {
        "date_programme": date_programme,
        "num_officiel": reunion.get("numOfficiel"),
        "hippodrome_code": _sub(reunion, "hippodrome", "code"),
        "nature": reunion.get("nature"),
        "audience": reunion.get("audience"),
        "statut": reunion.get("statut"),
        "specialites": reunion.get("specialites") or None,
        "meteo_nebulosite": meteo.get("nebulositeCode"),
        "meteo_temperature": meteo.get("temperature"),
        "meteo_force_vent": meteo.get("forceVent"),
        "meteo_direction_vent": meteo.get("directionVent"),
    }


def parse_course(course: dict, reunion_id: int) -> dict:
    return {
        "reunion_id": reunion_id,
        "num_ordre": course.get("numOrdre"),
        "num_externe": course.get("numExterne"),
        "libelle": course.get("libelle"),
        "libelle_court": course.get("libelleCourt"),
        "discipline": course.get("discipline"),
        "specialite": course.get("specialite"),
        "categorie_particularite": course.get("categorieParticularite"),
        "condition_age": course.get("conditionAge"),
        "condition_sexe": course.get("conditionSexe"),
        "conditions": course.get("conditions"),
        "distance": course.get("distance"),
        "distance_unit": course.get("distanceUnit"),
        "corde": course.get("corde"),
        "parcours": course.get("parcours"),
        "type_piste": course.get("typePiste"),
        "penetrometre_valeur": _sub(course, "penetrometre", "valeurMesure"),
        "penetrometre_intitule": _sub(course, "penetrometre", "intitule"),
        "montant_prix": course.get("montantPrix"),
        "montant_offert_1er": course.get("montantOffert1er"),
        "nombre_declares_partants": course.get("nombreDeclaresPartants"),
        "heure_depart": _ts(course.get("heureDepart")),
        "statut": course.get("statut"),
        # -- post-course --
        "res_ordre_arrivee": course.get("ordreArrivee"),
        "res_duree_course": course.get("dureeCourse"),
        "res_arrivee_definitive": course.get("arriveeDefinitive"),
    }


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------

def parse_cheval(p: dict) -> dict | None:
    """`idCheval` est la clé naturelle PMU : 'MUNCH-ACAPULCO GOLD-KENDARGENT'."""
    id_cheval = p.get("idCheval")
    if not id_cheval:
        return None
    return {
        "id_cheval": id_cheval,
        "nom": p.get("nom"),
        "nom_pere": p.get("nomPere"),
        "nom_mere": p.get("nomMere"),
        "nom_pere_mere": p.get("nomPereMere"),
        "sexe": p.get("sexe"),
        "race": p.get("race"),
        "robe": _sub(p, "robe", "libelleCourt"),
        "pays": p.get("pays"),
    }


CHAMPS_PERSONNES = ("driver", "entraineur", "proprietaire", "eleveur")


def noms_personnes(p: dict) -> list[str]:
    return [p[c] for c in CHAMPS_PERSONNES if p.get(c)]


def parse_participant(p: dict, course_id: int, ids_chevaux: dict,
                      ids_personnes: dict) -> dict:
    gains = p.get("gainsParticipant") or {}
    ref = p.get("dernierRapportReference") or {}
    direct = p.get("dernierRapportDirect") or {}

    return {
        "course_id": course_id,
        "num_pmu": p.get("numPmu"),
        "cheval_id": ids_chevaux.get(p.get("idCheval")),
        "driver_id": ids_personnes.get(p.get("driver")),
        "entraineur_id": ids_personnes.get(p.get("entraineur")),
        "proprietaire_id": ids_personnes.get(p.get("proprietaire")),
        "eleveur_id": ids_personnes.get(p.get("eleveur")),

        # -- pré-course --
        "statut": p.get("statut"),
        "age": p.get("age"),
        "sexe": p.get("sexe"),
        "race": p.get("race"),
        "allure": p.get("allure"),
        "oeilleres": p.get("oeilleres"),
        "place_corde": p.get("placeCorde"),
        "driver_change": p.get("driverChange"),
        "indicateur_inedit": p.get("indicateurInedit"),
        "jument_pleine": p.get("jumentPleine"),
        "engagement": p.get("engagement"),
        "supplement": p.get("supplement"),
        "pays_entrainement": p.get("paysEntrainement"),
        "musique": p.get("musique"),

        "handicap_poids": p.get("handicapPoids"),
        "handicap_valeur": p.get("handicapValeur"),
        "poids_condition_monte": p.get("poidsConditionMonte"),
        "poids_condition_monte_change": p.get("poidsConditionMonteChange"),

        "deferre": p.get("deferre"),
        "handicap_distance": p.get("handicapDistance"),
        "avis_entraineur": p.get("avisEntraineur"),
        "taux_reclamation": p.get("tauxReclamation"),

        "nombre_courses": p.get("nombreCourses"),
        "nombre_victoires": p.get("nombreVictoires"),
        "nombre_places": p.get("nombrePlaces"),
        "nombre_places_second": p.get("nombrePlacesSecond"),
        "nombre_places_troisieme": p.get("nombrePlacesTroisieme"),
        "gains_carriere": gains.get("gainsCarriere"),
        "gains_victoires": gains.get("gainsVictoires"),
        "gains_place": gains.get("gainsPlace"),
        "gains_annee_en_cours": gains.get("gainsAnneeEnCours"),
        "gains_annee_precedente": gains.get("gainsAnneePrecedente"),

        # -- cote de référence : AVANT le départ, seule utilisable en feature --
        "cote_reference": ref.get("rapport"),
        "cote_reference_at": _ts(ref.get("dateRapport")),
        "cote_reference_tendance": ref.get("indicateurTendance"),

        # -- post-course : labels uniquement --
        "res_cote_finale": direct.get("rapport"),
        "res_cote_finale_at": _ts(direct.get("dateRapport")),
        "res_ordre_arrivee": p.get("ordreArrivee"),
        "res_reduction_km": p.get("reductionKilometrique"),
        "res_temps_obtenu": p.get("tempsObtenu"),
        "res_incident": p.get("incident"),
        "res_distance_cheval_precedent": _sub(
            p, "distanceChevalPrecedent", "libelleCourt"),
        "res_commentaire": _sub(p, "commentaireApresCourse", "texte"),
    }


# ---------------------------------------------------------------------------
# Rapports définitifs
# ---------------------------------------------------------------------------

def parse_rapports(blocs: list, course_id: int) -> list[dict]:
    """L'endpoint renvoie une liste de blocs, un par type de pari."""
    lignes = []
    for bloc in blocs or []:
        type_pari = bloc.get("typePari")
        for r in bloc.get("rapports") or []:
            combinaison = r.get("combinaison")
            if combinaison is None:
                continue
            lignes.append({
                "course_id": course_id,
                "type_pari": type_pari,
                "combinaison": str(combinaison),
                "dividende_pour_un_euro": r.get("dividendePourUnEuro"),
                "nombre_gagnants": r.get("nombreGagnants"),
                "mise_base": bloc.get("miseBase"),
                "rembourse": bloc.get("rembourse"),
            })
    return lignes
