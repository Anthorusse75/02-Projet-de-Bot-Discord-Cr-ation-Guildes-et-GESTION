# Matrice de tests Discord sandbox

## Préparation commune

Créer deux Guilds dédiées A et B, sans membres réels non nécessaires. Installer la même application DID avec des permissions minimales. Stocker les IDs dans `.env.local` (`DISCORD_TEST_GUILD_A_ID`, `DISCORD_TEST_GUILD_B_ID`), jamais dans Git. Préfixer toute ressource `did-e2e-<run-id>-` et capturer uniquement des métadonnées expurgées.

| Scénario | Guild(s) | Préconditions | Action | Résultat attendu | Nettoyage | Étape |
|---|---|---|---|---|---|---:|
| installation/bootstrap | A | bot absent puis invité | installer, recevoir Gateway, bootstrap owner/admin | `PENDING_SETUP` puis `ACTIVE`, audit et cache initial | désinstaller seulement si scénario dédié | 02–03 |
| refus tenant | A/B | user autorisé A, pas B | lire/muter ID B depuis contexte A | 403/404 sans lecture repository B ni événement WS | aucun | 02, 10 |
| structure/types | A | catégorie + types de salons | importer et comparer | parentage/types/positions fidèles | supprimer préfixes run | 03–04 |
| permissions | A | rôles/overwrites/ADMINISTRATOR | View As/Why Access | résultat identique au comportement Discord documenté | restaurer rôles | 04 |
| hiérarchie bot | A | cible au-dessus du bot | preflight puis apply interdit | diagnostic précis, aucun REST invalide prévisible | restaurer ordre | 04–05 |
| create crash window | A | plan de création | couper après succès REST avant commit | `UNKNOWN_OUTCOME`, reconcile, aucun doublon | supprimer ressource créée | 05 |
| moteur de plan STAGE 05 | A | bot avec `MANAGE_CHANNELS` et `MANAGE_ROLES` | create/update/move/reorder/overwrite/delete uniquement sur fixtures préfixées | plan persisté, audit, vérification ciblée, cleanup par plan séparé | aucune fixture `DID-STAGE05-TEST-` | 05 |
| clone A→B | A/B | droits export A/import B | exporter, mapper, appliquer B | nouvelles IDs B, A intacte, double audit | supprimer clone B | 06 |
| clone refus partiel | A/B | retirer un droit d’un côté | tenter clone | refus avant mutation B | restaurer droit | 06 |
| topologie multilingue | A | scopes/langues configurés | compiler rôles/overwrites | intersection correcte, budget vérifié | retirer rôles techniques run | 08 |
| provider externe | A | provider présent/absent | config supportée/non supportée | automatique ou `MANUAL_CONFIGURATION_REQUIRED`, jamais faux succès | restaurer config | 08 |
| campagne multilingue | A/B | targets et langues | publish/schedule/retry | une delivery par clé, mentions sûres, pas de double traduction | supprimer messages test | 09 |
| désinstallation | A | installation active | retirer bot | mutations invalidées, dernier état/audit conservé selon politique | réinstaller si suite | 10 |
| obfuscation | A | mode Discord officiellement disponible | retirer `VIEW_CHANNEL` ciblé | état obfusqué/access-lost sans faux delete | rendre permission | 03, 10 |

Chaque scénario live référence la version officielle de l’endpoint/événement, l’intent, les permissions, le run ID, le commit et la preuve de nettoyage.

Au 2026-08-24, le bot de la Guild sandbox B possède `MANAGE_CHANNELS` et `MANAGE_ROLES`, sans besoin d'`ADMINISTRATOR`. Le runner STAGE 05 est `PASS` sur create/update/move/reorder/overwrite/delete, crash/recovery effectively-once, restauration de l'ordre des rôles et cleanup audité. Un seul CREATE a été observé dans la fenêtre de crash, le symbol binding a été récupéré et aucune fixture `DID-STAGE05-TEST-` ne subsiste. La preuve expurgée est `docs/90_handoffs/STAGE_05_LIVE_EVIDENCE.json`.
