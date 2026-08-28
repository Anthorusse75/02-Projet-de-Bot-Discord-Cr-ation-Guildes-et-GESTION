# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_07_COMPLETE_DRAFT_PR_PENDING` |
| Last completed stage | `STAGE_07_DASHBOARD_RUNTIME_UI_LOCALIZATION` |
| Base main | `d644015903953ef1dc46626562004746f2208c1c` |
| STAGE 07 tested code | `50832be79c390d03f2bdb62570f61ccd2835925e` |
| Branch | `stage/07-dashboard` |
| Last migration | `0013_stage_07`; parent `0012_stage_06`; une seule tête |
| Implementation | Dashboard React des capacités Stage 01–06; client OpenAPI généré; Query tenant-keyed; purge fail-closed au switch; WebSocket version/séquence/tenant; ActionRegistry partagé; context menu, Left/Right Drag et alternatives clavier; plans/jobs sans succès optimiste. |
| UI localization | Catalogue `did-ui-v&#49;`, 153 clés, packs EN/FR/DE/ES complets, AUTO_BROWSER BCP-47, override owner, packs runtime PostgreSQL en lecture publique avec ETag, validation exacte/atomique et rejet HTML/script. Application Commands : `NOT_APPLICABLE`, 0 commande. |
| Tests status | PASS sur `50832be` : Stage 07 (264 unitaires, 77 intégrations, migrations 0013, frontend 14 tests, OpenAPI/i18n/build), E2E 5/5 quatre langues et axe, puis régressions Stage 01–06 et profils load/failure/security. |
| Traceability | 246/246 REQ et 35 ADR. REQ Stage 07 `IMPLEMENTED`; vérification transverse finale Stage 10. Les `REQ-I18N-*` Stage 08 ne sont pas touchées. |
| Discord live status | `SKIPPED_NOT_VERIFIED` : opt-in sandbox non demandé; aucun REST/mutation Discord ajouté par Stage 07. |
| GitHub publication | Push et Draft PR après le commit documentaire final; ne pas merger. |
| Known limitations | Provisioning packs runtime réservé opérateur backend/DB, sans endpoint admin public; smokes Discord live non rejoués; termes Discord bruts conservés dans les vues expert; aucune Application Command utilisateur. |
| Next stage | Revue externe de STAGE 07; `STAGE_08_NOT_STARTED` |

Le détail est dans [`STAGE_07_HANDOFF.md`](../90_handoffs/STAGE_07_HANDOFF.md). Stage 07 est terminée localement, doit être publiée en Draft PR et ne doit pas être mergée par Codex. Stage 08 n'est pas commencée.
