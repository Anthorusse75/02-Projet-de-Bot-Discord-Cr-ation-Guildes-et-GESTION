# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_09_IMPLEMENTATION_IN_PROGRESS` |
| Last completed/integrated stage | `STAGE_08_MULTILINGUAL_CONTENT_AND_TRANSLATION_TOPOLOGY` |
| Base main | `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 08 functional tested code | `592b94bdee713cfb51e236e29cb979ba60e53ac9` |
| STAGE 08 approved final head | `42274836256d2af449678c239c2db4d8e5e6d01d` |
| STAGE 08 merge commit | `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 08 tag | `stage-08-complete` -> `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 09 branch | `stage/09-campaigns`, créée depuis `main` au commit `c41b61ae96cdb1d767c8d924212a6466b768ed60` |
| STAGE 09 PR | Draft PR #9, ouverte, non mergée |
| Last migration | `0025_stage_09`; chaîne `0013_stage_07 → … → 0021_stage_08 → 0022 → 0023 → 0024 → 0025_stage_09`; tête unique, rehearsal up/down/up validé sur PostgreSQL réel à chaque étape |
| STAGE 09 implementation | Trois passes cumulées : (1) fondations WP1-WP11 réelles et testées, (2) remédiation externe 17 findings (voir `STAGE_09_HANDOFF.md`), (3) **cette passe** — root-cause de la corruption d'intégrité (REQ-MSG-025 à 100 % réel, plus 97.2 %), fencing de bail strict (expiration + lifecycle au commit, pas seulement le token), service d'autorisation à la création pour targets/trigger sources (1E, réutilise l'AuthorizationService/PermissionEvaluator réels), politique de traduction typée par champ MessageModel (REQ-MSG-013), variables de template à sémantique typée (REQ-MSG-018), dépendance MESSAGE_CONTENT explicite avec blocage/avertissement/fail-closed (REQ-MSG-020), **worker de livraison réel** (`did.campaigns.delivery_worker`, WP13 : claim→SENDING→send→finalize fencé, réconciliation UNKNOWN_OUTCOME réelle, jamais de nonce neuf) câblé au `DiscordWorkloadGovernor` partagé sous un nouveau palier `WorkloadPriority.SEND_CAMPAIGN_MESSAGE`, suite de fairness/charge dédiée, 3 jobs CI Stage09 réels (`stage-09`, `stage-09-failure-injection`, `stage-09-load`). Restent absents : le service d'orchestration amont qui décide QUAND créer une occurrence/livraison depuis un schedule/événement (activation de campagne, WP12), le event consumer Stage03→trigger réel, l'API HTTP (WP14), le frontend (WP15), la matrice de qualification live complète, la sécurité anti double-traduction Translation Group bout-en-bout, la revue sémantique humaine |
| Data model | Tables STAGE 09 : header Control-Plane user-owned (RLS `owner_discord_user_id`) séparé des tables Guild tenant-scoped (RLS `guild_id`, FK composite) ; voir migrations `0022`-`0025_stage_09` |
| Tests status | `pytest backend/tests/unit -k stage09` : **306 passed** ; régression unit complète : **633 passed** ; `pytest backend/tests/integration -k stage09` (PostgreSQL réel) : **39 passed** ; régression integration complète : **139 passed** ; `pytest backend/tests/load -k stage09 -m load` : **3 passed** (fairness gouverneur) ; `pytest backend/tests/network` (`DID_ALLOW_NETWORK=1`, googletrans réel) : 2 passed ; ruff/ruff format/mypy strict/secret scan/doc validation : PASS sur tout le dépôt ; `python scripts/validate_stage.py 08` : PASS (régression, non affectée) ; `python scripts/validate_stage.py 09` : **PASS** ; `python scripts/validate_stage.py 09 --profile failure-injection` : **PASS** ; `python scripts/validate_stage.py 09 --profile translation-benchmark --allow-network` : **PASS**, intégrité 100 % (stratégie de production) |
| Traceability | **22** IDs `IMPLEMENTED`, **9** `PARTIALLY_IMPLEMENTED`, **0** `NOT_STARTED` sur `REQ-MSG-001..031` (passe précédente : 16/12/3). Cette passe a fait passer REQ-MSG-003 (autorisation cross-Guild réellement câblée), REQ-MSG-013, REQ-MSG-018, REQ-MSG-020, REQ-MSG-025 (intégrité réelle 100 %), REQ-MSG-026 (requalifié — SHOULD conditionnel honnêtement satisfait par la non-variation appuyée sur preuve) à `IMPLEMENTED`. Chaque ligne pointe vers du code de production, des tests et une preuve reproductible dans `00_REQUIREMENTS_TRACEABILITY.md` / `STAGE09_REQUIREMENTS_CHECKLIST_LOCAL.md` |
| Discord live status | `scripts/validate_discord_live_stage09.py` exécuté avec `--include` sur sandbox Guild A réel : **5/5 scénarios PASS** (envoi immédiat allowed_mentions=none, edit possédé, delete possédé, dédup nonce, nonce distinct) via le vrai `DiscordPyMessageSender` ; preuve sanitisée committée (`docs/90_handoffs/evidence/stage09/discord-live-stage09.json`) ; matrice complète de qualification (Guild A/B, scheduler, Translation Groups, event triggers cross-Guild, variantes approuvées) **non exécutée** — nécessite l'orchestration bout-en-bout et l'API/frontend encore absents |
| GitHub publication | Draft PR [#9](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/9) ouverte contre `main`, non mergée ; branche `stage/09-campaigns` poussée |
| Next stage | `STAGE_10` reste interdite tant que STAGE 09 n'est pas intégrée dans `main` |
| Known limitations | Voir la liste complète des écarts dans `STAGE_09_HANDOFF.md` § « Écarts connus » : service d'orchestration/activation de campagne (WP12), event consumer Stage03 réel, API (WP14), frontend (WP15), qualification live complète (matrice A/B), sécurité anti double-traduction Translation Group bout-en-bout, revue sémantique humaine (rubrique à définir, aucun score fabriqué) |

Le détail d'architecture, les décisions de conception, les 17 findings de la deuxième passe de
remédiation externe et cette troisième passe (root-cause REQ-MSG-025, fencing strict, worker réel,
1E) sont dans [`STAGE_09_HANDOFF.md`](../90_handoffs/STAGE_09_HANDOFF.md). STAGE 08 reste
`STAGE_08_INTEGRATED_IN_MAIN` (inchangée par ce travail). STAGE 09 est
`STAGE_09_IMPLEMENTATION_IN_PROGRESS` : fondations, remédiation et dispatch/worker réels et testés
avec preuve à chaque point ; l'orchestration d'activation de campagne, l'API, le frontend et la
qualification live complète restent à construire avant toute candidate
`STAGE_09_COMPLETE_DRAFT_PR_OPEN`. Aucun travail STAGE 10 n'a commencé.
