# che-collector

Collecteur de données hippiques françaises vers Postgres (Supabase).

Ce dépôt ne contient que de la plomberie : appel d'API publiques, parsing,
écriture en base. Aucune modélisation, aucune stratégie de mise — celles-ci
vivent dans un dépôt privé séparé.

---

## Ce que l'API PMU fournit réellement

Trois endpoints, tous en JSON, sans authentification :

| Objet | URL (`{d}` = `jjmmaaaa`) |
|---|---|
| Programme du jour | `offline.turfinfo.api.pmu.fr/rest/client/7/programme/{d}` |
| Partants d'une course | `…/programme/{d}/R{r}/C{c}/participants` |
| Rapports définitifs | `online.turfinfo.api.pmu.fr/rest/client/1/programme/{d}/R{r}/C{c}/rapports-definitifs` |

Quelques comportements vérifiés empiriquement, qui expliquent des choix du code :

- **L'historique remonte au 1er mars 2013.** Borné par dichotomie : le
  15/02/2013 répond `204`, le 01/03/2013 répond `200`.
- **Une date sans données répond `204 No Content`, pas `404`**, avec un corps
  vide. Un `response.json()` naïf lève une exception : voir `pmu_api._get`.
- **`datesProgrammesDisponibles` n'annonce que J → J+3.** La profondeur
  historique n'est pas découvrable, elle se sonde.
- L'API sert `offline` (mis en cache) et `online` (temps réel). Le backfill
  utilise `offline` ; le relevé de cotes force `online`.

## Les deux cotes, et pourquoi la distinction est vitale

Chaque partant porte deux cotes, dont les timings ont été mesurés sur 166
observations réelles (journée du 13/08/2023) :

```
dernierRapportReference : 100 %  AVANT le départ — médiane H-30, max H-6
dernierRapportDirect    : 98,8 % APRÈS le départ — médiane H+2 min
```

Conséquence directe sur le schéma :

- `cote_reference` → relevée avant le départ, **seule cote utilisable en
  entrée de modèle**. Elle est conservée dans tout l'historique.
- `res_cote_finale` → relevée après le départ. **L'utiliser comme feature est
  une fuite de données garantie.** Elle ne sert qu'au calcul du ROI.

Cette règle est appliquée structurellement : toute colonne connue seulement
après le départ est préfixée `res_`, et la vue `v_features_participants`
n'expose aucune d'entre elles hors des labels explicites. **Entraîner sur la
vue, jamais sur les tables brutes.**

Ce qui reste définitivement perdu, c'est la *trajectoire* entre H-30 et le
départ. Elle n'est récupérable que par relevé en direct — d'où
`collector/snapshot.py`. Illustration du 13/08/2026 à Deauville : I WILL BE
KING cotait 34,0 à H-30 et 5,6 au départ. Il a gagné.

## Couverture

Le programme PMU ne contient que les courses **support de pari national**. Les
réunions de province et les qualifications au trot en sont absentes. Le schéma
anticipe cet ajout (`courses.source`, table `chevaux_alias`) sans que le
collecteur LeTrot soit encore écrit.

---

## Installation

1. **Base de données.** Appliquer les migrations dans l'ordre, via l'éditeur
   SQL Supabase ou `supabase db push` :

   ```
   supabase/migrations/0001_schema.sql
   supabase/migrations/0002_multi_source.sql
   ```

2. **Secret GitHub.** Créer `SUPABASE_DB_URL` dans
   *Settings → Secrets and variables → Actions*.

   > Utiliser la chaîne du **pooler** (port `6543`), pas la connexion directe
   > (port `5432`) : cette dernière est en IPv6 seulement, or les runners
   > GitHub n'ont pas d'IPv6. C'est la cause d'échec la plus fréquente.

3. **Backfill.** Lancer manuellement le workflow *Backfill historique*. 14
   shards annuels, 4 en parallèle, ~2 h 30 chacun → une nuit environ.

## Workflows

| Workflow | Déclenchement | Rôle |
|---|---|---|
| `backfill.yml` | manuel | Historique 2013 → aujourd'hui, un shard par année |
| `daily.yml` | 04:30 UTC | J-2 → J+1. Le repassage récupère arrivées et rapports |
| `snapshot.yml` | 08:00 / 13:45 / 19:30 UTC | Relevé des cotes, 3 jobs de ~6 h |

`snapshot.yml` n'utilise volontairement pas le cron pour cadencer les relevés :
le cron GitHub plafonne à 5 minutes et se fait décaler sous charge. Chaque job
boucle en interne toutes les 60 s, ce qui donne une précision à la minute.

> **Dépôt public :** les workflows planifiés sont automatiquement désactivés
> après 60 jours sans activité sur le dépôt. Un commit périodique suffit à
> l'éviter.

## Exécution locale

```bash
pip install -r requirements.txt
export SUPABASE_DB_URL="postgresql://…@…pooler.supabase.com:6543/postgres"

python -m collector.daily --recul 2
python -m collector.backfill --debut 2024-01-01 --fin 2024-01-31
python -m collector.snapshot --duree-min 60
```

Toutes les écritures sont idempotentes (`on conflict do update`) : rejouer une
date déjà collectée est sans effet de bord. C'est ce qui rend le backfill
reprenable après interruption.

## Usage

Données publiques, à usage personnel. Le débit est volontairement limité
(`--intervalle`, `max-parallel: 4` dans le backfill, soit ~8 req/s au total).
Les CGU du PMU n'autorisent pas la redistribution des données.
