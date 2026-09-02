# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_09_BLOCKED_TRANSLATION_PROVIDER_UNAVAILABLE` -- **régression délibérée** depuis `STAGE_09_COMPLETE_DRAFT_PR_OPEN` (passe précédente) ; voir « Pourquoi cette régression » ci-dessous |
| Last completed/integrated stage | `STAGE_08_MULTILINGUAL_CONTENT_AND_TRANSLATION_TOPOLOGY` |
| Base main (point de divergence de `stage/09-campaigns`) | `c41b61ae96cdb1d767c8d924212a6466b768ed60` — le commit de `main` d'où la branche STAGE 09 a été créée ; ce n'est **pas** nécessairement le HEAD courant de `main` (voir `git rev-parse main` pour l'état à jour) |
| STAGE 08 functional tested code | `592b94bdee713cfb51e236e29cb979ba60e53ac9` |
| STAGE 08 approved final head | `42274836256d2af449678c239c2db4d8e5e6d01d` |
| STAGE 08 merge commit | `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 08 tag | `stage-08-complete` -> `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 09 branch | `stage/09-campaigns`, créée depuis `main` au commit `c41b61ae96cdb1d767c8d924212a6466b768ed60` |
| STAGE 09 HEAD (cette passe de remédiation) | le commit qui contient exactement ce texte est par construction le dernier commit poussé de cette passe -- voir `git log -1 --format=%H` sur `stage/09-campaigns`, identique au head affiché sur PR #9 après le push de cette passe |
| STAGE 09 PR | Draft PR [#9](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/9), ouverte, non mergée, `DO NOT MERGE — EXTERNAL AUDIT REQUIRED` |
| Last migration | `0032_stage_09` ; chaîne `0013_stage_07 → … → 0021_stage_08 → 0022 → … → 0032_stage_09` (32 migrations Stage09) ; tête unique, inchangée cette passe |
| Pourquoi cette régression | Un audit externe a trouvé un vrai défaut fail-open : l'adaptateur de production `GoogletransCampaignTranslationProvider` construisait `googletrans.Translator()` avec ses défauts (`raise_exception=False`), ce qui fait qu'une panne réelle du transport (HTTP non-200) renvoie silencieusement le sentinel `DUMMY_DATA` de la bibliothèque -- dont le texte traduit est **l'entrée elle-même ré-échoïsée** -- indiscernable d'une traduction réussie. C'est ce défaut qui expliquait la précédente évidence live montrant systématiquement un texte cible identique au texte source. **Corrigé** cette passe (`raise_exception=True` + vérification défensive du statut HTTP réel). Une fois corrigé, une tentative réelle a révélé que `translate.googleapis.com` renvoie HTTP 429 (page de blocage anti-abus Google authentique, capturée en brut) et que `translate.google.com`/variantes renvoient HTTP 403 pour l'IP sortante de ce sandbox -- une vraie indisponibilité externe, stable sur plusieurs tentatives et endpoints, pas un défaut DID. Le code échoue désormais correctement fermé au lieu de mentir ; mais tant que le provider externe reste indisponible, le gate d'acceptation Stage09 de traduction réelle live n'est objectivement pas satisfait |
| STAGE 09 implementation (inchangée structurellement) | Fondations WP1-WP13, remédiation externe (17 findings), orchestration WP12 réelle, connexion runtime réelle, API HTTP complète (WP14), réconciliation de livraison câblée, surfaces d'authoring produit complètes en UI/API, matrice de qualification live Discord (WP16/mission section 20). **Résultat REQ-MSG inchangé : 31/31 `IMPLEMENTED`, 0 `PARTIALLY_IMPLEMENTED`, 0 `NOT_STARTED`** -- REQ-MSG-009 exige structurellement l'existence d'un port/adaptateur de traduction, pas la disponibilité continue d'un tiers externe ; ceci reste distinct du gate d'acceptation de traduction *live* ci-dessous, qui lui n'est PAS satisfait. Voir `STAGE_09_HANDOFF.md` § « État actuel (vérité unique) » pour le détail à jour |
| Data model | Inchangé cette passe ; voir migrations `0022`-`0032_stage_09` |
| Tests status | `pytest backend/tests/unit/test_stage09_translation_adapter.py` : **15 passed** (6 nouveaux tests fail-closed) ; `python scripts/validate_stage.py 09` (défaut), `08`, `--profile failure-injection` : **PASS**, inchangés ; `DID_ALLOW_NETWORK=1 pytest backend/tests/network/test_stage09_translation_network.py` : **5 failed** (réel, honnête -- HTTP 429/disjoncteur ouvert, jamais un faux succès) ; `python scripts/validate_stage.py 09 --profile translation-benchmark --allow-network` : **BLOCKED** (jamais transformé en PASS) |
| Traceability | **31** IDs `IMPLEMENTED`, **0** `PARTIALLY_IMPLEMENTED`, **0** `NOT_STARTED` sur `REQ-MSG-001..031` — inchangé, aucun REQ n'a régressé structurellement (voir la distinction ci-dessus entre implémentation structurelle et gate d'acceptation live) |
| Translation benchmark status | **`BLOCKED`** (rejoué cette passe -- le comportement du provider de production a changé, rendant l'évidence précédente non représentative) : 1248/1248 mesures en échec réel sur les 4 stratégies, 0 traduction obtenue, jamais compté comme un succès. `docs/90_handoffs/evidence/stage09/translation-benchmark.json` |
| Discord live status | `python scripts/validate_stage.py 09 --include-discord-live` : **FAIL** (honnête). `validate_discord_live_stage09.py` reste 5/5 PASS (n'implique aucune traduction). `validate_discord_live_stage09_full_chain.py` (11 groupes) : 9 groupes 100% PASS (rien lié à la traduction), `translation_group_provider_boundary` 100% PASS (ne dépend jamais du provider `googletrans` propre à DID), et `translation_group_did_fanout` échoue désormais honnêtement sur les vérifications qui dépendent réellement d'une traduction obtenue (SOURCE_ONLY reste PASS). Preuve committée : `docs/90_handoffs/evidence/stage09/discord-live-stage09.json` et `discord-live-stage09-full-chain.json` (`"status": "FAIL"`) |
| GitHub publication | Draft PR [#9](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/9) ouverte contre `main`, non mergée ; branche `stage/09-campaigns` poussée |
| Next stage | `STAGE_10` reste `NOT_STARTED` et interdite tant que STAGE 09 n'est pas intégrée dans `main` |
| Known limitations | **(0, bloquante) Provider de traduction `googletrans` propre à DID indisponible** : `GOOGLETRANS_PROVIDER_CURRENTLY_UNAVAILABLE` -- HTTP 429/403 réels prouvés contre l'endpoint Google, hors du contrôle de cette passe technique. (A) **Revue sémantique humaine** : `PENDING_HUMAN_REVIEW`, bloquée en amont par (0) -- le pack documente honnêtement `MACHINE_TRANSLATION_CURRENTLY_UNAVAILABLE` plutôt que de fabriquer une sortie, `docs/90_handoffs/evidence/stage09/human-semantic-review-pack.md`. (B) **Provider de traduction tiers réellement présent dans le sandbox** (distinct de (0), un bot externe attaché à un Translation Group) : `EXTERNAL_SANDBOX_CAPABILITY_NOT_AVAILABLE`, inchangé. (C) **`UNKNOWN_OUTCOME` réel non reproductible à la demande contre Discord** : `NOT_SAFELY_REPRODUCIBLE_LIVE`, inchangé. |

Le détail d'architecture, les décisions de conception, les 17 findings de remédiation externe, et le
détail pass-par-pass sont dans [`STAGE_09_HANDOFF.md`](../90_handoffs/STAGE_09_HANDOFF.md) — sa
section « État actuel (vérité unique) » fait foi pour l'état courant ; ses sections « Nème passe »
sont un journal historique. STAGE 08 reste `STAGE_08_INTEGRATED_IN_MAIN` (inchangée par ce travail).

**STAGE 09 est `STAGE_09_BLOCKED_TRANSLATION_PROVIDER_UNAVAILABLE`, PAS `STAGE_09_COMPLETE_DRAFT_
PR_OPEN`** : un audit externe a trouvé et cette passe a corrigé un vrai défaut fail-open dans
l'adaptateur de traduction de production (voir ci-dessus). La correction elle-même est complète et
techniquement satisfaite (adaptateur fail-closed, smoke réseau étendu et câblé comme gate,
assertions live durcies pour ne plus jamais accepter un écho comme une traduction, benchmark rejoué
honnêtement). Mais le provider externe `googletrans` qu'elle protège désormais correctement est
**actuellement indisponible** dans ce sandbox réseau (prouvé, pas supposé) — ce qui signifie que le
gate d'acceptation Stage09 de traduction réelle live (partie de REQ-MSG-009/011/023/024, une clause
technique/canonique, pas une clause `EXTERNAL_ACCEPTANCE_ITEM`) n'est objectivement pas rempli.
Toutes les autres clauses de la Definition of Done restent satisfaites avec preuve réelle et
inchangées (migrations, engine, UI, fuzz/failure/load, live primitives + 9/11 groupes de la chaîne
complète, 31/31 REQ structurels, régressions 01-08, docs/handoff/state). Cette régression honnête
est préférable à un faux `PASS` qui masquerait la vraie panne provider derrière une évidence qui
semblait déjà propre. Le merge reste hors de portée (`DO NOT MERGE — EXTERNAL AUDIT REQUIRED`).
Aucun travail STAGE 10 n'a commencé.
