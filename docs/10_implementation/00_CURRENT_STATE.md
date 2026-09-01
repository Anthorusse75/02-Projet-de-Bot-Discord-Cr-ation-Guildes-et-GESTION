# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_09_IMPLEMENTATION_IN_PROGRESS` |
| Last completed/integrated stage | `STAGE_08_MULTILINGUAL_CONTENT_AND_TRANSLATION_TOPOLOGY` |
| Base main (point de divergence de `stage/09-campaigns`) | `c41b61ae96cdb1d767c8d924212a6466b768ed60` — le commit de `main` d'où la branche STAGE 09 a été créée ; ce n'est **pas** nécessairement le HEAD courant de `main` (voir `git rev-parse main` pour l'état à jour) ni un identifiant STAGE 08 séparé, c'est le même commit que « STAGE 09 branch » ci-dessous, listé deux fois pour deux lecteurs différents (revue de PR vs audit du point de fork) |
| STAGE 08 functional tested code | `592b94bdee713cfb51e236e29cb979ba60e53ac9` |
| STAGE 08 approved final head | `42274836256d2af449678c239c2db4d8e5e6d01d` |
| STAGE 08 merge commit | `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 08 tag | `stage-08-complete` -> `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 09 branch | `stage/09-campaigns`, créée depuis `main` au commit `c41b61ae96cdb1d767c8d924212a6466b768ed60` |
| STAGE 09 PR | Draft PR #9, ouverte, non mergée |
| Last migration | `0028_stage_09`; chaîne `0013_stage_07 → … → 0021_stage_08 → 0022 → 0023 → 0024 → 0025 → 0026 → 0027 → 0028_stage_09`; tête unique, rehearsal up/down/up validé sur PostgreSQL réel à chaque étape |
| STAGE 09 implementation | Six passes cumulées : (1)-(4) fondations WP1-WP11, remédiation externe, root-cause d'intégrité/fencing, orchestration WP12 réelle ; (5) connexion au runtime réel (`did.runtime.py` exécute `CampaignSchedulerRuntime`), dispatch durable de livraison, fencing de fan-out d'occurrence, correction `event_type`, transport d'événement Stage03 réel, groupes logiques (REQ-MSG-002), rétention (REQ-MSG-019), sécurité anti double-traduction (REQ-MSG-007), identité d'approbation de variante — voir passes précédentes dans `STAGE_09_HANDOFF.md`. **Cette sixième passe** construit l'API HTTP Stage09 complète (WP14) : `did.api.stage09` expose campagnes CRUD, targets, schedule, simulation, activate/pause/resume/cancel (l'activation ne crée que du travail durable, jamais un appel Discord direct -- prouvé par un test source/import-graph ET par une activation IMMEDIATE réelle assertée contre les lignes DB), historique de livraisons, preview/approve de variantes (principal approbateur toujours la session authentifiée), triggers/trigger-sources ; promeut REQ-MSG-016 à `IMPLEMENTED`. Ajoute aussi trois tests PostgreSQL prouvant la CHAÎNE COMPLÈTE du runtime réel bout-en-bout (`CampaignSchedulerRuntime.tick()` réel -> `DurableDiscordIOWorker.run_guild_once()` réel, deux schedulers concurrents, redémarrage de process en plein milieu de la chaîne), fermant l'écart des sections 22/23 de la mission. Restent absents : le frontend (WP15, **construction en cours**), la matrice de qualification live complète, et le taggage d'ancestry sur événement Discord réellement généré côté production (REQ-MSG-030 — blocage externe documenté, voir ci-dessous) |
| Data model | Tables STAGE 09 : header Control-Plane user-owned (RLS `owner_discord_user_id`) séparé des tables Guild tenant-scoped (RLS `guild_id`, FK composite) ; voir migrations `0022`-`0028_stage_09` |
| Tests status | `pytest backend/tests/unit` (régression complète) : **734 passed** ; `DID_RUN_INTEGRATION=1 pytest backend/tests/integration` (régression complète, PostgreSQL réel) : **213 passed** ; `ruff check .` : PASS 0 finding ; `ruff format --check .` : PASS ; `mypy src/did` (strict) : PASS 0 erreur, 158 fichiers ; `check_secrets.py` : PASS 432 fichiers |
| Traceability | **29** IDs `IMPLEMENTED`, **2** `PARTIALLY_IMPLEMENTED`, **0** `NOT_STARTED` sur `REQ-MSG-001..031` (passe précédente : 28/3/0). Cette passe a fait passer REQ-MSG-016 (approbation de variante, désormais exposée par l'API réelle avec identité authentifiée) à `IMPLEMENTED` ; REQ-MSG-007 reste partiel car l'exigence nomme explicitement une UI absente ; REQ-MSG-030 reste partiel pour un blocage externe documenté (ADR-008). Chaque ligne pointe vers du code de production, des tests et une preuve reproductible dans `00_REQUIREMENTS_TRACEABILITY.md` / `STAGE09_REQUIREMENTS_CHECKLIST_LOCAL.md` |
| Discord live status | `scripts/validate_discord_live_stage09.py` exécuté avec `--include` sur sandbox Guild A réel : **5/5 scénarios PASS** (envoi immédiat allowed_mentions=none, edit possédé, delete possédé, dédup nonce, nonce distinct) via le vrai `DiscordPyMessageSender` ; preuve sanitisée committée (`docs/90_handoffs/evidence/stage09/discord-live-stage09.json`) ; matrice complète de qualification (Guild A/B, scheduler, Translation Groups, event triggers cross-Guild, variantes approuvées) **non exécutée** — l'orchestration bout-en-bout, le runtime réel et l'API existent désormais, mais l'exercer authentiquement via la matrice complète nécessite encore le frontend (WP15) |
| GitHub publication | Draft PR [#9](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/9) ouverte contre `main`, non mergée ; branche `stage/09-campaigns` poussée |
| Next stage | `STAGE_10` reste interdite tant que STAGE 09 n'est pas intégrée dans `main` |
| Known limitations | Voir la liste complète des écarts dans `STAGE_09_HANDOFF.md` § « Écarts connus » : frontend (WP15, en cours), qualification live complète (matrice A/B), taggage d'ancestry sur événement Discord réellement généré côté production (blocage externe ADR-008), revue sémantique humaine (rubrique à définir, aucun score fabriqué) |

Le détail d'architecture, les décisions de conception, les 17 findings de la deuxième passe de
remédiation externe et les troisième/quatrième/cinquième/sixième passes (root-cause REQ-MSG-025,
fencing strict, worker réel, orchestration WP12 complète, connexion runtime réelle, API HTTP
complète) sont dans
[`STAGE_09_HANDOFF.md`](../90_handoffs/STAGE_09_HANDOFF.md). STAGE 08 reste
`STAGE_08_INTEGRATED_IN_MAIN` (inchangée par ce travail). STAGE 09 est
`STAGE_09_IMPLEMENTATION_IN_PROGRESS` : fondations, remédiation, dispatch/worker, orchestration
d'activation de campagne, connexion au runtime réel et API HTTP réels et testés avec preuve à
chaque point ; le frontend (en cours) et la qualification live complète restent à construire avant
toute candidate `STAGE_09_COMPLETE_DRAFT_PR_OPEN`. Aucun travail STAGE 10 n'a commencé.
