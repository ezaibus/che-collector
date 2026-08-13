-- ============================================================================
--  Multi-source : préparer LeTrot / France Galop sans rien casser côté PMU
--
--  Contexte : le programme PMU ne couvre que les courses support de pari
--  national. Les réunions de province et les qualifications au trot en sont
--  absentes. Elles ne seront jamais des cibles de prédiction (on ne peut pas
--  parier dessus) mais elles comblent les trous de la forme d'un cheval.
--
--  Coût de cet ajout maintenant : quasi nul. Coût une fois 2,5 M de lignes
--  chargées : une migration lourde. D'où son anticipation.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Origine de la donnée
-- ---------------------------------------------------------------------------

alter table reunions add column if not exists source text not null default 'PMU';
alter table courses  add column if not exists source text not null default 'PMU';

alter table reunions drop constraint if exists reunions_source_valide;
alter table reunions add  constraint reunions_source_valide
    check (source in ('PMU', 'LETROT', 'FRANCE_GALOP'));

alter table courses drop constraint if exists courses_source_valide;
alter table courses add  constraint courses_source_valide
    check (source in ('PMU', 'LETROT', 'FRANCE_GALOP'));

-- Clé d'identification propre à la source :
--   PMU          -> 'R1'   (numéro officiel de réunion)
--   LETROT       -> '4418' (code hippodrome dans l'URL /courses/{date}/{code})
--   FRANCE_GALOP -> le token opaque de l'URL (double base64, non reconstructible)
alter table reunions add column if not exists cle_source text;

update reunions set cle_source = 'R' || num_officiel
 where cle_source is null and num_officiel is not null;

-- L'ancienne clé (date, num_officiel) ne tient pas en multi-source : une
-- réunion de province n'a pas de numéro officiel PMU (Dozulé, Villeréal...).
-- Plusieurs NULL n'entrant pas en collision, elle laisserait passer des
-- doublons. On bascule sur une clé qui vaut pour toutes les sources.
alter table reunions drop constraint if exists reunions_date_programme_num_officiel_key;
alter table reunions alter column num_officiel drop not null;

create unique index if not exists uq_reunions_source
    on reunions (date_programme, source, cle_source);

create index if not exists idx_reunions_source on reunions (source);
create index if not exists idx_courses_source  on courses (source);

comment on column courses.source is
    'PMU = pariable, seule source valide comme cible de prédiction. '
    'LETROT / FRANCE_GALOP = enrichissement de forme uniquement.';

-- ---------------------------------------------------------------------------
-- 2. Identité des chevaux entre sources
-- ---------------------------------------------------------------------------

-- Le PMU identifie un cheval par 'NOM-MERE-PERE', LeTrot par un entier stable
-- (ex. 11965). Aucun des deux ne connaît l'autre : le rapprochement se fait
-- sur (nom, nom_pere, nom_mere) et reste une résolution d'entités imparfaite
-- (homonymies, variantes d'orthographe). Cette table matérialise le résultat
-- une fois pour toutes, plutôt que de refaire le rapprochement à chaque requête.
create table if not exists chevaux_alias (
    source          text not null check (source in ('PMU', 'LETROT', 'FRANCE_GALOP')),
    id_externe      text not null,
    cheval_id       int  not null references chevaux (id) on delete cascade,
    -- score de confiance du rapprochement : 1.0 = clé exacte fournie par la
    -- source, < 1.0 = rapprochement heuristique à re-vérifier
    confiance       real not null default 1.0,
    rapproche_at    timestamptz not null default now(),
    primary key (source, id_externe)
);

create index if not exists idx_alias_cheval on chevaux_alias (cheval_id);

-- `chevaux.id_cheval` reste la clé naturelle PMU et le chemin rapide de la
-- phase 1. Elle devient nullable : un cheval vu uniquement en qualification
-- LeTrot n'a pas encore d'identifiant PMU.
alter table chevaux alter column id_cheval drop not null;

comment on table chevaux_alias is
    'Table de correspondance des identifiants externes. Autoritative pour '
    'toute jointure inter-sources. chevaux.id_cheval reste le raccourci PMU.';

-- ---------------------------------------------------------------------------
-- 3. Le journal de collecte devient multi-source
-- ---------------------------------------------------------------------------

alter table collecte_journal add column if not exists source text not null default 'PMU';
alter table collecte_journal drop constraint if exists collecte_journal_pkey;
alter table collecte_journal add  constraint collecte_journal_pkey
    primary key (source, date_programme);

-- ---------------------------------------------------------------------------
-- 4. La vue d'entraînement ne cible que le pariable
-- ---------------------------------------------------------------------------

create or replace view v_features_participants as
select
    p.id                        as participant_id,
    c.id                        as course_id,
    r.date_programme,
    c.heure_depart,
    r.hippodrome_code,
    c.discipline,
    c.specialite,
    c.categorie_particularite,
    c.distance,
    c.corde,
    c.type_piste,
    c.penetrometre_valeur,
    c.montant_prix,
    c.nombre_declares_partants,
    r.meteo_nebulosite,
    r.meteo_temperature,
    r.meteo_force_vent,

    p.num_pmu,
    p.cheval_id,
    p.driver_id,
    p.entraineur_id,
    p.age,
    p.sexe,
    p.oeilleres,
    p.place_corde,
    p.driver_change,
    p.indicateur_inedit,
    p.musique,
    p.handicap_poids,
    p.handicap_valeur,
    p.deferre,
    p.handicap_distance,
    p.avis_entraineur,
    p.nombre_courses,
    p.nombre_victoires,
    p.nombre_places,
    p.gains_carriere,
    p.gains_annee_en_cours,

    p.cote_reference,
    p.cote_reference_at,
    p.cote_reference_tendance,

    -- ---- LABELS ------------------------------------------------------------
    p.res_ordre_arrivee,
    (p.res_ordre_arrivee = 1)   as est_gagnant,
    (p.res_ordre_arrivee <= 3)  as est_place,
    p.res_cote_finale
from participants p
join courses  c on c.id = p.course_id
join reunions r on r.id = c.reunion_id
where p.statut = 'PARTANT'
  and c.source = 'PMU';          -- seules les courses pariables sont des cibles

alter table chevaux_alias enable row level security;
create policy lecture_publique_chevaux_alias on chevaux_alias
    for select to anon, authenticated using (true);
