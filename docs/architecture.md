# Architecture détaillée — Transport Pulse

## Vue d'ensemble

Le pipeline suit une architecture en couches (raw → staging → mart) :

1. **Ingestion temps réel** (`ingestion/fetch_passages.py`) — appelle l'endpoint SIRI Lite
   `estimated-timetable` de l'API PRIM (toutes lignes, `LineRef=ALL`), aplatit la réponse
   SIRI imbriquée (`ServiceDelivery` → `EstimatedTimetableDelivery` →
   `EstimatedJourneyVersionFrame` → `EstimatedVehicleJourney` → `EstimatedCalls`) en lignes
   tabulaires, puis écrit le résultat en Parquet (`data/raw/`) et l'insère dans la table
   PostgreSQL `raw_passages`.
2. **Référentiel statique** (`analysis/load_gtfs_postgres.py`) — charge le GTFS IDFM
   (agency, routes, stops, calendar, calendar_dates, trips en une fois ; `stop_times.txt`,
   737 Mo / ~8,7M lignes, par lots de 500 000 lignes) dans des tables PostgreSQL dédiées.
3. **Staging (dbt)** — `stg_passages` type et normalise les passages bruts.
4. **Mart (dbt)** — `fct_line_punctuality` agrège par ligne, mode et snapshot, et calcule
   les KPI de ponctualité.
5. **Restitution** — Metabase interroge directement PostgreSQL pour construire le
   dashboard.

## Point d'attention trouvé pendant le nettoyage : le mart n'était pas dans le projet dbt

`fct_line_punctuality.sql` et son `schema.yml` se trouvaient, dans l'archive d'origine, à
la racine du projet (`models/marts/`) — **en dehors** du dossier `transport_pulse/` qui
contient `dbt_project.yml`. Or `model-paths: ["models"]` y est résolu relativement à ce
dossier : dbt ne voyait donc jamais ce mart, et `dbt run` ne le construisait pas. Il a été
déplacé vers `dbt/transport_pulse/models/marts/` pour faire réellement partie du projet.
(Cause probable : une commande dbt — ou simplement un `mkdir models/marts`— lancée depuis
le mauvais dossier ; les logs égarés retrouvés dans `models/logs/dbt.log` et
`transport_pulse/models/staging/logs/dbt.log` pointent dans le même sens, et ont été
supprimés avec le reste des artefacts générés.)

## Couche staging : `stg_passages`

Renomme et type les colonnes de `raw_passages` : `response_ts` et `expected_departure`
sont castés en `timestamptz` (PostgreSQL les stocke en UTC en interne, ce qui règle la
question du fuseau horaire côté SQL). `line_code` et `stop_code` sont extraits des
identifiants composites IDFM en découpant sur `:` (`split_part(line_id, ':', 4)` — par
exemple `STIF:Line::C01100:` → `C01100`).

## Couche mart : `fct_line_punctuality`

Agrège au grain (`response_ts` × ligne × mode). Deux choix de calcul à noter :

- **Dénominateur de la ponctualité.** `punctuality_pct` ne compte que les passages
  réellement supervisés (`ON_TIME` + `DELAYED` + `EARLY`) au dénominateur — les
  `CANCELLED` et `NO_REPORT` en sont exclus, pour ne pas diluer l'indicateur avec des
  passages où l'on ne sait pas si le véhicule est passé à l'heure. `cancellation_pct` et
  `no_report_pct` sont calculés séparément (dénominateur = tous les passages) pour garder
  ces deux phénomènes visibles sans les mélanger à la ponctualité.
- **Seuil de 30 passages** (`where total_calls >= 30`). En dessous, un taux de ponctualité
  n'est pas statistiquement stable : une ligne avec seulement 2 passages observés peut
  afficher 0 % ou 100 % sans que ce soit représentatif. Plutôt que d'afficher un chiffre
  trompeur, la ligne est simplement exclue du mart pour la période concernée.

## Prototype Python : `delay_prototype.py` et `merge_asof`

Avant de généraliser le calcul de retard en dbt, le rapprochement horaire théorique /
temps réel a été prototypé en pandas sur une seule ligne (bus 64, `route_id IDFM:C01100`) :

- **Pourquoi `merge_asof`.** Un passage temps réel et son horaire GTFS n'ont presque
  jamais le même horodatage à la seconde près. Il faut associer chaque passage à
  l'horaire théorique **le plus proche**, pour le même arrêt, dans une tolérance donnée
  (1 800 s ici, soit 30 min). `pd.merge_asof(..., by="stop_id", direction="nearest",
  tolerance=...)` fait exactement cela, en restant proche de O(n log n) grâce au tri
  préalable sur la colonne `secs` — une jointure classique ne trouverait presque aucune
  correspondance exacte, et une boucle comparant chaque passage à tous les horaires
  possibles serait quadratique, ingérable à l'échelle du réseau.
- **Gestion des fuseaux horaires.** Le flux SIRI est en UTC, le GTFS en heure locale
  Europe/Paris. Le prototype convertit le temps réel en Europe/Paris (`tz_convert`) puis
  le réduit en secondes depuis minuit, pour le comparer à `arrival_time` du GTFS
  (également réduit en secondes via `pd.to_timedelta`, qui accepte nativement les heures
  GTFS `>24:00:00` utilisées pour les services se terminant après minuit).
- **Limite connue, non résolue dans le prototype.** Les secondes temps réel sont calculées
  à partir de `hour`/`minute`/`second` et ne dépassent donc jamais 86 400, alors qu'un
  horaire GTFS après minuit peut valoir par exemple 91 800 s (25h30). Un passage réel juste
  après minuit ne sera donc pas rapproché correctement d'un service de nuit tant que ce
  cas n'est pas traité explicitement (par exemple en ajoutant 86 400 s aux horaires réels
  compris entre 00:00 et l'heure de fin de service). À couvrir avant toute généralisation
  en dbt.

## Sources dbt déclarées mais pas encore utilisées

`models/staging/sources.yml` déclare déjà les tables GTFS (`routes`, `trips`,
`stop_times`, `stops`) comme sources dbt, mais aucun modèle de staging ne les matérialise
encore : le rapprochement horaire théorique / temps réel décrit ci-dessus reste
aujourd'hui uniquement dans le prototype Python, limité à une ligne. C'est la piste
d'évolution la plus naturelle du projet (voir le README).

## Schéma simplifié

| Table                       | Couche   | Grain                              |
|-------------------------------|----------|--------------------------------------|
| `raw_passages`                 | raw      | 1 appel de passage observé           |
| `stops`, `routes`, `trips`, `stop_times`, `calendar`, `calendar_dates`, `agency` | raw | référentiel GTFS (1 ligne = 1 enregistrement source) |
| `stg_passages`                 | staging  | 1 passage observé, typé/normalisé    |
| `fct_line_punctuality`         | mart     | 1 ligne × 1 mode × 1 snapshot (`response_ts`) |
