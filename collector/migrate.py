"""Application des migrations SQL, avec suivi de ce qui a déjà tourné.

Passer par ce script plutôt que par l'éditeur SQL Supabase permet de piloter
la base depuis GitHub Actions : le secret reste côté GitHub et personne n'a à
manipuler la chaîne de connexion à la main.

Les migrations ne sont pas idempotentes prises isolément — `create policy` et
`alter table ... add constraint` échouent au second passage. C'est la table
`schema_migrations` qui garantit qu'une migration ne s'applique qu'une fois.

    python -m collector.migrate            # applique ce qui manque
    python -m collector.migrate --etat     # ne fait que rapporter
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import psycopg

from .config import DsnInvalide, dsn_supabase

log = logging.getLogger("migrate")

DOSSIER = Path(__file__).resolve().parent.parent / "supabase" / "migrations"

SUIVI = """
create table if not exists schema_migrations (
    version      text primary key,
    applique_at  timestamptz not null default now()
)
"""

# Tables attendues après 0001 + 0002, pour le contrôle d'état.
TABLES = ("hippodromes", "personnes", "chevaux", "reunions", "courses",
          "participants", "rapports", "cotes_snapshots", "collecte_journal",
          "chevaux_alias", "masse_enjeu", "enjeux_combinaisons")


def etat(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("select version, applique_at from schema_migrations order by version")
        appliquees = cur.fetchall()
        print("\nMigrations appliquées :")
        for v, t in appliquees or []:
            print(f"  {v:<28} {t:%Y-%m-%d %H:%M}")
        if not appliquees:
            print("  (aucune)")

        print("\nTables :")
        for t in TABLES:
            cur.execute("select to_regclass(%s)", (f"public.{t}",))
            existe = cur.fetchone()[0] is not None
            if existe:
                cur.execute(f"select count(*) from {t}")     # noqa: S608
                print(f"  {t:<20} {cur.fetchone()[0]:>10} lignes")
            else:
                print(f"  {t:<20} {'ABSENTE':>10}")

        cur.execute("select to_regclass('public.v_features_participants')")
        print(f"\nVue v_features_participants : "
              f"{'présente' if cur.fetchone()[0] else 'ABSENTE'}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Applique les migrations SQL")
    p.add_argument("--etat", action="store_true", help="rapporter sans appliquer")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        stream=sys.stdout)

    try:
        dsn, _ = dsn_supabase()
    except DsnInvalide as e:
        log.error("%s", e)
        return 1

    fichiers = sorted(DOSSIER.glob("*.sql"))
    if not fichiers:
        log.error("Aucune migration dans %s", DOSSIER)
        return 1

    with psycopg.connect(dsn, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(SUIVI)
        conn.commit()

        if args.etat:
            etat(conn)
            return 0

        with conn.cursor() as cur:
            cur.execute("select version from schema_migrations")
            deja = {r[0] for r in cur.fetchall()}

        for f in fichiers:
            if f.name in deja:
                log.info("%s : déjà appliquée", f.name)
                continue
            log.info("%s : application…", f.name)
            try:
                with conn.cursor() as cur:
                    cur.execute(f.read_text(encoding="utf-8"))
                    cur.execute(
                        "insert into schema_migrations (version) values (%s)",
                        (f.name,),
                    )
                conn.commit()
                log.info("%s : OK", f.name)
            except Exception:
                conn.rollback()
                log.exception("%s : ÉCHEC — rien n'a été appliqué pour ce fichier",
                              f.name)
                return 1

        etat(conn)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
