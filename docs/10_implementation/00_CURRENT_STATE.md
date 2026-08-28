# Etat courant

| Champ | Valeur |
|---|---|
| Current stage | `STAGE_07_COMPLETE_DRAFT_PR_OPEN` |
| Last integrated stage | `STAGE_06_CLONE_TEMPLATES_PORTABLE_ARTIFACTS` |
| Base main | `d644015903953ef1dc46626562004746f2208c1c` |
| Stage 07 candidate | `3b81127fa5504ae9e0ad0a75e57da4b5d2362332` |
| Branch | `stage/07-dashboard` |
| Last migration | `0013_stage_07`; parent `0012_stage_06`; une seule tête |
| Implementation | Dashboard React des capacités Stage 01–06; endpoint de capacités réelles user/bot cache-first; dispatcher ActionRegistry partagé; move via DSG + plan/preflight Stage 05; cross-Guild via prévisualisation + transfert Stage 06 exact; Query tenant-keyed; progression REST durable; purge/replay fail-closed; context menu, Left/Right Drag et alternatives clavier; aucun succès optimiste. |
| UI localization | Catalogue `did-ui-v&#49;`, 239 clés, packs EN/FR/DE/ES indépendamment complets au compile-time, scanner réel `*.ts/*.tsx`, AUTO_BROWSER BCP-47, préférence owner authentifiée, packs runtime avec ETag, validation exacte/atomique et rejet HTML/script. Application Commands : `NOT_APPLICABLE`, 0 commande. |
| Tests status | PASS sur `3b81127` : Stage 07 (267 unitaires, 77 intégrations, migrations 0013, frontend 24 tests, OpenAPI/i18n/build), E2E 31/31 dont quatre langues fonctionnelles et axe, puis régressions Stage 01–06 et profils load/failure/security. |
| Traceability | 246/246 REQ et 35 ADR. Les 41 REQ Stage 07 ont été ré-auditées et disposent chacune d’une preuve `IMPLEMENTED`; vérification transverse finale Stage 10. Les `REQ-I18N-*` Stage 08 ne sont pas touchées. |
| Discord live status | `SKIPPED_NOT_VERIFIED` : opt-in sandbox non demandé; aucun REST/mutation Discord ajouté par Stage 07. |
| GitHub publication | Draft PR [#7](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/7), ouverte et non mergée. |
| Known limitations | Provisioning packs runtime réservé opérateur backend/DB, sans endpoint admin public; smokes Discord live non rejoués; aucune Application Command utilisateur. |
| Next stage | Revue externe de STAGE 07; `STAGE_08_NOT_STARTED` |

Le détail est dans [`STAGE_07_HANDOFF.md`](../90_handoffs/STAGE_07_HANDOFF.md). Stage 07 est publiée en Draft PR, non mergée, et attend la revue externe. Stage 08 n'est pas commencée.
