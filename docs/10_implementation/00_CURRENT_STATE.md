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
| Last migration | `0022_stage_09`; chaîne `0013_stage_07 → … → 0021_stage_08 → 0022_stage_09`; tête unique, rehearsal up/down/up validé sur PostgreSQL réel |
| STAGE 09 implementation | Fondations durables réelles et testées : schéma/domaine/repository (WP1, preuve PostgreSQL réelle A/B + FK composite + concurrence de claim), scheduler RRULE/IANA/DST/misfire (WP2, transitions DST réelles Europe/Paris 2026), causalité/AST de condition allowlist (WP3), résolution de cibles/réautorisation/simulation (WP4), MessageModel/AllowedMentionsCompiler/edit-delete sûr (WP5), sender Discord réel + réconciliation nonce (WP6, deux sondes live réelles ayant révélé et corrigé une hypothèse de conception erronée), parseur/protecteur Discord-safe fuzzé (WP7), glossaire à priorité déterministe (WP8), adapter googletrans réel (WP9), benchmark réel 288 appels googletrans (WP10), variantes approuvées (WP11). Pas d'orchestration bout-en-bout, pas de worker/governor câblé (WP13), pas d'API (WP14), pas de frontend (WP15), qualification live limitée à deux sondes ciblées (WP16 partiel) |
| Data model | Tables STAGE 09 : header Control-Plane user-owned (RLS `owner_discord_user_id`) séparé des tables Guild tenant-scoped (RLS `guild_id`, FK composite) ; voir migration `0022_stage_09` |
| Tests status | `pytest backend/tests/unit -k stage09` : 211 passed ; régression unit complète : 538 passed ; `pytest backend/tests/integration/test_stage09_campaigns_postgres.py` (PostgreSQL réel) : 7 passed ; régression integration complète : 107 passed ; `pytest backend/tests/network` (`DID_ALLOW_NETWORK=1`, googletrans réel) : 2 passed ; ruff/ruff format/mypy strict/secret scan/doc validation : PASS sur tout le dépôt ; `python scripts/validate_stage.py 08` : PASS (régression confirmée avant de commencer) ; `python scripts/validate_stage.py 09` : **non ajouté** cette session (écart explicite) |
| Traceability | 15 IDs `IMPLEMENTED`, 13 `PARTIALLY_IMPLEMENTED`, 3 `NOT_STARTED` sur `REQ-MSG-001..031`, chacun avec preuve fichier:ligne et test dans `00_REQUIREMENTS_TRACEABILITY.md` / `STAGE09_REQUIREMENTS_CHECKLIST_LOCAL.md` ; aucune promotion au-delà de la preuve réelle disponible |
| Discord live status | Deux sondes live réelles ciblées (persistance du nonce, déduplication par défaut) sur sandbox Guild A, preuve sanitisée committée dans `docs/90_handoffs/evidence/stage09/nonce-reconciliation-probe.json` ; matrice complète de qualification (section J de la spécification) **non exécutée**, car elle nécessite l'orchestration bout-en-bout qui n'existe pas encore |
| GitHub publication | Aucune PR ouverte à ce stade de la session ; branche `stage/09-campaigns` poussée localement uniquement pour l'instant |
| Next stage | `STAGE_10` reste interdite tant que STAGE 09 n'est pas intégrée dans `main` |
| Known limitations | Voir la liste complète des écarts dans `STAGE_09_HANDOFF.md` § « Écarts connus » : orchestration bout-en-bout, worker/governor, API, frontend, qualification live complète, REQ-MSG-013/018/020/026, `enforce_nonce` indisponible dans `discord.py==2.7.1` (vérifié, documenté) |

Le détail d'architecture, les décisions de conception, les deux découvertes réelles issues des
sondes live (persistance du nonce, déduplication par défaut) et la liste complète des écarts sont
dans [`STAGE_09_HANDOFF.md`](../90_handoffs/STAGE_09_HANDOFF.md). STAGE 08 reste
`STAGE_08_INTEGRATED_IN_MAIN` (inchangée par ce travail). STAGE 09 est
`STAGE_09_IMPLEMENTATION_IN_PROGRESS` : fondations réelles et testées pour 11 des 16 work packages
internes, orchestration/API/frontend/qualification live complète restant à faire avant toute
Draft PR de candidate complète. Aucun travail STAGE 10 n'a commencé.
