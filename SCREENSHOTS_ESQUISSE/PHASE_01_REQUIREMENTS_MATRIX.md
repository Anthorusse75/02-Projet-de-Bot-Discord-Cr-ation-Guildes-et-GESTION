# Phase 1 — Matrice de conformité `docs/00_reference` → produit

Statut : **AUDIT INITIAL TERMINÉ**  
Branche : `ui/complete-redesign`  
Référence visuelle : `SCREENSHOTS_ESQUISSE/Esquisse 1.png`

## Règles de lecture

Cette matrice ne reprend pas les anciens `VERIFIED` comme vérité. Elle qualifie l'état **visible/utilisable par l'utilisateur** et le chemin d'exécution réel.

Statuts employés :

- **CONFORME CODE / À REJOUER** : le mécanisme attendu existe clairement dans le code, mais le nouveau programme d'acceptance doit encore le rejouer dans le navigateur et/ou sur les Guilds A/B ;
- **PARTIEL** : une partie utile existe, mais le use case ou l'UX demandée n'est pas complet ;
- **NON CONFORME** : le parcours demandé est absent, cassé ou contraire à la référence ;
- **NON REQUALIFIÉ** : exigence principalement backend/sécurité ; pas de preuve négative trouvée pendant l'audit UI, mais elle ne sera pas considérée acquise sans le gate adapté ;
- **N/A UI** : pas de surface UI propre, mais la contrainte doit rester vraie pendant les phases de refonte.

Les deux sources normatives sont :

- `docs/00_reference/01_SPECIFICATIONS_FONCTIONNELLES_DISCORD_INFRA_DESIGNER.md`
- `docs/00_reference/02_ARCHITECTURE_TECHNIQUE_DISCORD_INFRA_DESIGNER.md`

---

## 53.1 — Installation et identité (`REQ-INST-001..007`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| INST-001, INST-002 | CONFORME CODE / À REJOUER | Modèle `guild_installations` tenant par `guild_id`; runtime `GUILD_CREATE` sait créer `PENDING_SETUP`. | 2 / 9 |
| INST-003, INST-004, INST-005 | **NON CONFORME PARCOURS** | L'API possède `/bootstrap`, mais `GuildSelectPage` n'offre aucun assistant; base vierge A/B non découverte dans l'essai réel. | **2** |
| INST-006, INST-007 | NON REQUALIFIÉ | Backend de désinstallation existe; doit être rejoué avec perte réelle de capacités et réinstallation sans contamination tenant. | 2 / 9 |

## 53.2 — Multi-tenancy (`REQ-TEN-001..014`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| TEN-001..004, TEN-006..010 | NON REQUALIFIÉ | RLS/tenant context et repositories tenant-aware existent; aucun écart UI direct identifié. Garder les tests sécurité ciblés, pas les rejouer à chaque changement visuel. | 9 |
| TEN-005 | CONFORME CODE / À REJOUER | WebSocket est tenant-scopé et réautorisé, mais le socket réel échoue actuellement; impossible de valider le use case tant que P0-006 n'est pas corrigé. | 2 / 9 |
| TEN-011..014 | PARTIEL | Le moteur de copie/portable existe et `ActionRegistry` vérifie source/destination; UI de clone demande encore des IDs bruts et portability retourne 503 sans configuration. | **6 / 9** |

## 53.3 — Structure Discord (`REQ-STR-001..013`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| STR-001 | **NON CONFORME EN PRATIQUE** | Code de projection catégories/salons/threads présent, mais serveur réel affiché vide après le parcours testé. | **2 puis 3** |
| STR-002, STR-004, STR-005 | CONFORME CODE / À REJOUER | Modèle et planification semblent respecter catégories/parentage; mutations réelles à rejouer. | 3 / 5 / 9 |
| STR-003 | PARTIEL | Les abstractions existent mais leur distinction visuelle n'atteint pas la qualité attendue. | 3 |
| STR-006..013 | PARTIEL | Pointer gesture + ActionRegistry + preview + right-drag existent. L'UX visuelle est primitive et aucun parcours réel n'a été validé après import de structure. | **3 / 9** |

## 53.4 — Permissions (`REQ-PERM-001..009`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| PERM-001, PERM-002 | NON REQUALIFIÉ | Moteur backend hors audit UI détaillé; conserver les tests unitaires critiques. | 4 / 9 |
| PERM-003 | **NON CONFORME UI** | L'écran actuel n'administre pas les permissions; il ne fait qu'expliquer/View As. Aucun mode simple de mutation humaine. | **4** |
| PERM-004 | PARTIEL | Bascule expert et trace existent, mais pas d'éditeur complet des flags/overwrites réels. | 4 |
| PERM-005, PERM-006, PERM-007 | PARTIEL / À REJOUER | `View As`, trace et warning ADMINISTRATOR ont un substrat; entrée utilisateur basée sur Snowflakes bruts et pas de validation UX réelle. | 4 / 9 |
| PERM-008, PERM-009 | PARTIEL / NON REQUALIFIÉ | Comparaison/présentation des politiques doit être refondue pour distinguer clairement Discord natif et délégation DID. | 4 |

## 53.5 — Plans et mutations (`REQ-PLAN-001..016`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| PLAN-001..010, PLAN-013..016 | CONFORME CODE / À REJOUER | Pipeline backend de plan existe; écran Plans expose validate/confirm/apply/cancel et progression. La conformité réelle sera jugée sur mutation Discord + reload + audit. | **5 / 9** |
| PLAN-011, PLAN-012 | PARTIEL | Confirmation renforcée existe dans le code; l'impact avant/après et le risque ne sont pas présentés avec la clarté produit attendue. | **5** |

## 53.6 — Duplication et templates (`REQ-DUP-001..019`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| DUP-001..019 | **PARTIEL / NON FONCTIONNEL DANS LA BASELINE** | Backend/portable pipeline substantiel, mais Templates/Bibliothèque renvoient 503 sans configuration, Template UI est lecture seule, Clone exige un Snowflake source saisi à la main et n'offre pas le workflow visuel de mapping/conflits attendu. | **6 / 9** |

## 53.7 — Bots et sécurité (`REQ-BOT-001..007`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| BOT-001, BOT-002, BOT-006, BOT-007 | NON REQUALIFIÉ | Contraintes backend/sécurité; aucune régression volontaire prévue par la refonte. | 9 |
| BOT-003 | PARTIEL UI | `dashboard-capabilities` expose des causes/remédiations, mais Diagnostics n'affiche actuellement que couverture/fraîcheur. | **2 / 8** |
| BOT-004 | PARTIEL / À REJOUER | Audit sécurité backend à exposer clairement. | 8 / 9 |
| BOT-005 | **NON CONFORME UI** | La référence demande où chaque bot peut lire/écrire; aucune vraie cartographie dans le dashboard actuel. | **8** |

## 53.8 — OAuth et sessions (`REQ-AUTH-001..014`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| AUTH-001..014 | CONFORME CODE / À REJOUER, avec défaut de lancement | OAuth réel a fonctionné. Le premier échec `OAUTH_STATE_INVALID` provenait du mélange `127.0.0.1`/`localhost`, rendu possible par le câblage dev incohérent. La refonte doit garantir une origine unique et rejouer changement de Guild/session/CSRF. | **2 / 9** |

## 53.9 — Gateway et intents (`REQ-GW-001..008`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| GW-001..005, GW-007, GW-008 | CONFORME CODE / À REJOUER | Intents minimaux + normalisation + cache/obfuscation existent. Le défaut réel de découverte montre que le démarrage Gateway doit être observé et rejoué sans fixture. | **2 / 9** |
| GW-006 | NON REQUALIFIÉ EN LIVE | Invalidation/stale existe dans le moteur, mais doit être démontrée via modification directe Discord -> UI. | 3 / 5 / 9 |

## 53.10 — Audit / données (`REQ-AUD-001..006`, `REQ-DATA-001..002`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| AUD-001..006 | **PARTIEL / CASSÉ EN BASELINE** | Ledger backend existe; écran Audit est minimal et l'endpoint `/audit` a produit un HTTP 500 dans le parcours réel. | **2 / 8 / 9** |
| DATA-001, DATA-002 | NON REQUALIFIÉ | Contraintes backend/rétention; à préserver et vérifier au gate final. | 9 |

## 53.11 — UX (`REQ-UX-001..007`, `REQ-UX-CTX-001..005`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| UX-001 | PARTIEL | ActionRegistry sait désactiver selon capabilities, mais trop d'écrans finissent en ErrorState générique/HTTP brut; diagnostics insuffisants. | 2..8 |
| UX-002 | **NON CONFORME** | Plusieurs parcours demandent des IDs/Snowflakes bruts; ce n'est pas un vocabulaire humain. | **3 / 4 / 6 / 7** |
| UX-003 | PARTIEL | Mode expert permissions/trace présent mais incomplet. | 4 |
| UX-004 | PARTIEL | DnD/menu codés, qualité et use cases réels non validés. | 3 |
| UX-005 | CONFORME CODE / À REJOUER | Command palette présente dans le shell. | 8 |
| UX-006 | PARTIEL | Progression de plans présente; progression cohérente à généraliser aux opérations longues. | 5 / 7 |
| UX-007 | PARTIEL / À REJOUER | L'écran Plans distingue job accepté, mais le produit doit prouver qu'il ne célèbre pas une mutation avant vérification réelle. | 5 / 9 |
| UX-CTX-001, UX-CTX-002 | **CONFORME CODE / À REJOUER** | `GlobalContextMenuBoundary` est monté globalement et intercepte `contextmenu` en capture. | 3 / 9 |
| UX-CTX-003..005 | PARTIEL / À REJOUER | ActionRegistry commun et right-drag présents; comportement réel, filtres ACL et accessibilité à rejouer dans la nouvelle UI. | 3 / 9 |

## 53.12 — Multilingue (`REQ-I18N-001..042`, incluant `026A`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| I18N-001..042/026A | **SUBSTRAT IMPORTANT / NON REQUALIFIÉ DE BOUT EN BOUT** | `TranslationWorkspace` est l'un des écrans les plus complets : groupes, langues, providers, routes, variantes, drift, right-drag, create/link/clone/preview. Il reste visuellement à refaire et chaque use case critique doit être rejoué sur données réelles. | **7 / 9** |
| I18N-034 | PARTIEL | Une représentation hiérarchique existe mais n'atteint pas l'explorateur visuel validé. | 7 |

## 53.13 — Cache / réconciliation / rate limits (`REQ-CACHE-001..013`, `REQ-RATE-001..006`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| CACHE-001..006, CACHE-008..013 | CONFORME CODE / NON REQUALIFIÉ LIVE | Infrastructure cache/réconciliation existe; à rejouer via refresh, drift, obfuscation et purge ciblée. | 2 / 3 / 9 |
| CACHE-007 | CONFORME CODE / UX À REFAIRE | `StructureScreen` possède `includeHiddenDeleted`; rendu actuel trop sommaire. | 3 |
| RATE-001..006 | N/A UI / NON REQUALIFIÉ | Garder gates backend ciblés au checkpoint final; diagnostics/métriques utiles seront présentés en Phase 8. | 8 / 9 |

## 53.14 — Internationalisation dashboard (`REQ-UI18N-001..021`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| UI18N-001..010, 012..020 | PARTIEL / À REJOUER | Infrastructure i18next/catalog/runtime existe. Défaut concret trouvé : catalogue FR contient littéralement `Àucun serveur Discord admissible trouvé.`; ce n'est pas un problème de police mais une faute dans la source. | **2 / 8** |
| UI18N-011 | NON REQUALIFIÉ | Les E2E critiques EN/FR/DE/ES devront couvrir les vrais use cases, sans multiplier les tests décoratifs. | 8 / 9 |
| UI18N-021 | N/A / À CONFIRMER | Pas d'Application Commands utilisateur visibles dans le produit courant. | 8 / 9 |

## 53.15 — Communication / campagnes (`REQ-MSG-001..031`)

| Exigences | État Phase 1 | Constat / preuve actuelle | Phase propriétaire |
|---|---|---|---|
| MSG-001..031 | **SUBSTRAT FONCTIONNEL LARGE / NON REQUALIFIÉ DE BOUT EN BOUT** | `CampaignCenter` expose création/édition, targets multi-Guild, translation modes, scheduling, simulation, variantes, deliveries et interventions. L'écran est trop complexe et doit être redessiné; les publications réelles et protections Discord-safe seront rejouées. | **7 / 9** |

## 53.16 — Tests (`REQ-TEST-001..005`)

| Exigences | État Phase 1 | Décision pour la refonte | Phase propriétaire |
|---|---|---|---|
| TEST-001 | CONSERVÉ | Les endpoints tenant critiques gardent leurs preuves cross-tenant; pas de relance massive après CSS. | 9 |
| TEST-002 | CONSERVÉ | Tests unitaires exhaustifs du moteur permissions restent utiles. | 4 / 9 |
| TEST-003 | **DEVIENT CENTRAL** | A/B doivent être utilisées pour les use cases réels d'acceptance, pas seulement des fixtures. | 2..9 |
| TEST-004 | CONSERVÉ CIBLÉ | Destructif + échecs partiels testés au niveau du use case. | 5 / 9 |
| TEST-005 | **RENFORCÉ** | Playwright couvre les parcours critiques réellement visibles; pas chaque détail CSS. | 2..9 |

---

# Architecture technique — écarts UI à conserver dans le backlog

| Référence architecture | État | Décision |
|---|---|---|
| React 19 / TS strict / Vite / Router / TanStack / Zustand / i18next | Globalement en place | Conserver. |
| `dnd-kit` | Absent du package | L'architecture §22 précise néanmoins que les Pointer Events/`PointerGestureManager` sont la source de vérité pour clic droit/right-drag. Le moteur actuel n'est donc **pas non conforme par principe**. Ajouter `dnd-kit` en Phase 3 uniquement pour les primitives utiles (collision, overlay, tri, clavier), avec custom sensor/gesture layer DID. |
| Radix/shadcn ou primitives accessibles similaires | Bibliothèque externe absente; primitives maison présentes | Ré-auditer accessibilité composant par composant. Remplacer les primitives faibles dans le nouveau design system. |
| environnement Windows 11 simple | **NON CONFORME** | README + Vite ne donnent pas un lancement frontend/API same-origin fonctionnel. Corriger Phase 2. |
| API + Bot + Worker + Scheduler + Frontend | Processus présents | Phase 2 doit fournir un démarrage local clair et observable. |
| zéro chaîne système non localisée | Infrastructure présente | Ré-auditer pendant la reconstruction et corriger le catalogue. |

# Conclusion de la matrice

Le backend contient beaucoup plus de substance que ce que l'UI actuelle laisse voir. Le problème n'est donc pas « tout jeter » :

- **conserver** les contrats backend, moteurs, cache, plans, portable, translation/campaign quand ils passent la requalification ;
- **réparer** le chemin d'exécution réel et l'onboarding ;
- **remplacer** le shell et les expériences UI simplistes ;
- **rejouer** les use cases plutôt que considérer la présence d'une route ou d'un test comme une preuve produit.

Aucune famille de `docs/00_reference` ayant un impact utilisateur n'est laissée sans phase propriétaire.
