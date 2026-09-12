# Handoff STAGE 10 — Product completion, security and acceptance

## État actuel (vérité unique)

| Champ | Valeur |
|---|---|
| Date | `2026-09-12` |
| Base intégrée | `ad7a2c5b3f4ca33faf4aa51c91b7cefb5c11cc8d` (`main`, tag `stage-09-complete`) |
| Branche | `stage/10-acceptance` |
| Commit produit réellement qualifié live | `0d9a913cd8171827fd896b16608eb1d583eadb08` |
| Run live qualifiant | `20260912T160140123082Z-0d9a913cd817-local-docker` |
| Correctif d’outillage post-qualification | `16a2e2ce624a088741e6c096c4a827eab7adf4f2` |
| Statut Stage 10 | `ACCEPTANCE_CLOSED_PENDING_PR_MERGE` |
| Clôture exigences | **PASS** : 245 `VERIFIED`, 1 `IMPLEMENTED` SHOULD (`REQ-BOT-005`), 0 MUST ouvert, 0 PLANNED |
| Discord A/B | **PASS qualifié** sur les deux Guilds sandbox, avec limitations exactes approuvées pour 02/03/04 |
| Déploiement production | aucun ; hors scope Stage 10 |
| Tag Stage 10 | aucun ; à créer uniquement après merge + reconstruction RC propre |

Ce handoff remplace l’ancien état `BLOCKED_EXTERNAL_LIVE_CREDENTIALS`. Les
credentials sandbox ont été restaurés, la matrice Discord A/B a été exécutée,
la preuve a été promue et l’audit strict a fermé tous les MUST.

## 1. Preuve live canonique

Le bundle canonique est :

```text
artifacts/test-evidence/stage-10/
20260912T160140123082Z-0d9a913cd817-local-docker/
```

Rapports obligatoires du même run :

```text
discord-live-02.json
discord-live-03.json
discord-live-04.json
discord-live-05.json
discord-live-06.json
discord-live-08.json
discord-live-09-primitives.json
discord-live-09-full-chain.json
```

Résultats :

| Rapport | Statut |
|---|---|
| Stage 02 | `PASS_WITH_APPROVED_LIMITATION` |
| Stage 03 | `PASS_WITH_APPROVED_LIMITATION` |
| Stage 04 | `PASS_WITH_APPROVED_LIMITATION` |
| Stage 05 | `PASS` |
| Stage 06 | `PASS` |
| Stage 08 | `PASS` |
| Stage 09 primitives | `PASS` |
| Stage 09 full-chain | `PASS` |

Le promoteur a produit :

```text
stage10-discord-live-closure.json
```

sur le commit qualifié :

```text
0d9a913cd8171827fd896b16608eb1d583eadb08
```

La génération de traçabilité avec cet aggregate, suivie de :

```text
python scripts/validate_documentation.py
python scripts/audit_requirements.py --strict-closure
```

a donné :

```text
Source requirements: 246
MUST: 225
SHOULD: 21
VERIFIED: 245
IMPLEMENTED: 1
PLANNED: 0
STRICT CLOSURE — MUST not closed: 0
STRICT CLOSURE — SHOULD not closed (no VERIFIED, no documented deviation): 0
STAGE 10 STRICT CLOSURE: PASS
```

Le seul `IMPLEMENTED` restant est `REQ-BOT-005`, exigence SHOULD avec déviation
documentée. Aucun MUST n’est ouvert.

## 2. Distinction entre preuve live et HEAD ultérieurs

La preuve Discord est liée à `0d9a913`. Après la qualification, le promoteur a
révélé deux faux négatifs : il exigeait `> 0` pour des compteurs d’hygiène qui
peuvent légitimement être à `0` sur un sandbox propre :

- Stage 05 : `abandoned_fixture_jobs_resumed`,
  `terminal_fixture_jobs_acknowledged`, `preexisting_fixtures_cleaned` ;
- Stage 06 : `resumed_portability_jobs`.

Aucun rapport live n’a été modifié et aucun résultat Discord n’a été fabriqué.
La validation a été relancée sur les mêmes huit rapports après correction de la
logique de promotion uniquement. La correction permanente a été commitée en :

```text
16a2e2ce624a088741e6c096c4a827eab7adf4f2
fix(stage10): align promotion counters with clean live sandboxes
```

Ce commit ajoute des tests de régression : zéro accepté pour les compteurs
d’hygiène, négatif rejeté, vrais compteurs de preuve toujours strictement
positifs. Il n’est pas présenté comme un nouveau commit live qualifié.

## 3. Traçabilité et règle anti-circularité

`docs/10_implementation/00_REQUIREMENTS_TRACEABILITY.md` est généré par
`scripts/generate_traceability.py`. Sans aggregate live explicitement fourni,
le rendu tracké garde `REQ-TEST-003` à `IMPLEMENTED`.

C’est intentionnel : committer une version promue changerait le SHA Git et
rendrait la preuve liée à l’ancien SHA incohérente. La vérité persistante est
donc :

- baseline trackée sans promotion dynamique ;
- aggregate qualifié dans le bundle live ;
- ce handoff enregistre le résultat `VERIFIED` obtenu pendant le run qualifiant.

Ne jamais « corriger » manuellement la ligne REQ-TEST-003 dans la table générée.

## 4. Validation post-qualification

Sur `16a2e2c` :

```text
uv run pytest backend/tests/unit/test_promote_stage10_live_evidence.py -q
→ 28 passed

uv run pytest -m "not integration and not load and not discord_live" -q
→ 1040 passed, 29 skipped, 272 deselected

uv run mypy
→ Success: no issues found in 159 source files

ruff check → PASS
ruff format --check → PASS
git diff --check → PASS
worktree → clean
```

Le workflow GitHub Actions `CI`, run `34707440163`, exécuté sur `16a2e2c`, est
`success` pour les jobs historiques Stage 01–09.

Un workflow dédié `Stage 10 Offline Acceptance` est ajouté à la clôture. Il
exécute les profils Stage 10 `security`, `performance`, `failure-injection` et
`e2e`, puis les meta-tests de validation/promotion/traçabilité. Il ne contient
aucun secret Discord et ne prétend pas remplacer la qualification live A/B.

## 5. Topologie et frontières d’exécution

| Plan | Processus / composant | Responsabilité et limite |
|---|---|---|
| Frontend | Vite/React | session/CSRF, UI tenant-scopée, aucune possession de bot token, aucune mutation Discord directe |
| API | FastAPI | OAuth/session, API tenant-scopée, lecture cache-first, création d’intentions/plans/jobs ; aucune mutation Discord structurelle directe |
| Worker | `did.worker` | consommation des jobs durables, autorisation/preflight finale, Workload Governor, mutations Discord, vérification et audit |
| Scheduler | `did.scheduler` | réconciliation et campagnes différées/récurrentes/event-driven ; publication de travail durable uniquement |
| PostgreSQL | base durable | source durable, RLS activée/forcée sur les données tenant/utilisateur concernées |
| Redis | cache/coordination | cache Discord, single-flight, routage/wakeups/locks tenant-scopés |
| Backend image | Python 3.13 slim | environnement verrouillé, dépendances production, image candidate Stage 10 |

Frontière non négociable conservée :

```text
frontend → API → données/intention durable → worker gouverné → Discord
```

Les opérations multi-Guild restent doublement autorisées et fan-out vers des
jobs tenant-scopés ; aucun plan enfant ne mute plusieurs Guilds.

## 6. Migrations et cycle de données

Tête Alembic Stage 10 :

```text
0032_stage_09 → 0033_stage_10 → 0034_stage_10
```

- `0033_stage_10_transfer_plan_retention.py` : conservation honnête de
  l’historique de transfert lorsque le plan destination disparaît ;
- `0034_stage_10_tenant_purge_snapshot_erasure.py` : suppression des snapshots
  append-only uniquement pendant une purge tenant autorisée ; les mises à jour
  normales restent interdites.

La purge tenant conserve les invariants de sécurité, traite les dépendances dans
l’ordre compatible FK et purge les namespaces Redis du seul tenant ciblé.

## 7. Configuration requise — noms uniquement

Configuration runtime/base :

```text
DID_APP_ENV
DID_DATABASE_URL
DID_DATABASE_ADMIN_URL
DID_REDIS_URL
DID_LOG_LEVEL
DID_HEALTH_TIMEOUT_SECONDS
```

OAuth/session/chiffrement :

```text
DISCORD_CLIENT_ID
DISCORD_CLIENT_SECRET
DISCORD_REDIRECT_URI
SESSION_SECRET
OAUTH_TOKEN_ENCRYPTION_KEY
DID_OAUTH_TOKEN_KEY_VERSION
ARTIFACT_ENCRYPTION_KEY
ARTIFACT_PREVIOUS_ENCRYPTION_KEYS
```

Sandbox/live :

```text
DISCORD_BOT_TOKEN
DISCORD_TEST_GUILD_A_ID
DISCORD_TEST_GUILD_B_ID
```

Aucune valeur de secret ni aucun Snowflake brut n’est consigné dans ce handoff.
Les credentials production restent hors scope Stage 10.

## 8. État Guild A/B et cleanup

La qualification utilise deux Guilds sandbox distinctes. Les preuves sont
expurgées et ne stockent pas les IDs Discord bruts.

Le tail live continu a validé : Stage 05 → 06 → 08 → 09 primitives → 09
full-chain sans état manuel intermédiaire. Stage 09 full-chain a exécuté les 11
groupes et 60 scénarios ; cleanup : 42 ressources créées, 42 tentatives de
suppression, 42 supprimées/déjà absentes, 0 échec, 0 restante.

Stage 06 a purgé ses artefacts éphémères et ses transferts temporaires. Les
fixtures préfixées sont absentes après cleanup. Aucun nettoyage production
n’est impliqué.

## 9. Limitations live approuvées et non bloquantes

Stage 02 :

- profil administrateur non-owner live non exercé ;
- profil non-administrateur live non exercé.

Stage 03 :

- mutation externe Discord observée via Gateway non forcée ;
- reconnect/RESUME/non-resumed forcé non exercé ;
- Channel Obfuscation live visibility reste `CONTRACT_ONLY_NOT_LIVE_VERIFIED` ;
- limitations Stage 02 héritées.

Stage 04 :

- matrices thread membership contrôlées non créées par le runner read-only ;
- fixtures catégorie synced/desynced et hiérarchie managed/equal non créées par
  le runner read-only ;
- profils humains Stage 02 hérités.

Stage 05 :

- 429 couvert par contrat, pas forcé contre Discord ;
- ambiguous duplicate CREATE couvert sans fixture live manuelle forcée.

Stage 06 :

- incompatibilités bot/webhook couvertes en sécurité sans fixture live unsafe.

Ces limitations sont exactes, fail-closed et connues du promoteur ; toute
limitation différente fait échouer la promotion.

## 10. Sécurité, dette et vulnérabilités

- Frontend : `npm audit --audit-level=moderate` à zéro finding dans la passe
  Stage 10 enregistrée ;
- chunk frontend >500 kB : résolu par lazy loading ;
- `logging.unstructured_rejected` : comportement de redaction fail-closed
  accepté, pas un TODO masqué ;
- image backend : zéro vulnérabilité critique au gate RC ;
- risque connu : Debian zlib `CVE-2026-85091`, sévérité High, sans version
  corrigée publiée dans le scan conservé ; ne pas filtrer ni reclasser.

`REQ-BOT-005` reste SHOULD `IMPLEMENTED` avec déviation documentée : le backend
réel fournit la carte read/write, la visualisation dashboard complète reste
différée sans masquer l’API ni simuler la donnée.

## 11. RC / SBOM / checksums

Le dossier `artifacts/stage10-audit/` contient un paquet RC historique produit
avant la qualification finale. Il reste utile comme preuve de build/SBOM/scan,
mais ne doit pas être présenté comme l’artefact immuable final car son manifeste
référence un ancien SHA et un worktree alors dirty.

Le run qualifiant `0d9a913` a passé les gates RC inclus dans la phase Stage 10,
notamment build/import et zéro critique. Aucun tag ni déploiement production n’a
été créé.

Après merge Stage 10 dans `main`, reconstruire impérativement :

```text
backend image
backend-image.cdx.json
frontend.cdx.json
backend-image-cves.sarif
release-manifest.json
SHA256SUMS
```

sur le SHA mergé propre, puis rescanner zlib. Le tag Stage 10/RC ne vient
qu’après cette reconstruction.

## 12. CI et stratégie de merge

À la clôture :

- branche Stage 10 : 12 commits devant `main`, 0 derrière avant la passe docs/CI ;
- workflow historique CI sur `16a2e2c` : `success` ;
- aucun PR Stage 10 ouvert au moment de la rédaction ;
- workflow Stage 10 offline dédié ajouté et requis vert avant merge.

**Méthode de merge obligatoire pour préserver la chaîne de preuve : merge
commit.** Ne pas squasher ni rebaser les commits Stage 10 : `0d9a913` doit
rester un ancêtre identifiable du commit de merge.

## 13. Commandes de contrôle avant PR

Après récupération du commit de clôture documentaire/CI :

```bash
git pull --ff-only
git status --short
uv run pytest -m "not integration and not load and not discord_live" -q
uv run mypy
python scripts/validate_documentation.py
git diff --check
```

La qualification Discord live n’est pas à refaire pour cette passe documentaire.

## 14. Préconditions exactes pour STAGE 11

STAGE 11 reste `SKELETON_ONLY`. Avant de le réécrire/commencer :

1. workflow `Stage 10 Offline Acceptance` vert sur le HEAD de PR ;
2. PR `stage/10-acceptance → main` revue ;
3. merge **commit** réalisé sans réécriture de `0d9a913` ;
4. tête Alembic `0034_stage_10` confirmée sur `main` ;
5. RC/SBOM/SARIF/manifeste/checksums reconstruits sur le SHA mergé propre ;
6. vulnérabilités rescannées et High zlib redispositionné selon disponibilité
   d’un correctif ;
7. tag Stage 10/RC créé seulement si explicitement autorisé ;
8. inventaire final des services, variables, migrations, images/digests et
   preuves transmis au nouveau handoff Stage 11 ;
9. aucune mutation production/DNS/TLS avant autorisation humaine explicite.

Références :

- [`00_CURRENT_STATE.md`](../10_implementation/00_CURRENT_STATE.md)
- [`STAGE_10_DISCORD_LIVE_STATUS.md`](../20_testing/STAGE_10_DISCORD_LIVE_STATUS.md)
- [`STAGE_10_RELEASE_CANDIDATE.md`](../20_testing/STAGE_10_RELEASE_CANDIDATE.md)
- [`STAGE_10_SECURITY_ACCEPTANCE.md`](../30_security/STAGE_10_SECURITY_ACCEPTANCE.md)
- [`STAGE_10_TECHNICAL_DEBT_DISPOSITION.md`](../20_testing/STAGE_10_TECHNICAL_DEBT_DISPOSITION.md)
