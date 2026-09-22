# État courant

## Vérité courante — STAGE 10

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_10_ACCEPTANCE_CLOSED_PENDING_PR_MERGE` |
| Base intégrée | `main` / `stage-09-complete` à `ad7a2c5b3f4ca33faf4aa51c91b7cefb5c11cc8d` |
| Branche | `stage/10-acceptance` |
| Commit produit qualifié live | `0d9a913cd8171827fd896b16608eb1d583eadb08` |
| Run live qualifiant | `20260912T160140123082Z-0d9a913cd817-local-docker` |
| Correctif d’outillage post-qualification | `16a2e2ce624a088741e6c096c4a827eab7adf4f2` (`fix(stage10): align promotion counters with clean live sandboxes`) |
| HEAD documentaire | le commit contenant ce document ; descendant de `16a2e2c` et de `0d9a913` |
| Migration head | `0034_stage_10` ; chaîne `0032_stage_09 → 0033_stage_10 → 0034_stage_10` |
| Live Discord A/B | **CLOSED** : 8 rapports du même run ; Stage 02/03/04 `PASS_WITH_APPROVED_LIMITATION`, Stage 05/06/08/09-primitives/09-full-chain `PASS` |
| Clôture exigences qualifiée | **PASS** : 246 exigences, 225 MUST, 21 SHOULD ; 245 `VERIFIED`, 1 `IMPLEMENTED` (`REQ-BOT-005`, SHOULD avec déviation documentée) ; 0 MUST ouvert, 0 PLANNED |
| Traçabilité trackée | reste volontairement une baseline sans preuve live injectée : `REQ-TEST-003` redevient `IMPLEMENTED` lorsqu’aucun aggregate qualifié n’est fourni ; la preuve `VERIFIED` fait foi dans le run qualifiant et son aggregate |
| Validation post-qualification | `28 passed` sur le promoteur ; suite offline `1040 passed, 29 skipped, 272 deselected` ; mypy `159 source files` sans erreur ; Ruff/format/diff-check verts |
| CI existante | workflow `CI` run `34707440163` sur `16a2e2c` : **SUCCESS** pour les jobs Stage 01–09 existants |
| CI Stage 10 | workflow dédié `Stage 10 Offline Acceptance` ajouté ; il exécute les profils Stage 10 offline et les meta-tests, sans Discord live ni secrets sandbox |
| RC / sécurité | 0 vulnérabilité critique au gate RC ; 1 High Debian zlib `CVE-2026-85091` sans version corrigée publiée dans le scan conservé ; frontend audit moderate+ à zéro |
| Publication | branche poussée ; aucune PR Stage 10 encore ouverte au moment de cette clôture documentaire ; aucun tag Stage 10 et aucun déploiement production |
| Next exact action | attendre le workflow Stage 10 offline vert, ouvrir la PR `stage/10-acceptance → main`, revue, puis **merge commit uniquement** (pas squash/rebase) afin de conserver `0d9a913` dans l’ascendance ; reconstruire ensuite RC/SBOM/checksums sur le SHA mergé propre |
| Stage suivante | `STAGE_11` reste `SKELETON_ONLY` et ne démarre qu’après intégration Stage 10 dans `main` et handoff RC post-merge |

## Règle de preuve Stage 10

Le commit qui a été réellement qualifié contre les deux Guilds Discord sandbox est
`0d9a913cd8171827fd896b16608eb1d583eadb08`. Les corrections ultérieures sont des
changements d’outillage/documentation et ne sont pas présentées comme requalifiées
live. Le bundle canonique est :

```text
artifacts/test-evidence/stage-10/
20260912T160140123082Z-0d9a913cd817-local-docker/
```

La promotion a produit `stage10-discord-live-closure.json`, puis la génération de
traçabilité qualifiée et `python scripts/audit_requirements.py --strict-closure`
ont donné :

```text
VERIFIED: 245
IMPLEMENTED: 1
PLANNED: 0
STRICT CLOSURE — MUST not closed: 0
STAGE 10 STRICT CLOSURE: PASS
```

Le fichier tracké `00_REQUIREMENTS_TRACEABILITY.md` n’embarque pas cette promotion
dynamique afin d’éviter un cercle SHA-preuve : une nouvelle commit modifiant la
traceabilité ne peut pas devenir rétroactivement le commit live qualifié.

## Handoff faisant foi

Le détail complet Stage 10 est dans
[`STAGE_10_HANDOFF.md`](../90_handoffs/STAGE_10_HANDOFF.md). Les états Stage 01–09
restent conservés dans leurs handoffs dédiés ; ils ne sont plus dupliqués ici afin
que ce fichier reste une vue de l’état courant.

Documents de clôture associés :

- [`STAGE_10_DISCORD_LIVE_STATUS.md`](../20_testing/STAGE_10_DISCORD_LIVE_STATUS.md)
- [`STAGE_10_RELEASE_CANDIDATE.md`](../20_testing/STAGE_10_RELEASE_CANDIDATE.md)
- [`STAGE_10_SECURITY_ACCEPTANCE.md`](../30_security/STAGE_10_SECURITY_ACCEPTANCE.md)
- [`STAGE_10_TECHNICAL_DEBT_DISPOSITION.md`](../20_testing/STAGE_10_TECHNICAL_DEBT_DISPOSITION.md)

Aucun travail de déploiement production, DNS, TLS ou reverse proxy n’est autorisé
par cette clôture ; ces sujets restent exclusivement STAGE 11.

## Addendum de branche UI — extension Phase 4 du 2026-09-16

Cet addendum décrit la branche de refonte `ui/complete-redesign`; il ne modifie
ni la clôture qualifiée Stage 10 ci-dessus, ni le SHA live, ni le statut de
Stage 11.

Le lot ajoute au moteur Policy canonique les intentions vocal, threads,
réactions, mentions et accès bot minimal, avec traduction Discord contextuelle,
Preview/Explain, compilation DSG/Plan et UI intention-first. Les lectures sont
cache-first, les décisions stale/incomplètes restent `UNKNOWN`, aucune mutation
Discord directe ou route APPLY n’est ajoutée et aucune migration n’est créée.

Preuves locales du lot : 127 tests backend ciblés, mypy/Ruff ciblés, 11 tests
frontend ciblés, ESLint/typecheck/i18n, OpenAPI courant et 3 parcours Playwright
ciblés. Les campagnes globales, PostgreSQL/RLS, Discord live A/B et APPLY réel
n’ont pas été exécutés. Le détail et les limites officielles sont consignés
dans `SCREENSHOTS_ESQUISSE/PHASE_04_REPORT.md` et l’addendum du handoff Stage 04.

## Addendum de branche UI — Phase 1 au 2026-09-22

Sur `ui/complete-redesign`, les tâches UX1-T009, UX1-T004, UX1-T007, UX1-T001,
UX1-T002 et UX1-T003 sont fermées. Le shell Bunny, l'Accueil, les Rôles et le
parcours Accès par intention sont implémentés avec contrôles frontend ciblés et
captures desktop/mobile inspectées. Aucun backend, invariant RLS, chemin cache-first
ou chaîne Policy/Preview/Plan n'a été modifié. La vérité opérationnelle détaillée
et le prochain geste exact restent dans
`SCREENSHOTS_ESQUISSE/UI_IMPLEMENTATION_LIVE_STATE.md` ; la prochaine tâche est
UX1-T005 et ne doit pas être commencée silencieusement.
