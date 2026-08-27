# Stratégie globale de tests

## Principes et niveaux de preuve

La pyramide combine tests de domaine rapides, tests d’intégration sur dépendances réelles, contrats d’adapters, E2E UI et preuves Discord live. Chaque bug d’isolation, d’idempotence, de causalité, de permissions ou de traduction produit un test de non-régression. `VERIFIED` exige une preuve reproductible ; un mock ne suffit pas pour une sémantique externe critique.

Les suites portent des marqueurs (`unit`, `integration`, `postgres`, `redis`, `api`, `frontend`, `e2e`, `discord_live`, `security`, `slow`, `failure_injection`) et sont orchestrées par `scripts/validate_stage.py`. La CI exécute tout ce qui n’exige pas de secrets live ; les suites live sont déclenchées dans un environnement GitHub protégé ou local contrôlé.

## Backend

- `pytest` : domaine, services applicatifs, permissions, planification, cloning, langues, campagnes, parser et invariants ;
- PostgreSQL réel via Docker : migrations Alembic up/down lorsque sûr, contraintes, FK composites, index, transactions, RLS, concurrent writes et outbox ; SQLite n’est pas une preuve DB ;
- Redis réel via Docker : streams, consumer groups, locks, TTL, sessions, cache, pub/sub, single-flight et recovery ;
- API FastAPI : contrats Pydantic, auth, CSRF, IDOR, pagination, erreurs localisables, Snowflakes en chaînes et aucun repository cross-tenant consulté ;
- jobs/worker : idempotence, retries bornés, backoff/jitter, crash points, lock ownership, poison messages et redelivery ;
- migrations : base vide → head, version précédente → head, contraintes/RLS actives et smoke API après migration ;
- architecture : imports interdits, mutation Discord absente des routers, secrets absents des logs.

## Frontend

- TypeScript strict, lint et format check ;
- tests unitaires/composants pour loading/error/empty, permission display, query invalidation et serialization des IDs ;
- catalogue i18n typé : 100 % des clés EN/FR/DE/ES, paramètres compatibles, aucune clé brute ni chaîne système détectable, packs runtime invalides rejetés atomiquement ;
- gestes : `contextmenu` natif bloqué, clic droit simple, Right Drag au-delà du seuil, `pointercancel`, drag gauche intra/inter-Guild, Drop Target Resolver et alternative clavier ;
- Playwright : login simulé contrôlé, navigation, sélection tenant, plans, progression live, permissions, clone, traductions et campagnes ;
- accessibilité : navigation clavier, focus, rôles/ARIA traduits, contraste et tests automatiques complétés par revue manuelle.

## Multi-tenancy et Control Plane

Chaque endpoint, repository, event, cache, job et WebSocket tenant-scopé possède au minimum : happy path Guild A, refus Guild B, identifiant étranger, utilisateur sans membership, contexte RLS absent, clé Redis A/B et absence de fuite d’existence. Les transferts A→B exigent lecture/export A et import/mutation B ; retirer l’une des deux autorisations doit refuser avant export final ou plan destination.

Le Control Plane est testé avec deux utilisateurs : artifacts, préférences et campagnes globales restent owner-scopés ; chaque delivery fan-out redevient tenant-scopée. Aucun job parent multi-Guild n’appelle Discord.

## Discord sandbox live

Deux Guilds réelles isolées sont obligatoires avant clôture de STAGE 10. Les tests suivent `DISCORD_SANDBOX_TEST_MATRIX.md`, utilisent des préfixes uniques, inventorient l’état avant/après, minimisent les permissions et nettoient les ressources. Les validations critiques couvrent permissions/overwrites et hiérarchie, types/parentage de salons, Gateway/reconnect, 429/retry observable sans provoquer d’abus, create/update/delete, installation/désinstallation, cross-Guild autorisé et comportements d’obfuscation disponibles.

## Cache, panne et concurrence

Tester état frais/aging/stale/obfuscated/access-lost/deleted/tombstone, write-through après mutation, perte de séquence, reconnect, reconcile ciblé, cache miss, purge sans mutation et réobservation. Injecter les crashes avant appel Discord, après succès Discord avant commit DB, après commit avant ack Redis et pendant vérification. Vérifier `UNKNOWN_OUTCOME`, réconciliation avant retry et absence de doublon.

## Rate limits et équité

Le harness simule headers de bucket, 429 global/route/shared, `Retry-After`, réseau lent, invalid requests et pression multi-Guild. Les assertions couvrent queue, backpressure, priorité, fairness bornée, non-starvation, coalescing/single-flight, pause du reconcile, bulk endpoints, métriques et absence de GET Discord lors des consultations cache-hit. Une Guild bruyante ne doit pas empêcher une action interactive d’une autre Guild d’avancer dans la borne définie par le test.

## Traduction

Le corpus versionné FR/EN/DE/ES inclut phrases longues, contexte inter-phrases, pronoms, négations, jargon, glossaires concurrents, URLs, mentions, Markdown, code, timestamps, emojis custom, variables, embeds et composants. Les stratégies de segmentation (message masqué complet, blocs contextuels, phrases/nœuds regroupés) sont mesurées réellement avec `googletrans` sur préservation technique, qualité sémantique, latence et erreurs. Le choix et les résultats bruts expurgés sont conservés ; aucun score simulé.

Le parser et protector reçoivent property-based tests/fuzzing. Toute modification d’un token protégé, empreinte, `allowed_mentions` ou structure bloque la publication. Les pannes provider, timeouts, contenu partiel et glossaires ambigus sont fail-closed.

## Gates

- PR : lint, format, typecheck, unit, architecture, secrets scan, i18n et tests impactés ;
- merge d’étape : intégration PostgreSQL/Redis, migrations, API, frontend, sécurité, suites antérieures et documentation ;
- étapes live : preuve sandbox signée/date/commit, sans secret ;
- STAGE 10 : E2E complet, pannes, charge, deux Guilds, traceability sans `PLANNED/IMPLEMENTED` obligatoire restant ;
- STAGE 11 : smoke production, backup/restore et rollback réellement exercés.

## Preuves STAGE 05

- Le profil par defaut rejoue les migrations depuis `base`, `0001` a `0007` vers la tete unique `0009_stage_05`, puis exerce `head -> 0007 -> head`.
- Le profil `failure-injection` exerce les fenetres A-I sur PostgreSQL/Redis reels. Il ajoute le fence exact owner/token/generation et verifie qu'un callback tardif de l'ancien worker ne touche pas le nouvel attempt.
- La recovery est operation-specific. L'absence d'un channel dans une liste reste ambigue pour create/delete; la liste complete des roles fournit une preuve plus forte. Aucun CREATE ambigu n'est retry.
- Les tests d'integration couvrent l'autorisation acteur au worker, la confirmation actor-bound, les preconditions juste-a-temps, les matchers Gateway bulk/overwrite, l'index des plans concernes, l'Impact Engine et la progression concurrente.
- Le profil load compile et ordonne un DSG de 500 noeuds avec resultat deterministe et rapport JSON borne.
- Le live n'est PASS que si le plan complet effectue des mutations reelles, le crash-window conserve un seul CREATE, le symbol binding est recupere et le cleanup par plan ne laisse aucune fixture prefixee. Un refus de capability est `BLOCKED_CAPABILITY_CONFIGURATION`, jamais `PASS_WITH_APPROVED_LIMITATION`.

## Preuves STAGE 06

- Le profil par défaut rejoue les migrations `base`, `0001` à `0010` vers l'unique tête `0011_stage_06`, puis `head -> 0009 -> head`. Il couvre le domaine pur, l'API, PostgreSQL/RLS, l'enveloppe chiffrée, les quotas concurrents, les bindings de relation, le lifecycle CAS, les quatre modes, MERGE divergent, RECONCILE borné et le report-only sans plan.
- Le profil `security` est distinct : fichiers hostiles, limites, champs dupliqués, versions/types inconnus, absence de SSRF, injection d'IDs/capabilities/bindings, altération de l'enveloppe et de l'AAD, clé historique absente, isolation owner U/V, tenant A/B, quota, confused deputy et ambiguïté.
- Le profil load construit, ferme, mappe et compile 600 ressources sans requête Discord ni boucle DB par ressource. Le rapport et les métriques gardent une cardinalité bornée.
- Le live A→B n'est `PASS` que si les fixtures A et B sont créées par plans STAGE 05, le COPY_AS_NEW produit de nouveaux IDs B, A reste identique et sans mutation, un mapping existant confirmé est réutilisé, un second plan est compilé depuis l'artifact stocké avec un reader source interdit, puis le cleanup par plans et la purge ne laissent aucun préfixe `DID-STAGE06-TEST-`.
