-- Exposer les chronos dans la vue de features.
--
-- `res_reduction_km` (secondes au kilomètre, au trot) et `res_temps_obtenu`
-- (chrono, au galop) sont collectés depuis le premier jour et n'ont jamais
-- servi. Or dans toute la littérature ce sont les prédicteurs les plus
-- puissants du sport, largement devant les taux de victoire : un cheval qui
-- gagne une course faible n'a rien montré, un cheval battu en réalisant un
-- chrono de premier ordre a tout montré.
--
-- Ils restent préfixés `res_` : ce sont des LABELS, connus après le départ.
-- Le modèle ne peut s'en servir que décalés — le chrono des courses passées
-- d'un cheval, jamais celui du jour. La barrière anti-fuite reste entière,
-- c'est la convention de nommage qui la rend visible.
--
-- `res_incident` accompagne : sans lui, un chrono manquant ne se distingue
-- pas d'une disqualification.

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
    p.res_cote_finale,
    p.res_temps_obtenu,
    p.res_reduction_km,
    p.res_incident
from participants p
join courses  c on c.id = p.course_id
join reunions r on r.id = c.reunion_id
where p.statut = 'PARTANT'
  and c.source = 'PMU';          -- seules les courses pariables sont des cibles

alter table chevaux_alias enable row level security;

do $$
begin
    if not exists (
        select 1 from pg_policies
         where schemaname = 'public'
           and tablename  = 'chevaux_alias'
           and policyname = 'lecture_publique_chevaux_alias'
    ) then
        create policy lecture_publique_chevaux_alias on chevaux_alias
            for select to anon, authenticated using (true);
    end if;
end $$;
