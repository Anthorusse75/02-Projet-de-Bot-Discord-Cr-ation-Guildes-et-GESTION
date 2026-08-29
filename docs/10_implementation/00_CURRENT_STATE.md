# État courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_08_COMPLETE_DRAFT_PR_OPEN` |
| Last completed/integrated stage | `STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS` |
| Base main | `252a4661195a3868acd04a2987453e23fc6ee4ff` |
| Branch | `stage/08-multilingual-topology` |
| Pull request | `#8`, Draft, non mergée |
| Last migration | `0015_stage_08`; parent `0014_stage_08`, puis `0013_stage_07`; tête unique et downgrade/re-upgrade PostgreSQL validés |
| Implementation | WP2 à WP20 terminés : services/application, API, visibilité Scope × Language, provider non invasif, drift, clone, workspace, actions et validation |
| Data model | Tables STAGE 08 tenant-scoped avec clés/FK composites, FORCE RLS, IDs logiques stables et CAS groupe/routes |
| Tests status | Gates canoniques STAGE 08, E2E et live PASS ; 294 unitaires backend, 88 intégrations, 28 frontend et 39 Playwright pour la candidate |
| Traceability | Les 43 IDs `REQ-I18N-001..042` + `REQ-I18N-026A` sont `IMPLEMENTED`, avec emplacement et preuve ; qualification `VERIFIED` réservée à la politique transverse |
| Discord live status | `PASS` sur Guild A/B réelles, intent GUILDS uniquement, budgets/visibilité/provider/clone contrôlés, zéro secret/PII/ID Discord dans la preuve et zéro mutation directe |
| GitHub publication | Candidate destinée à la Draft PR #8 ; CI dédiée STAGE 08 et STAGE 08 E2E ajoutée ; aucun merge autorisé |
| Next stage | `STAGE_09_NOT_STARTED_FORBIDDEN_UNTIL_STAGE08_MERGED` |
| Known limitations | Le bot provider existant reste `MANUAL_CONFIGURATION_REQUIRED` lorsqu’aucune interface sûre d’automation n’est disponible ; comportement supporté, sans faux READY |

Le détail d’architecture, les invariants et les preuves sont dans
[`STAGE_08_HANDOFF.md`](../90_handoffs/STAGE_08_HANDOFF.md). STAGE 08 est une candidate complète publiée
uniquement sur sa branche et sa Draft PR. `main` reste au dernier stage intégré STAGE 07 ; STAGE 09 n’a
pas commencé.
