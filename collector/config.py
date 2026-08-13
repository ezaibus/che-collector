"""Lecture et validation du DSN Supabase.

Supabase propose trois chaînes de connexion, et deux d'entre elles écoutent
sur le port 5432 — ce qui rend le port inutilisable comme critère. Le vrai
discriminant est l'hôte :

    db.<ref>.supabase.co:5432            connexion directe, IPv6 SEULEMENT
    aws-0-<region>.pooler.supabase.com:5432   pooler session   <-- celui-ci
    aws-0-<region>.pooler.supabase.com:6543   pooler transaction

Les runners GitHub n'ont pas d'IPv6 : la connexion directe y échoue avec
« Network is unreachable » sur une adresse en 2a05:… — message qui ne dit pas
du tout qu'on s'est trompé de chaîne. D'où cette validation en amont.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class DsnInvalide(RuntimeError):
    pass


AIDE = (
    "Dans Supabase : bouton « Connect » → onglet « Session pooler ».\n"
    "L'hôte doit contenir 'pooler.supabase.com' et l'utilisateur ressembler à "
    "'postgres.<ref>' (avec un point). Si l'utilisateur est simplement "
    "'postgres' et l'hôte 'db.<ref>.supabase.co', c'est la connexion directe."
)


def dsn_supabase(dsn: str | None = None) -> tuple[str, bool]:
    """Renvoie (dsn, mode_transaction). Lève DsnInvalide si inutilisable."""
    dsn = dsn or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        raise DsnInvalide("SUPABASE_DB_URL manquant.\n" + AIDE)

    hote = (urlparse(dsn).hostname or "").lower()
    port = urlparse(dsn).port

    if hote.startswith("db.") and hote.endswith(".supabase.co"):
        raise DsnInvalide(
            f"DSN pointant vers la connexion directe ({hote}), qui est en IPv6 "
            f"seulement. Les runners GitHub n'ont pas d'IPv6 : la connexion "
            f"échouera avec « Network is unreachable ».\n" + AIDE
        )

    if "pooler.supabase.com" not in hote:
        log.warning(
            "Hôte inattendu (%s) : ni pooler Supabase ni connexion directe "
            "reconnue. On tente quand même.", hote or "?"
        )

    mode_transaction = port == 6543
    if mode_transaction:
        log.warning(
            "Port 6543 = pooler en mode transaction : les prepared statements "
            "n'y sont pas supportés, ils seront désactivés. Le mode session "
            "(port 5432) est préférable pour un script long."
        )
    return dsn, mode_transaction
