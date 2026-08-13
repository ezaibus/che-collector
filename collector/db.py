"""Écriture vers Supabase (Postgres).

Choix d'implémentation : psycopg3 en direct plutôt que le client PostgREST de
Supabase. PostgREST passe par HTTP et plafonne vite en insertion de masse ;
ici on charge ~540 participants par journée de courses, sur ~4 900 journées.

Tous les écrits sont idempotents (`on conflict do update`) : rejouer une date
déjà collectée est sans effet de bord. C'est ce qui rend le backfill
reprenable et permet à la collecte quotidienne de repasser sur une journée
pour y injecter les arrivées une fois les courses courues.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Iterable, Sequence

import psycopg
from psycopg.types.json import Jsonb

from .config import dsn_supabase

log = logging.getLogger(__name__)

# Colonnes de type jsonb : psycopg n'adapte pas les listes/dicts Python tout seul.
COLONNES_JSONB = {"res_ordre_arrivee"}


def _prepare(valeur: Any, colonne: str) -> Any:
    if colonne in COLONNES_JSONB and valeur is not None:
        return Jsonb(valeur)
    return valeur


class Db:
    def __init__(self, dsn: str | None = None):
        # Valide l'hôte avant de tenter la connexion : une erreur de chaîne
        # remonte sinon en « Network is unreachable » sur une adresse IPv6,
        # message qui n'oriente pas du tout vers la vraie cause.
        # psycopg3 prépare automatiquement une requête après 5 exécutions, ce
        # que le pooler en mode transaction ne supporte pas — d'où la bascule.
        dsn, mode_transaction = dsn_supabase(dsn)
        self.conn = psycopg.connect(
            dsn,
            autocommit=False,
            prepare_threshold=None if mode_transaction else 5,
        )
        # Caches de dimensions : évitent un aller-retour par ligne.
        self._cache_personnes: dict[str, int] = {}
        self._cache_chevaux: dict[str, int] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()

    def commit(self):
        self.conn.commit()

    # -- moteur d'upsert générique -------------------------------------------

    def _upsert(self, table: str, rows: Sequence[dict], conflit: Sequence[str],
                maj: bool = True) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        placeholders = ", ".join(["%s"] * len(cols))

        if maj:
            majs = [c for c in cols if c not in conflit]
            action = "do update set " + ", ".join(
                f"{c} = excluded.{c}" for c in majs
            ) if majs else "do nothing"
        else:
            action = "do nothing"

        sql = (
            f"insert into {table} ({', '.join(cols)}) "
            f"values ({placeholders}) "
            f"on conflict ({', '.join(conflit)}) {action}"
        )
        params = [
            tuple(_prepare(r.get(c), c) for c in cols) for r in rows
        ]
        with self.conn.cursor() as cur:
            cur.executemany(sql, params)

    # -- dimensions -----------------------------------------------------------

    def upsert_hippodromes(self, rows: Sequence[dict]) -> None:
        uniques = {r["code"]: r for r in rows if r}.values()
        self._upsert("hippodromes", list(uniques), ["code"])

    def resoudre_personnes(self, noms: Iterable[str]) -> dict[str, int]:
        """Insère les noms inconnus puis renvoie la table nom -> id."""
        manquants = sorted({n for n in noms if n and n not in self._cache_personnes})
        if manquants:
            with self.conn.cursor() as cur:
                cur.executemany(
                    "insert into personnes (nom) values (%s) on conflict (nom) do nothing",
                    [(n,) for n in manquants],
                )
                cur.execute(
                    "select nom, id from personnes where nom = any(%s)", (manquants,)
                )
                self._cache_personnes.update(dict(cur.fetchall()))
        return self._cache_personnes

    def resoudre_chevaux(self, rows: Sequence[dict]) -> dict[str, int]:
        """Idem pour les chevaux, clé naturelle PMU `id_cheval`."""
        uniques = {r["id_cheval"]: r for r in rows if r and r.get("id_cheval")}
        manquants = [r for k, r in uniques.items() if k not in self._cache_chevaux]
        if manquants:
            self._upsert("chevaux", manquants, ["id_cheval"])
            cles = [r["id_cheval"] for r in manquants]
            with self.conn.cursor() as cur:
                cur.execute(
                    "select id_cheval, id from chevaux where id_cheval = any(%s)", (cles,)
                )
                self._cache_chevaux.update(dict(cur.fetchall()))
        return self._cache_chevaux

    # -- faits ---------------------------------------------------------------

    def upsert_reunion(self, row: dict) -> int:
        """Renvoie l'id de la réunion (créée ou déjà présente)."""
        row = dict(row)
        row.setdefault("source", "PMU")
        if not row.get("cle_source"):
            row["cle_source"] = f"R{row.get('num_officiel')}"

        cols = list(row.keys())
        majs = [c for c in cols if c not in ("date_programme", "source", "cle_source")]
        sql = (
            f"insert into reunions ({', '.join(cols)}) "
            f"values ({', '.join(['%s'] * len(cols))}) "
            f"on conflict (date_programme, source, cle_source) do update set "
            + ", ".join(f"{c} = excluded.{c}" for c in majs)
            + " returning id"
        )
        with self.conn.cursor() as cur:
            cur.execute(sql, tuple(row[c] for c in cols))
            return cur.fetchone()[0]

    def upsert_courses(self, rows: Sequence[dict]) -> dict[int, int]:
        """Renvoie num_ordre -> course_id pour la réunion concernée."""
        if not rows:
            return {}
        for r in rows:
            r.setdefault("source", "PMU")
        self._upsert("courses", rows, ["reunion_id", "num_ordre"])
        reunion_id = rows[0]["reunion_id"]
        with self.conn.cursor() as cur:
            cur.execute(
                "select num_ordre, id from courses where reunion_id = %s", (reunion_id,)
            )
            return dict(cur.fetchall())

    def upsert_participants(self, rows: Sequence[dict]) -> int:
        self._upsert("participants", rows, ["course_id", "num_pmu"])
        return len(rows)

    def upsert_rapports(self, rows: Sequence[dict]) -> int:
        self._upsert("rapports", rows, ["course_id", "type_pari", "combinaison"])
        return len(rows)

    def inserer_snapshots(self, rows: Sequence[dict]) -> int:
        """Série temporelle des cotes : jamais de mise à jour, que de l'ajout."""
        self._upsert(
            "cotes_snapshots", rows,
            ["course_id", "num_pmu", "releve_at"], maj=False,
        )
        return len(rows)

    # -- journal / reprise ----------------------------------------------------

    def journaliser(self, d: date, statut: str, source: str = "PMU", **kw) -> None:
        row = {
            "date_programme": d, "source": source, "statut": statut,
            "nb_reunions": kw.get("nb_reunions"),
            "nb_courses": kw.get("nb_courses"),
            "nb_participants": kw.get("nb_participants"),
            "nb_rapports": kw.get("nb_rapports"),
            "erreur": (kw.get("erreur") or "")[:2000] or None,
            "duree_ms": kw.get("duree_ms"),
        }
        self._upsert("collecte_journal", [row], ["source", "date_programme"])
        self.conn.commit()

    def courses_du_jour(self, d: date) -> dict[tuple[int, int], tuple[int, Any]]:
        """(num_réunion, num_course) -> (course_id, heure_depart).

        Le relevé de cotes a besoin de résoudre un couple R/C vers la clé
        interne sans requêter la base à chaque tick.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                "select r.num_officiel, c.num_ordre, c.id, c.heure_depart "
                "from courses c join reunions r on r.id = c.reunion_id "
                "where r.date_programme = %s and c.source = 'PMU' "
                "  and r.num_officiel is not null",
                (d,),
            )
            return {(a, b): (cid, dep) for a, b, cid, dep in cur.fetchall()}

    def dates_deja_collectees(self, source: str = "PMU") -> set[date]:
        """Dates terminées (OK ou VIDE) : le backfill les saute."""
        with self.conn.cursor() as cur:
            cur.execute(
                "select date_programme from collecte_journal "
                "where source = %s and statut in ('OK', 'VIDE')",
                (source,),
            )
            return {r[0] for r in cur.fetchall()}
