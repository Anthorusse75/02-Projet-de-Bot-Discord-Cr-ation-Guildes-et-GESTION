# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_08_COMPLETE_DRAFT_PR_OPEN` |
| Last completed/integrated stage | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Base main | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branch | `stage/08-multilingual-topology` |
| Pull request | `#8`, Draft, non mergée |
| Last migration | `0021_stage_08`; chaîne `0013_stage_07 → 0014 → … → 0021_stage_08`; tête unique et downgrade/re-upgrade PostgreSQL validés |
| Implementation | Correctifs de deep review intégrés et re-vérifiés contre le code actuel : autorité backend, isolation intra-Guild, lifecycle Scope × Language, clone 06→05, drift Gateway, actions UI. La première tentative de qualification live sur sandbox réelle a révélé un défaut de code réel (accès du bot control-plane sur les salons clonés à visibilité restreinte) ; corrigé en `592b94b`, puis la qualification live a PASS sur sandbox propre |
| Data model | Tables STAGE 08 tenant-scoped avec clés/FK composites, FORCE RLS, IDs logiques stables et CAS groupe/routes |
| Tests status | `validate_stage.py` 01/03/05/06/07/08 et `08 --profile e2e` PASS localement et en CI ; `08 --include-discord-live` PASS sur sandbox réelle après correctif (preuve `artifacts/test-evidence/stage-08/live-final.json`, sanitisée, committée) |
| Traceability | Les 43 IDs `REQ-I18N-001..042` + `REQ-I18N-026A` sont `IMPLEMENTED` avec preuve fichier:ligne et test dans `00_REQUIREMENTS_TRACEABILITY.md` / `STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md` ; `VERIFIED` reste réservé à la qualification transverse, conformément à la convention du dépôt |
| Discord live status | `PASS` sur deux Guilds sandbox réelles distinctes, après correctif de l'accès control-plane du bot sur les salons clonés à visibilité restreinte ; zéro secret, zéro identifiant Discord, zéro PII dans la preuve committée ; zéro mutation Discord directe ; zéro intent `MESSAGE_CONTENT` |
| GitHub publication | Draft PR #8 ouverte, non approuvée au merge ; correctifs publiés sans rebase, squash ni force-push ; CI push et CI PR vertes |
| Next stage | `STAGE_09_NOT_STARTED_FORBIDDEN_UNTIL_STAGE08_MERGED` |
| Known limitations | Aucun finding fonctionnel/sécurité ouvert après réaudit et qualification live réelle ; le provider manuel reste un état supporté et vérifié (`PROVIDER_PENDING`/`APPLIED_WITH_PENDING_PROVIDER`) |

Le détail d'architecture, les invariants, le défaut réel découvert par la qualification live et son
correctif sont dans [`STAGE_08_HANDOFF.md`](../90_handoffs/STAGE_08_HANDOFF.md). STAGE 08 est
`STAGE_08_COMPLETE_DRAFT_PR_OPEN` : implémentation, non-live et live sont tous PASS, mais la candidate
reste volontairement en Draft, non mergée, dans l'attente de l'audit externe indépendant final. `main`
reste au dernier stage intégré STAGE 07 et STAGE 09 n'a pas commencé.
