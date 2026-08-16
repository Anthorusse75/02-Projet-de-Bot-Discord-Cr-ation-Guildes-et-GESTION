# Index maître d’implémentation

## Ordre obligatoire

| Étape | Branche | Objectif | Dépend de |
|---:|---|---|---|
| [01](STAGE_01_REPOSITORY_ENVIRONMENT_AND_FOUNDATIONS.md) | `stage/01-foundations` | Monorepo, outillage, PostgreSQL/Redis, migrations, RLS, CI et baseline qualité. | — |
| [02](STAGE_02_OAUTH_SESSIONS_TENANCY_RBAC_INSTALLATION.md) | `stage/02-auth-tenancy` | OAuth2, sessions, Control Plane, tenancy, installation Guild et RBAC. | 01 |
| [03](STAGE_03_DISCORD_RUNTIME_CACHE_GOVERNOR_RECONCILIATION.md) | `stage/03-discord-runtime` | Gateway, cache durable, obfuscation, I/O Worker, governor, reconcile, outbox et audit. | 02 |
| [04](STAGE_04_READ_MODEL_PERMISSIONS_DIAGNOSTICS_SCOPES.md) | `stage/04-read-permissions` | Projections cache-first, moteur de permissions, diagnostics, groupes et Visibility Scopes. | 03 |
| [05](STAGE_05_DESIRED_STATE_PLAN_AND_MUTATION_ENGINE.md) | `stage/05-plan-engine` | Desired State Graph, plans immuables, DAG, preflight, apply fiable et vérification. | 04 |
| [06](STAGE_06_CLONE_TEMPLATES_PORTABLE_ARTIFACTS.md) | `stage/06-portability` | Clonage profond, templates, artifacts, bibliothèque et transfert cross-Guild autorisé. | 05 |
| [07](STAGE_07_REACT_DASHBOARD_I18N_AND_INTERACTIONS.md) | `stage/07-dashboard` | Dashboard React complet, i18n intégrale, menus, Right Drag, DnD et accessibilité. | 06 |
| [08](STAGE_08_MULTILINGUAL_CONTENT_AND_TRANSLATION_TOPOLOGY.md) | `stage/08-multilingual-topology` | Profils de langue, topologies, Scope × Language et provider non invasif. | 07 |
| [09](STAGE_09_MESSAGE_CAMPAIGN_AUTOMATION_TRANSLATION.md) | `stage/09-campaigns` | Campagnes, planification, automatisations et traduction Discord-safe mesurée. | 08 |
| [10](STAGE_10_PRODUCT_COMPLETION_SECURITY_ACCEPTANCE.md) | `stage/10-acceptance` | Complétion fonctionnelle, sécurité, performance, E2E et fermeture de chaque exigence. | 09 |
| [11](STAGE_11_FINAL_DEPLOYMENT_AND_OPERATIONS.md) | `stage/11-final-deployment` | Réécrire le runbook depuis le Release Candidate réel, déployer et valider l’exploitation. | 10 |

Les étapes sont séquentielles. Une étape validée est intégrée dans `main` avant la suivante, sauf décision formelle consignée. Les work packages internes ne constituent pas des étapes additionnelles.

## Documents transverses

- [Contrat global](00_GLOBAL_IMPLEMENTATION_CONTRACT.md)
- [État courant](00_CURRENT_STATE.md)
- [Traçabilité des exigences](00_REQUIREMENTS_TRACEABILITY.md)
- [Stratégie de tests](../20_testing/TEST_STRATEGY.md)
- [Politique de preuves](../20_testing/TEST_EVIDENCE_POLICY.md)
- [Secrets et credentials](../30_security/SECRETS_AND_CREDENTIALS.md)
- [Décisions d’implémentation](../40_decisions/IMPLEMENTATION_DECISIONS.md)
- [Handoffs](../90_handoffs/README.md)
