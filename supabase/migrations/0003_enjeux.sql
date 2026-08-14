-- Enjeux par combinaison et masse des pools.
--
-- Ce que la table `rapports` contient déjà : ce qu'a payé la combinaison
-- gagnante, une fois la course courue. Ce qu'elle ne contient pas : ce que la
-- foule avait misé sur toutes les autres. Or c'est exactement ça, le prix.
--
-- Sans ces enjeux, on peut estimer la probabilité qu'un couplé sorte, mais pas
-- savoir s'il est cher ou bon marché. Parier à la valeur devient impossible :
-- on ne compare la probabilité à rien.
--
-- Deux limites assumées, mesurées sur l'API avant d'écrire ce fichier :
--
--   * seules les 12 combinaisons les plus jouées sont servies. On voit donc
--     le haut du classement — précisément les combinaisons que la foule
--     surcharge, et qu'il faut éviter. Le reste du pool est connu par
--     différence, pas dans le détail ;
--   * `total_enjeu` est horodaté 1 à 5 minutes APRÈS le départ (vérifié sur
--     douze courses de 2022 et 2025). C'est donc le pool final, celui qui a
--     déterminé les rapports, et non un instantané partiel.

create table if not exists masse_enjeu (
    course_id       bigint not null references courses(id) on delete cascade,
    type_pari       text   not null,
    -- En centimes, comme le sert l'API. On ne convertit pas : une division
    -- par 100 à l'écriture est une occasion silencieuse de perdre un centime
    -- sur des millions de lignes.
    total_enjeu     bigint not null,
    maj_at          timestamptz,
    evolution       double precision,
    collecte_at     timestamptz not null default now(),
    primary key (course_id, type_pari)
);

create table if not exists enjeux_combinaisons (
    course_id       bigint not null references courses(id) on delete cascade,
    type_pari       text   not null,
    -- Numéros PMU joints par des tirets, dans l'ordre servi par l'API :
    -- « 5-3 » n'est pas « 3-5 » pour un COUPLE_ORDRE. On conserve l'ordre
    -- brut, la normalisation éventuelle est affaire d'analyse.
    combinaison     text   not null,
    rang            smallint not null,     -- 1 = combinaison la plus jouée
    total_enjeu     bigint not null,
    maj_at          timestamptz,
    collecte_at     timestamptz not null default now(),
    primary key (course_id, type_pari, combinaison)
);

create index if not exists idx_enjeux_combi_course
    on enjeux_combinaisons (course_id, type_pari);

alter table masse_enjeu          enable row level security;
alter table enjeux_combinaisons  enable row level security;

do $$
declare t text; nom text;
begin
    foreach t in array array['masse_enjeu', 'enjeux_combinaisons']
    loop
        nom := 'lecture_publique_' || t;
        if not exists (select 1 from pg_policies
            where schemaname = 'public' and tablename = t and policyname = nom) then
            execute format(
                'create policy %I on %I for select to anon, authenticated using (true)',
                nom, t);
        end if;
    end loop;
end $$;
