# Discord Infrastructure Designer — Audit d’implémentation

> Snapshot audité : `stage/10-acceptance` @ `dfd6bb57517806f2b68144818714755c82e0871c`  
> Périmètre : **389 exigences** — 246 historiques + 143 détaillées.

## Méthode

`CONFORME` = comportement et preuves suffisants; `PARTIEL` = une partie existe mais un critère manque; `ABSENT` = comportement non trouvé; `NON DÉMONTRÉ` = éléments plausibles mais preuve insuffisante. Un fichier/classe/écran seul ne vaut pas conformité.

Libellés canoniques : `00_REQUIREMENTS_TRACEABILITY.md` (246 historiques) et `DISCORD_INFRA_DESIGNER_EXIGENCES_DETAILLEES_AUDIT_CONFORMITE.md` (143 détaillées).

## Résultat

| Statut | Nb |
|---|---:|
| CONFORME | 265 |
| PARTIEL | 40 |
| ABSENT | 69 |
| NON DÉMONTRÉ | 15 |
| **Total** | **389** |

Le socle historique est à **244 CONFORME / 2 PARTIEL** (`REQ-BOT-005`, `REQ-TEST-003`). Les écarts nouveaux portent surtout sur Policies, Wizards, UX nouvelle, reprise inter-session et templates produit.

## PARTIEL — ce qui est fait / ce qui manque

| ID | Implémenté | Manque |
|---|---|---|
| REQ-BOT-005 | API backend réelle par bot/salon (lecture/écriture), cache-derived, testée. | La visualisation dashboard demandée reste différée. |
| REQ-TEST-003 | Harness et rapports live A/B prévus/intégrés dans Stage10. | Pas d’agrégat live A/B valide du run courant: credentials sandbox externes indisponibles. |
| REQ-POL-013 | Les policies spécialisées inspectées sont déterministes | pas de moteur générique. |
| REQ-POL-040 | Permission engine actuel sait représenter incomplete/unknown | pas de policy engine générique. |
| REQ-POL-053 | message_content_policy.py et translation_policy.py inspectés | absence de moteur générique confirmée. |
| REQ-WIZ-012 | Principe présent dans le référentiel et capability checks existants | flux Wizard non démontré. |
| REQ-UXN-004 | Référentiel distingue les concepts | conformité de chaque écran non auditée. |
| REQ-UXN-009 | Moteur multi-rôles conforme | audit de toutes les UIs non réalisé. |
| REQ-UXN-012 | Pile UI i18n/Unicode existe | workflow de nommage dédié non démontré. |
| REQ-UXN-015 | Validation structurelle existe globalement | suggestions de naming non implémentées. |
| REQ-OPS-003 | Persistance backend démontrée | UX de reprise après nouvelle session non démontrée. |
| REQ-OPS-004 | OutboxScreen/PlanDrawer existent | sémantique “centre d’opérations” et reprise session non totalement prouvées. |
| REQ-OPS-005 | PlanState/OperationState riches existent | équivalence UX complète non auditée. |
| REQ-OPS-006 | Persistance des résultats/erreurs plan présente | UX globale non démontrée. |
| REQ-OPS-007 | UNKNOWN_OUTCOME/reconciliation existent | UI complète non auditée. |
| REQ-OPS-008 | PlanState.DRAFT existe | usage universel hors plan non démontré. |
| REQ-OPS-009 | Pipeline plan existe | tous types de brouillons non unifiés. |
| REQ-OPS-014 | REQ-UX-006 et plan progress existent | persistance inter-session UI non complètement prouvée. |
| REQ-TPL-001 | Stage06 possède des templates portables | aucun catalogue UX préconstruit clairement démontré. |
| REQ-TPL-002 | Pipeline portable/preflight existe | UX d’adaptation préconstruite non prouvée. |
| REQ-TPL-003 | Portabilité rapporte mappings | écran dédié de template infrastructure non prouvé. |
| REQ-TPL-004 | COPY_AS_NEW sait créer | expérience de suggestion non démontrée. |
| REQ-TPL-007 | REQ-DUP-019 couvre portabilité de définitions | moteur générique de Policy absent. |
| REQ-TPL-009 | `template_id`, `schema_version` et `content_hash` donnent identité et empreinte reproductible. | Pas de révision métier publiée/sélectionnable (v1/v2 immuables) démontrée. |
| REQ-TPL-010 | Portabilité converge sur planning | Wizard absent. |
| REQ-REUSE-001 | Architecture recommande dnd-kit, Radix/shadcn, i18next, discord.py, etc. | processus formel non démontré. |
| REQ-REUSE-005 | uv.lock/npm audit et Stage10 existent | règle universelle non prouvée. |
| REQ-REUSE-007 | discord.py et TranslationProvider sont abstraits | pratique à généraliser. |
| REQ-REUSE-009 | dnd-kit et primitives UI sont prévus/utilisés | emoji picker pas encore présent. |
| REQ-REUSE-010 | Redis/streams/locks et abstractions existent | audit exhaustif non réalisé. |
| REQ-REUSE-012 | TranslationProvider/Discord adapter sont de bons exemples | pas prouvé partout. |
| REQ-PERMX-010 | Moteur canonique existe | Wizard/Policy Engine absents. |
| REQ-QA-001 | Règle d’audit adoptée ici | traçabilité historique parfois plus large que preuve réinspectée. |
| REQ-QA-003 | Permissions/planning fortement testés | futur Policy Engine absent. |
| REQ-QA-004 | Historique Stage10 affirme couverture | pas tout réexécuté. |
| REQ-QA-005 | Suite importante déclarée | audit indépendant exhaustif non reproduit. |
| REQ-QA-006 | Stage07-10 E2E existent | nouveaux Wizards/Policies non couverts. |
| REQ-QA-010 | artifacts/stage10-audit/skipped-tests.txt montre des scans conditionnels/skip. | Critère restant non prouvé: Aucun skip sérieux/critique inexpliqué dans la gate finale. |
| REQ-QA-011 | REQ-TEST-003 dans registre: implémenté | agrégat courant non fourni à ce rendu. |
| REQ-QA-012 | Registre contient preuves, | leur réexécution indépendante n’a pas été exhaustive ici. |

## Matrice exhaustive de statut

### CONFORME

- `REQ-INST-001`, `REQ-INST-002`, `REQ-INST-003`, `REQ-INST-004`, `REQ-INST-005`, `REQ-INST-006`, `REQ-INST-007`, `REQ-TEN-001`, `REQ-TEN-002`, `REQ-TEN-003`, `REQ-TEN-004`, `REQ-TEN-005`, `REQ-TEN-006`, `REQ-TEN-007`, `REQ-TEN-008`, `REQ-TEN-009`, `REQ-TEN-010`, `REQ-TEN-011`, `REQ-TEN-012`, `REQ-TEN-013`
- `REQ-TEN-014`, `REQ-STR-001`, `REQ-STR-002`, `REQ-STR-003`, `REQ-STR-004`, `REQ-STR-005`, `REQ-STR-006`, `REQ-STR-007`, `REQ-STR-008`, `REQ-STR-009`, `REQ-STR-010`, `REQ-STR-011`, `REQ-STR-012`, `REQ-STR-013`, `REQ-PERM-001`, `REQ-PERM-002`, `REQ-PERM-003`, `REQ-PERM-004`, `REQ-PERM-005`, `REQ-PERM-006`
- `REQ-PERM-007`, `REQ-PERM-008`, `REQ-PERM-009`, `REQ-PLAN-001`, `REQ-PLAN-002`, `REQ-PLAN-003`, `REQ-PLAN-004`, `REQ-PLAN-005`, `REQ-PLAN-006`, `REQ-PLAN-007`, `REQ-PLAN-008`, `REQ-PLAN-009`, `REQ-PLAN-010`, `REQ-PLAN-011`, `REQ-PLAN-012`, `REQ-PLAN-013`, `REQ-PLAN-014`, `REQ-PLAN-015`, `REQ-PLAN-016`, `REQ-DUP-001`
- `REQ-DUP-002`, `REQ-DUP-003`, `REQ-DUP-004`, `REQ-DUP-005`, `REQ-DUP-006`, `REQ-DUP-007`, `REQ-DUP-008`, `REQ-DUP-009`, `REQ-DUP-010`, `REQ-DUP-011`, `REQ-DUP-012`, `REQ-DUP-013`, `REQ-DUP-014`, `REQ-DUP-015`, `REQ-DUP-016`, `REQ-DUP-017`, `REQ-DUP-018`, `REQ-DUP-019`, `REQ-BOT-001`, `REQ-BOT-002`
- `REQ-BOT-003`, `REQ-BOT-004`, `REQ-BOT-006`, `REQ-BOT-007`, `REQ-AUTH-001`, `REQ-AUTH-002`, `REQ-AUTH-003`, `REQ-AUTH-004`, `REQ-AUTH-005`, `REQ-AUTH-006`, `REQ-AUTH-007`, `REQ-AUTH-008`, `REQ-AUTH-009`, `REQ-AUTH-010`, `REQ-AUTH-011`, `REQ-AUTH-012`, `REQ-AUTH-013`, `REQ-AUTH-014`, `REQ-GW-001`, `REQ-GW-002`
- `REQ-GW-003`, `REQ-GW-004`, `REQ-GW-005`, `REQ-GW-006`, `REQ-GW-007`, `REQ-GW-008`, `REQ-AUD-001`, `REQ-AUD-002`, `REQ-AUD-003`, `REQ-AUD-004`, `REQ-AUD-005`, `REQ-AUD-006`, `REQ-DATA-001`, `REQ-DATA-002`, `REQ-UX-001`, `REQ-UX-002`, `REQ-UX-003`, `REQ-UX-004`, `REQ-UX-005`, `REQ-UX-006`
- `REQ-UX-007`, `REQ-UX-CTX-001`, `REQ-UX-CTX-002`, `REQ-UX-CTX-003`, `REQ-UX-CTX-004`, `REQ-UX-CTX-005`, `REQ-I18N-001`, `REQ-I18N-002`, `REQ-I18N-003`, `REQ-I18N-004`, `REQ-I18N-005`, `REQ-I18N-006`, `REQ-I18N-007`, `REQ-I18N-008`, `REQ-I18N-009`, `REQ-I18N-010`, `REQ-I18N-011`, `REQ-I18N-012`, `REQ-I18N-013`, `REQ-I18N-014`
- `REQ-I18N-015`, `REQ-I18N-016`, `REQ-I18N-017`, `REQ-I18N-018`, `REQ-I18N-019`, `REQ-I18N-020`, `REQ-I18N-021`, `REQ-I18N-022`, `REQ-I18N-023`, `REQ-I18N-024`, `REQ-I18N-025`, `REQ-I18N-026`, `REQ-I18N-026A`, `REQ-I18N-027`, `REQ-I18N-028`, `REQ-I18N-029`, `REQ-I18N-030`, `REQ-I18N-031`, `REQ-I18N-032`, `REQ-I18N-033`
- `REQ-I18N-034`, `REQ-I18N-035`, `REQ-I18N-036`, `REQ-I18N-037`, `REQ-I18N-038`, `REQ-I18N-039`, `REQ-I18N-040`, `REQ-I18N-041`, `REQ-I18N-042`, `REQ-CACHE-001`, `REQ-CACHE-002`, `REQ-CACHE-003`, `REQ-CACHE-004`, `REQ-CACHE-005`, `REQ-CACHE-006`, `REQ-CACHE-007`, `REQ-CACHE-008`, `REQ-CACHE-009`, `REQ-CACHE-010`, `REQ-CACHE-011`
- `REQ-CACHE-012`, `REQ-CACHE-013`, `REQ-RATE-001`, `REQ-RATE-002`, `REQ-RATE-003`, `REQ-RATE-004`, `REQ-RATE-005`, `REQ-RATE-006`, `REQ-UI18N-001`, `REQ-UI18N-002`, `REQ-UI18N-003`, `REQ-UI18N-004`, `REQ-UI18N-005`, `REQ-UI18N-006`, `REQ-UI18N-007`, `REQ-UI18N-008`, `REQ-UI18N-009`, `REQ-UI18N-010`, `REQ-UI18N-011`, `REQ-UI18N-012`
- `REQ-UI18N-013`, `REQ-UI18N-014`, `REQ-UI18N-015`, `REQ-UI18N-016`, `REQ-UI18N-017`, `REQ-UI18N-018`, `REQ-UI18N-019`, `REQ-UI18N-020`, `REQ-UI18N-021`, `REQ-MSG-001`, `REQ-MSG-002`, `REQ-MSG-003`, `REQ-MSG-004`, `REQ-MSG-005`, `REQ-MSG-006`, `REQ-MSG-007`, `REQ-MSG-008`, `REQ-MSG-009`, `REQ-MSG-010`, `REQ-MSG-011`
- `REQ-MSG-012`, `REQ-MSG-013`, `REQ-MSG-014`, `REQ-MSG-015`, `REQ-MSG-016`, `REQ-MSG-017`, `REQ-MSG-018`, `REQ-MSG-019`, `REQ-MSG-020`, `REQ-MSG-021`, `REQ-MSG-022`, `REQ-MSG-023`, `REQ-MSG-024`, `REQ-MSG-025`, `REQ-MSG-026`, `REQ-MSG-027`, `REQ-MSG-028`, `REQ-MSG-029`, `REQ-MSG-030`, `REQ-MSG-031`
- `REQ-TEST-001`, `REQ-TEST-002`, `REQ-TEST-004`, `REQ-TEST-005`, `REQ-UXN-001`, `REQ-UXN-002`, `REQ-UXN-008`, `REQ-UXN-018`, `REQ-OPS-001`, `REQ-OPS-002`, `REQ-OPS-013`, `REQ-TPL-005`, `REQ-TPL-006`, `REQ-TPL-008`, `REQ-REUSE-008`, `REQ-PERMX-001`, `REQ-PERMX-002`, `REQ-PERMX-003`, `REQ-PERMX-004`, `REQ-PERMX-005`
- `REQ-PERMX-006`, `REQ-PERMX-007`, `REQ-PERMX-008`, `REQ-PERMX-009`, `REQ-QA-002`

### PARTIEL

- `REQ-BOT-005`, `REQ-TEST-003`, `REQ-POL-013`, `REQ-POL-040`, `REQ-POL-053`, `REQ-WIZ-012`, `REQ-UXN-004`, `REQ-UXN-009`, `REQ-UXN-012`, `REQ-UXN-015`, `REQ-OPS-003`, `REQ-OPS-004`, `REQ-OPS-005`, `REQ-OPS-006`, `REQ-OPS-007`, `REQ-OPS-008`, `REQ-OPS-009`, `REQ-OPS-014`, `REQ-TPL-001`, `REQ-TPL-002`
- `REQ-TPL-003`, `REQ-TPL-004`, `REQ-TPL-007`, `REQ-TPL-009`, `REQ-TPL-010`, `REQ-REUSE-001`, `REQ-REUSE-005`, `REQ-REUSE-007`, `REQ-REUSE-009`, `REQ-REUSE-010`, `REQ-REUSE-012`, `REQ-PERMX-010`, `REQ-QA-001`, `REQ-QA-003`, `REQ-QA-004`, `REQ-QA-005`, `REQ-QA-006`, `REQ-QA-010`, `REQ-QA-011`, `REQ-QA-012`

### ABSENT

- `REQ-POL-001`, `REQ-POL-002`, `REQ-POL-003`, `REQ-POL-004`, `REQ-POL-005`, `REQ-POL-006`, `REQ-POL-007`, `REQ-POL-008`, `REQ-POL-009`, `REQ-POL-010`, `REQ-POL-011`, `REQ-POL-014`, `REQ-POL-015`, `REQ-POL-016`, `REQ-POL-017`, `REQ-POL-018`, `REQ-POL-019`, `REQ-POL-020`, `REQ-POL-021`, `REQ-POL-022`
- `REQ-POL-023`, `REQ-POL-024`, `REQ-POL-025`, `REQ-POL-026`, `REQ-POL-027`, `REQ-POL-028`, `REQ-POL-029`, `REQ-POL-030`, `REQ-POL-031`, `REQ-POL-032`, `REQ-POL-033`, `REQ-POL-034`, `REQ-POL-035`, `REQ-POL-036`, `REQ-POL-037`, `REQ-POL-038`, `REQ-POL-039`, `REQ-POL-041`, `REQ-POL-042`, `REQ-POL-043`
- `REQ-POL-044`, `REQ-POL-045`, `REQ-POL-046`, `REQ-POL-047`, `REQ-POL-048`, `REQ-POL-049`, `REQ-POL-050`, `REQ-POL-051`, `REQ-POL-052`, `REQ-WIZ-001`, `REQ-WIZ-002`, `REQ-WIZ-003`, `REQ-WIZ-004`, `REQ-WIZ-005`, `REQ-WIZ-006`, `REQ-WIZ-007`, `REQ-WIZ-008`, `REQ-WIZ-009`, `REQ-WIZ-010`, `REQ-WIZ-013`
- `REQ-WIZ-014`, `REQ-UXN-003`, `REQ-UXN-005`, `REQ-UXN-006`, `REQ-UXN-013`, `REQ-UXN-014`, `REQ-QA-007`, `REQ-QA-008`, `REQ-QA-009`

### NON DÉMONTRÉ

- `REQ-POL-012`, `REQ-WIZ-011`, `REQ-UXN-007`, `REQ-UXN-010`, `REQ-UXN-011`, `REQ-UXN-016`, `REQ-UXN-017`, `REQ-OPS-010`, `REQ-OPS-011`, `REQ-OPS-012`, `REQ-REUSE-002`, `REQ-REUSE-003`, `REQ-REUSE-004`, `REQ-REUSE-006`, `REQ-REUSE-011`

## Preuves principales réinspectées

- Tenancy/RLS : `tenancy/context.py`, `infrastructure/database.py`, migrations/repositories RLS, tests A/B/IDOR.
- Permissions : moteur de permissions, tests unit/property; rôles cumulatifs, overwrites, owner/admin, View As, simple/expert, simulation.
- Planning : service planning, modèles, persistance/DAG/preflight/impact/UNKNOWN_OUTCOME, failure-injection.
- Portabilité/templates : service/repository/API Stage06, tests PostgreSQL/E2E; template privé RLS démontré.
- Stage10 : large couverture backend/Playwright; `REQ-TEST-003` reste partiel car l’agrégat live A/B du run courant manque.
- Policies/Wizards : les policies spécialisées message/traduction existent, mais aucun Policy Engine générique ni module Wizard complet n’est démontré.

## Priorités

1. **Policy Engine générique** : traité dans la Phase UI 4 existante.
2. **Wizards** : socle en Phase UI 4, réutilisé ensuite.
3. **Operations Center inter-session + drafts** : Phase UI 5.
4. **Templates adaptatifs** : Phase UI 6.
5. **UX/REUSE** : Phase UI 8.
6. **REQ-TEST-003 + QA + clôture** : Phase UI 9.

Aucune phase UI supplémentaire n'est créée à partir de cet audit.

## Maintenance

Une exigence `PARTIEL` ne passe à `CONFORME` qu’après satisfaction de **tous** ses critères avec preuve adaptée au risque. Les tests sont ciblés pendant les phases ; la campagne complète est réservée à la Phase 9.
