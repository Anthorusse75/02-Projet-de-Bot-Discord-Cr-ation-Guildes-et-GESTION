# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_08_IMPLEMENTATION_IN_PROGRESS` |
| Last completed/integrated stage | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Base main | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branch | `stage/08-multilingual-topology` |
| Pull request | `#8`, Draft, non mergée |
| Last migration | `0021_stage_08`; chaîne `0013_stage_07 → 0014 → … → 0021_stage_08`; tête unique et downgrade/re-upgrade PostgreSQL validés |
| Implementation | Correctifs de deep review intégrés et re-vérifiés contre le code actuel : autorité backend, isolation intra-Guild, lifecycle Scope × Language, clone 06→05, drift Gateway, actions UI. Preuve live réelle bloquée par nettoyage sandbox externe (non-code) |
| Data model | Tables STAGE 08 tenant-scoped avec clés/FK composites, FORCE RLS, IDs logiques stables et CAS groupe/routes |
| Tests status | `validate_stage.py` 01/03/05/06/07/08 et `08 --profile e2e` PASS localement et en CI (run push `adafad8`) ; `08 --include-discord-live` bloqué (voir Discord live status) |
| Traceability | Les 43 IDs `REQ-I18N-001..042` + `REQ-I18N-026A` sont `IMPLEMENTED` avec preuve fichier:ligne et test réévaluée dans `00_REQUIREMENTS_TRACEABILITY.md` / `STAGE08_REQUIREMENTS_CHECKLIST_LOCAL.md` ; `VERIFIED` reste réservé à la qualification transverse |
| Discord live status | `BLOCKED_SANDBOX_RECOVERY` : sandbox Guild B conserve 4 salons `DID-STAGE08-TEST-*` d'une exécution antérieure au correctif d'ordre des overwrites ; 2 refusent `VIEW_CHANNEL`/`MANAGE_CHANNELS` au bot au niveau salon. Guild A propre. Requiert nettoyage manuel ou nouvelle Guild B avant re-run |
| GitHub publication | Draft PR #8 ouverte, non approuvée au merge ; correctifs publiés sans rebase, squash ni force-push ; CI push verte |
| Next stage | `STAGE_09_NOT_STARTED_FORBIDDEN_UNTIL_STAGE08_MERGED` |
| Known limitations | Aucun finding fonctionnel/sécurité ouvert après réaudit ; seul `BLOCKED_SANDBOX_RECOVERY` (nettoyage sandbox externe) reste avant preuve live complète ; le provider manuel reste un état supporté et vérifié (`PROVIDER_PENDING`/`APPLIED_WITH_PENDING_PROVIDER`) |

Le détail d’architecture, les invariants et les preuves sont dans
[`STAGE_08_HANDOFF.md`](../90_handoffs/STAGE_08_HANDOFF.md). STAGE 08 reste en implémentation active
(`STAGE_08_IMPLEMENTATION_IN_PROGRESS`) uniquement à cause du blocage sandbox live externe ; `main` reste
au dernier stage intégré STAGE 07 et STAGE 09 n’a pas commencé.
