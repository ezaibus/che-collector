-- Rendre le montant facultatif sur les enjeux par combinaison.
--
-- Mesuré sur l'API après coup : avant le printemps 2015,
-- `listeCombinaisons` ne sert que la combinaison, sans `totalEnjeu`. L'ordre
-- est conservé — l'API classe par enjeu décroissant — mais les montants
-- n'existent pas.
--
--   mars 2013 -> ~mars 2015 : ordre seul
--   ~avril 2015 -> 2026     : ordre et montants
--
-- Bascule resserrée par sondage : rien le 20/02/2015, tout le 10/04/2015.
--
-- Un rang sans montant reste exploitable : savoir quel couplé la foule
-- charge le plus est une information ordinale, même sans son prix. La
-- contrainte NOT NULL faisait rejeter ces lignes en silence, ce qui est le
-- pire des deux mondes : ni donnée, ni erreur.

alter table enjeux_combinaisons
    alter column total_enjeu drop not null;
