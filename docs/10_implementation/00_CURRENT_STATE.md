# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_09_READY_NOT_STARTED` |
| Last completed/integrated stage | `STAGE_08_MULTILINGUAL_CONTENT_AND_TRANSLATION_TOPOLOGY` |
| Base main | `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 08 functional tested code | `592b94bdee713cfb51e236e29cb979ba60e53ac9` |
| STAGE 08 approved final head | `42274836256d2af449678c239c2db4d8e5e6d01d` |
| STAGE 08 merge commit | `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| STAGE 08 tag | `stage-08-complete` -> `d6a8425cff6606cace2ac89705b71519b6a308b1` |
| Branch | `stage/08-multilingual-topology` |
| Last migration | `0021_stage_08`; chaîne `0013_stage_07 → 0014 → … → 0021_stage_08`; tête unique et downgrade/re-upgrade PostgreSQL validés |
| Implementation | Correctifs de deep review intégrés et re-vérifiés contre le code actuel : autorité backend, isolation intra-Guild, lifecycle Scope × Language, clone 06→05, drift Gateway, actions UI. La première tentative de qualification live sur sandbox réelle a révélé un défaut de code réel (accès du bot control-plane sur les salons clonés à visibilité restreinte) ; corrigé en `592b94b`, puis la qualification live a PASS sur sandbox propre. Le code fonctionnel testé et mergé est celui de `592b94b`, inchangé jusqu'au head approuvé `4227483` |
| Data model | Tables STAGE 08 tenant-scoped avec clés/FK composites, FORCE RLS, IDs logiques stables et CAS groupe/routes |
| Tests status | `validate_stage.py` 01/03/05/06/07/08 et `08 --profile e2e` PASS localement et en CI ; `08 --include-discord-live` PASS sur sandbox réelle après correctif, testé sur `592b94b` (preuve sanitisée committée dans `docs/90_handoffs/evidence/stage08/discord-live-stage08.json`) |
| Traceability | Les 43 IDs `REQ-I18N-001..042` + `REQ-I18N-026A` sont `IMPLEMENTED` avec preuve fichier:ligne et test dans `00_REQUIREMENTS_TRACEABILITY.md` / `STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md` ; `VERIFIED` reste réservé à la qualification transverse, conformément à la convention du dépôt |
| Discord live status | `PASS` sur deux Guilds sandbox réelles distinctes, testé sur le commit fonctionnel `592b94b`, après correctif de l'accès control-plane du bot sur les salons clonés à visibilité restreinte ; zéro secret, zéro identifiant Discord, zéro PII dans la preuve committée ; zéro mutation Discord directe ; zéro intent `MESSAGE_CONTENT` |
| GitHub publication | PR [#8](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/8) intégrée dans `main` par merge commit (pas de squash, pas de rebase) ; branche `stage/08-multilingual-topology` conservée |
| Next stage | `STAGE_09_READY_NOT_STARTED`; autorisée mais non commencée |
| Known limitations | Aucun finding fonctionnel/sécurité ouvert après réaudit et qualification live réelle ; le provider manuel reste un état supporté et vérifié (`PROVIDER_PENDING`/`APPLIED_WITH_PENDING_PROVIDER`) |

Le détail d'architecture, les invariants, le défaut réel découvert par la qualification live et son
correctif sont dans [`STAGE_08_HANDOFF.md`](../90_handoffs/STAGE_08_HANDOFF.md). STAGE 08 est
`STAGE_08_INTEGRATED_IN_MAIN` : implémentation, non-live et live sont tous PASS, l'audit externe
indépendant a approuvé le head `4227483`, et la PR #8 est mergée dans `main` par un vrai merge commit
(`d6a8425`), tagué `stage-08-complete`. STAGE 09 est autorisée mais n'a pas commencé.
