-- ============================================================================
--  Base PMU — schéma initial
--  Cible : Supabase Pro (Postgres 15+), instance Micro.
--
--  PRINCIPE ANTI-FUITE (le plus important de ce fichier) :
--  toute colonne connue seulement APRÈS le départ est préfixée `res_`
--  (résultat). Les vues `v_features_*` ne les exposent jamais.
--  Entraîne tes modèles sur les vues, jamais sur les tables brutes.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Dimensions
-- ---------------------------------------------------------------------------

create table if not exists hippodromes (
    code            text primary key,           -- ex. 'DEA'
    libelle_court   text not null,
    libelle_long    text,
    pays_code       text,
    pays_libelle    text
);

-- Drivers, entraîneurs, propriétaires, éleveurs partagent le même espace de
-- noms : un driver peut être entraîneur. Une seule table, référencée 4 fois.
create table if not exists personnes (
    id              int generated always as identity primary key,
    nom             text not null unique
);

create table if not exists chevaux (
    id              int generated always as identity primary key,
    -- clé naturelle fournie par le PMU : 'MUNCH-ACAPULCO GOLD-KENDARGENT'
    id_cheval       text not null unique,
    nom             text not null,
    nom_pere        text,
    nom_mere        text,
    nom_pere_mere   text,
    sexe            text,
    race            text,
    robe            text,
    pays            text
);

create index if not exists idx_chevaux_nom on chevaux (nom);

-- ---------------------------------------------------------------------------
-- 2. Réunions et courses
-- ---------------------------------------------------------------------------

create table if not exists reunions (
    id                  int generated always as identity primary key,
    date_programme      date not null,
    num_officiel        smallint not null,          -- le "R" de R1C3
    hippodrome_code     text references hippodromes (code),
    nature              text,                       -- DIURNE / NOCTURNE / ...
    audience            text,                       -- NATIONAL / INTERNATIONAL
    statut              text,
    specialites         text[],
    -- météo : connue avant le départ, donc exploitable
    meteo_nebulosite    text,
    meteo_temperature   smallint,
    meteo_force_vent    smallint,
    meteo_direction_vent text,
    unique (date_programme, num_officiel)
);

create index if not exists idx_reunions_date on reunions (date_programme);

create table if not exists courses (
    id                      bigint generated always as identity primary key,
    reunion_id              int not null references reunions (id) on delete cascade,
    num_ordre               smallint not null,      -- le "C" de R1C3
    num_externe             smallint,

    libelle                 text,
    libelle_court           text,
    discipline              text,                   -- PLAT / ATTELE / MONTE / STEEPLECHASE / HAIES / CROSS
    specialite              text,
    categorie_particularite text,                   -- COURSE_A_CONDITIONS / HANDICAP / ...
    condition_age           text,
    condition_sexe          text,
    conditions              text,

    distance                int,                    -- mètres
    distance_unit           text,
    corde                   text,                   -- CORDE_GAUCHE / CORDE_DROITE / LIGNE_DROITE
    parcours                text,
    type_piste              text,                   -- HERBE / PSF / MACHEFER / CENDREE
    penetrometre_valeur     text,                   -- ex. '3,4' (état du terrain)
    penetrometre_intitule   text,

    montant_prix            bigint,                 -- allocation totale (centimes)
    montant_offert_1er      bigint,
    nombre_declares_partants smallint,

    heure_depart            timestamptz,
    statut                  text,                   -- PROGRAMMEE / FIN_COURSE / ...

    -- ---- post-course -------------------------------------------------------
    res_ordre_arrivee       jsonb,                  -- [[11],[5],[7]] — listes imbriquées = dead heats
    res_duree_course        int,                    -- ms
    res_arrivee_definitive  boolean,

    unique (reunion_id, num_ordre)
);

create index if not exists idx_courses_reunion   on courses (reunion_id);
create index if not exists idx_courses_depart    on courses (heure_depart);
create index if not exists idx_courses_discipline on courses (discipline);

-- ---------------------------------------------------------------------------
-- 3. Participants — la table centrale (~2,5 M lignes sur 13 ans)
-- ---------------------------------------------------------------------------

create table if not exists participants (
    id                      bigint generated always as identity primary key,
    course_id               bigint not null references courses (id) on delete cascade,
    num_pmu                 smallint not null,      -- numéro de dossard

    cheval_id               int references chevaux (id),
    driver_id               int references personnes (id),
    entraineur_id           int references personnes (id),
    proprietaire_id         int references personnes (id),
    eleveur_id              int references personnes (id),

    -- ---- pré-course : exploitable comme feature ---------------------------
    statut                  text,                   -- PARTANT / NON_PARTANT
    age                     smallint,
    sexe                    text,
    race                    text,
    allure                  text,
    oeilleres               text,                   -- SANS_OEILLERES / OEILLERES_CLASSIQUES / AUSTRALIENNES
    place_corde             smallint,
    driver_change           boolean,
    indicateur_inedit       boolean,                -- 1re course de sa carrière
    jument_pleine           boolean,
    engagement              boolean,
    supplement              bigint,
    pays_entrainement       text,
    musique                 text,                   -- forme récente : '1a 2a Da 3a 5a'

    -- plat / obstacle
    handicap_poids          int,                    -- décagrammes (580 = 58,0 kg)
    handicap_valeur         int,
    poids_condition_monte   int,
    poids_condition_monte_change boolean,

    -- trot
    deferre                 text,                   -- DEFERRE_ANTERIEURS / PROTEGE_... / etc.
    handicap_distance       int,                    -- mètres (trot à handicap)
    avis_entraineur         text,                   -- NEUTRE / POSITIF / NEGATIF
    taux_reclamation        bigint,

    -- palmarès à la date de la course (cumuls fournis par le PMU)
    nombre_courses          smallint,
    nombre_victoires        smallint,
    nombre_places           smallint,
    nombre_places_second    smallint,
    nombre_places_troisieme smallint,
    gains_carriere          bigint,
    gains_victoires         bigint,
    gains_place             bigint,
    gains_annee_en_cours    bigint,
    gains_annee_precedente  bigint,

    -- ---- COTES : la distinction critique -----------------------------------
    -- Référence : mesurée AVANT le départ (médiane H-30, 100 % pré-départ sur
    -- l'échantillon vérifié). C'est la SEULE cote utilisable en feature.
    cote_reference          real,
    cote_reference_at       timestamptz,
    cote_reference_tendance text,                   -- '+' / '-' / '='

    -- ---- post-course : JAMAIS en feature -----------------------------------
    -- Cote finale, relevée ~2 min APRÈS le départ. Sert de base au calcul du
    -- ROI et de label. L'utiliser en entrée = fuite de données garantie.
    res_cote_finale         real,
    res_cote_finale_at      timestamptz,
    res_ordre_arrivee       smallint,               -- null si non classé / non partant
    res_reduction_km        int,                    -- ms/km réalisés dans CETTE course (trot)
    res_temps_obtenu        int,                    -- ms
    res_incident            text,                   -- DISQUALIFIE_POUR_ALLURE_IRREGULIERE / TOMBE / ...
    res_distance_cheval_precedent text,
    res_commentaire         text,

    unique (course_id, num_pmu)
);

create index if not exists idx_part_course      on participants (course_id);
create index if not exists idx_part_cheval      on participants (cheval_id);
create index if not exists idx_part_driver      on participants (driver_id);
create index if not exists idx_part_entraineur  on participants (entraineur_id);

-- ---------------------------------------------------------------------------
-- 4. Rapports définitifs — base de calcul du ROI au backtest
-- ---------------------------------------------------------------------------

create table if not exists rapports (
    id                      bigint generated always as identity primary key,
    course_id               bigint not null references courses (id) on delete cascade,
    type_pari               text not null,          -- SIMPLE_GAGNANT / TRIO / MULTI / ...
    combinaison             text not null,          -- '11' ou '11-5-7'
    dividende_pour_un_euro  bigint,                 -- centimes pour 1 € misé
    nombre_gagnants         numeric,                -- nb de tickets gagnants -> taille de la foule
    mise_base               int,
    rembourse               boolean,
    unique (course_id, type_pari, combinaison)
);

create index if not exists idx_rapports_course on rapports (course_id, type_pari);

-- ---------------------------------------------------------------------------
-- 5. Snapshots de cotes — série temporelle H-40 → départ
--     Non récupérable rétroactivement : seule la collecte live l'alimente.
-- ---------------------------------------------------------------------------

create table if not exists cotes_snapshots (
    course_id       bigint not null references courses (id) on delete cascade,
    num_pmu         smallint not null,
    releve_at       timestamptz not null,
    cote            real not null,
    -- minutes restantes avant le départ au moment du relevé (négatif = avant)
    minutes_avant_depart real,
    primary key (course_id, num_pmu, releve_at)
);

create index if not exists idx_snap_course on cotes_snapshots (course_id);

-- ---------------------------------------------------------------------------
-- 6. Journal de collecte — rend le backfill reprenable
-- ---------------------------------------------------------------------------

create table if not exists collecte_journal (
    date_programme  date primary key,
    statut          text not null,          -- OK / VIDE / ERREUR / EN_COURS
    nb_reunions     smallint,
    nb_courses      smallint,
    nb_participants int,
    nb_rapports     int,
    erreur          text,
    collecte_at     timestamptz not null default now(),
    duree_ms        int
);

create index if not exists idx_journal_statut on collecte_journal (statut);

-- ---------------------------------------------------------------------------
-- 7. Vues d'entraînement — garantie structurelle anti-fuite
--     Aucune colonne `res_*` n'y figure, sauf le label explicite.
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

    -- seule cote autorisée en entrée
    p.cote_reference,
    p.cote_reference_at,
    p.cote_reference_tendance,

    -- ---- LABELS (cible, jamais en entrée) ---------------------------------
    p.res_ordre_arrivee,
    (p.res_ordre_arrivee = 1)   as est_gagnant,
    (p.res_ordre_arrivee <= 3)  as est_place,
    p.res_cote_finale
from participants p
join courses  c on c.id = p.course_id
join reunions r on r.id = c.reunion_id
where p.statut = 'PARTANT';

comment on view v_features_participants is
    'Vue d''entraînement. Les colonnes res_* sont des LABELS : ne jamais les '
    'passer en entrée du modèle. cote_reference est la seule cote pré-départ.';

-- ---------------------------------------------------------------------------
-- 8. RLS — lecture publique pour le front Vercel, écriture service_role only
-- ---------------------------------------------------------------------------

alter table hippodromes      enable row level security;
alter table personnes        enable row level security;
alter table chevaux          enable row level security;
alter table reunions         enable row level security;
alter table courses          enable row level security;
alter table participants     enable row level security;
alter table rapports         enable row level security;
alter table cotes_snapshots  enable row level security;
alter table collecte_journal enable row level security;

-- Postgres ne connaît pas `create policy if not exists` : on teste
-- explicitement pg_policies, faute de quoi rejouer la migration échoue sur
-- « policy already exists ».
do $$
declare
    t text;
    nom text;
begin
    foreach t in array array['hippodromes','personnes','chevaux','reunions',
                             'courses','participants','rapports',
                             'cotes_snapshots','collecte_journal']
    loop
        nom := 'lecture_publique_' || t;
        if not exists (
            select 1 from pg_policies
             where schemaname = 'public' and tablename = t and policyname = nom
        ) then
            execute format(
                'create policy %I on %I for select to anon, authenticated using (true)',
                nom, t);
        end if;
    end loop;
end $$;
