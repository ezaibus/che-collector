"""Client HTTP pour l'API PMU.

Particularités de cette API, vérifiées empiriquement :
  - une date sans courses répond **204 No Content** (pas 404) avec un corps
    vide : `response.json()` lève alors une exception. On renvoie None.
  - l'historique remonte au 1er mars 2013 ; avant, tout est en 204.
  - `offline.*` sert le programme et les participants, `online.*` les rapports.
"""

from __future__ import annotations

import logging
import time
from datetime import date

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

BASE_OFFLINE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"
BASE_ONLINE = "https://online.turfinfo.api.pmu.fr/rest/client/1"

# Première date pour laquelle l'API renvoie des données (bornée par dichotomie :
# 15/02/2013 -> 204, 01/03/2013 -> 200).
PREMIERE_DATE = date(2013, 3, 1)


class PmuApi:
    def __init__(self, intervalle_min: float = 0.35, timeout: int = 25):
        self.intervalle_min = intervalle_min
        self.timeout = timeout
        self._dernier_appel = 0.0

        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        )
        retry = Retry(
            total=5,
            backoff_factor=1.5,               # 0s, 1.5s, 3s, 6s, 12s
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
        self.session.mount("https://", adapter)

    # -- interne -------------------------------------------------------------

    def _throttle(self) -> None:
        delta = time.monotonic() - self._dernier_appel
        if delta < self.intervalle_min:
            time.sleep(self.intervalle_min - delta)
        self._dernier_appel = time.monotonic()

    def _get(self, url: str):
        """Renvoie le JSON, ou None si l'API répond 204 / corps vide."""
        self._throttle()
        r = self.session.get(url, timeout=self.timeout)
        if r.status_code == 204 or not r.content:
            return None
        r.raise_for_status()
        return r.json()

    # -- endpoints -----------------------------------------------------------

    @staticmethod
    def fmt(d: date) -> str:
        """L'API attend jjmmaaaa, sans séparateur."""
        return d.strftime("%d%m%Y")

    def programme(self, d: date):
        return self._get(f"{BASE_OFFLINE}/programme/{self.fmt(d)}")

    def participants(self, d: date, r: int, c: int, live: bool = False):
        """`live=True` force la base `online`.

        `offline` sert une copie mise en cache : très bien pour du backfill
        historique, inadapté au relevé de cotes avant le départ où l'on veut
        la valeur courante. Toute la valeur des snapshots tient dans leur
        fraîcheur — les lire depuis un cache les viderait de leur sens.
        """
        base = BASE_ONLINE if live else BASE_OFFLINE
        return self._get(f"{base}/programme/{self.fmt(d)}/R{r}/C{c}/participants")

    def rapports_definitifs(self, d: date, r: int, c: int):
        return self._get(
            f"{BASE_ONLINE}/programme/{self.fmt(d)}/R{r}/C{c}/rapports-definitifs"
        )

    def combinaisons(self, d: date, r: int, c: int):
        """Enjeux par combinaison, pour chaque type de pari.

        L'API ne sert que les 12 combinaisons les plus jouées — c'est sa
        limite, pas celle du client. Disponible sur l'historique : vérifié de
        2014 à 2026.
        """
        return self._get(
            f"{BASE_OFFLINE}/programme/{self.fmt(d)}/R{r}/C{c}/combinaisons"
        )

    def masse_enjeu(self, d: date, r: int, c: int):
        """Masse totale engagée par type de pari.

        Horodatée une à cinq minutes après le départ : c'est le pool final,
        celui qui a déterminé les rapports, et non un instantané partiel.
        """
        return self._get(
            f"{BASE_OFFLINE}/programme/{self.fmt(d)}/R{r}/C{c}/masse-enjeu"
        )
