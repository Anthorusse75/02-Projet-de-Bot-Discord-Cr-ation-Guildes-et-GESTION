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
| Last migration | `0024_stage_09`; chaîne `0013_stage_07 → … → 0021_stage_08 → 0022 → 0023 → 0024_stage_09`; tête unique, rehearsal up/down/up validé sur PostgreSQL réel à chaque étape |
| STAGE 09 implementation | Fondations durables réelles et testées (WP1-WP11) **plus une passe de remédiation externe intégrée** (17 findings — voir `STAGE_09_HANDOFF.md`) : intégrité relationnelle DB (FK composites owner+campaign, campaign+target/occurrence), curseur scheduler naive/aware corrigé (round-trip PostgreSQL réel traversant la DST 2026 réelle), fencing de bail schedule/delivery, AST de condition bornée et validée avant persistance, correction majeure `enforce_nonce` (disponible, erreur d'investigation antérieure corrigée), benchmark refait sur la matrice complète FR/EN/DE/ES (516 appels réels) avec un validateur renforcé ayant révélé une corruption réelle (espacement autour des URLs, toujours détectée/bloquée), tiers de glossaire GUILD ajouté, correctif `REPLACE_ALL`, `validate_stage.py 09` réel et exécuté avec succès, qualification live Stage09 réelle (5/5 scénarios PASS). Pas d'orchestration bout-en-bout, pas de worker/governor câblé (WP13), pas d'API (WP14), pas de frontend (WP15) |
| Data model | Tables STAGE 09 : header Control-Plane user-owned (RLS `owner_discord_user_id`) séparé des tables Guild tenant-scoped (RLS `guild_id`, FK composite) ; voir migrations `0022`-`0024_stage_09` |
| Tests status | `pytest backend/tests/unit -k stage09` : **255 passed** ; régression unit complète : **582 passed** ; `pytest backend/tests/integration/test_stage09_campaigns_postgres.py` (PostgreSQL réel) : **26 passed** ; régression integration complète : **126 passed** ; `pytest backend/tests/network` (`DID_ALLOW_NETWORK=1`, googletrans réel) : 2 passed ; ruff/ruff format/mypy strict/secret scan/doc validation : PASS sur tout le dépôt ; `python scripts/validate_stage.py 08` : PASS (régression, non affectée) ; `python scripts/validate_stage.py 09` : **PASS** (ajouté et exécuté avec succès cette passe de remédiation) |
| Traceability | **16** IDs `IMPLEMENTED`, **12** `PARTIALLY_IMPLEMENTED`, 3 `NOT_STARTED` sur `REQ-MSG-001..031` (mis à jour après remédiation : REQ-MSG-029 `PARTIALLY_IMPLEMENTED → IMPLEMENTED` ; REQ-MSG-025 reste `PARTIALLY_IMPLEMENTED` avec preuve honnête corrigée, pas 100% d'intégrité mais échec fermé 100% fiable), chacun avec preuve fichier:ligne et test dans `00_REQUIREMENTS_TRACEABILITY.md` / `STAGE09_REQUIREMENTS_CHECKLIST_LOCAL.md` |
| Discord live status | `scripts/validate_discord_live_stage09.py` exécuté avec `--include` sur sandbox Guild A réel : **5/5 scénarios PASS** (envoi immédiat allowed_mentions=none, edit possédé, delete possédé, dédup nonce, nonce distinct) via le vrai `DiscordPyMessageSender` ; preuve sanitisée committée (`docs/90_handoffs/evidence/stage09/discord-live-stage09.json`) ; matrice complète de qualification (section J) **non exécutée**, nécessite l'orchestration bout-en-bout absente |
| GitHub publication | Draft PR [#9](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/9) ouverte contre `main`, non mergée ; branche `stage/09-campaigns` poussée |
| Next stage | `STAGE_10` reste interdite tant que STAGE 09 n'est pas intégrée dans `main` |
| Known limitations | Voir la liste complète des écarts dans `STAGE_09_HANDOFF.md` § « Écarts connus » : orchestration bout-en-bout, worker/governor, API, frontend, qualification live complète (matrice), REQ-MSG-013/018/020/026, corruption résiduelle d'espacement autour des URLs (REQ-MSG-025, toujours détectée/bloquée, format de placeholder à améliorer) |

Le détail d'architecture, les décisions de conception, les 17 findings de la passe de remédiation
externe (dont deux corrections majeures : `enforce_nonce` réellement disponible, intégrité de
traduction réelle mesurée à 97.2%/66.7% et non 100%) et la liste complète des écarts sont dans
[`STAGE_09_HANDOFF.md`](../90_handoffs/STAGE_09_HANDOFF.md). STAGE 08 reste
`STAGE_08_INTEGRATED_IN_MAIN` (inchangée par ce travail). STAGE 09 est
`STAGE_09_IMPLEMENTATION_IN_PROGRESS` : fondations réelles et testées pour 11 des 16 work packages
internes plus une remédiation externe intégrée avec preuve réelle à chaque point, orchestration/
API/frontend/qualification live complète restant à faire avant toute candidate complète. Aucun
travail STAGE 10 n'a commencé.
