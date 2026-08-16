# Décisions d’implémentation

Les ADR-001 à ADR-035 restent normatifs dans la source d’architecture. Ce registre contient uniquement les décisions prises pendant l’exécution et les clarifications de cohérence ; il ne réécrit pas les sources.

## IMP-001 — Channel Obfuscation future-dated

- Date : 2026-08-16
- Statut : `OPEN_REVALIDATION_STAGE_03`
- Constat : les deux sources décrivent un changement « Channel Obfuscation » annoncé pour le 16 novembre 2026, date future par rapport à la date de référence du dépôt. Une recherche dans la documentation officielle accessible au moment de l’import n’a pas permis de confirmer ce contrat précis.
- Décision : conserver l’exigence comme compatibilité anticipée et modèle de robustesse (`VISIBLE`, `OBFUSCATED`, `ACCESS_LOST`, tombstones), mais ne pas figer le payload, le flag ou la sémantique REST dans le code avant relecture du changelog et des docs Discord officiels au PRECHECK de STAGE 03.
- Validation : contract tests tolérants aux champs évolutifs, fixture versionnée issue d’une source officielle, puis test sandbox lorsque le mode est disponible. Une absence HTTP seule ne prouve jamais une suppression, invariant sûr indépendamment du rollout.

## IMP-002 — Publication GitHub initiale

- Date : 2026-08-16
- Statut : `RESOLVED`
- Constat initial : `gh` n’était pas installé dans l’environnement initial ; le dossier a donc d’abord été validé et committé localement sans déclarer de publication inexistante.
- Résolution :
  - le repository GitHub réel est `Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION` ;
  - `origin` est configuré vers `https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION.git` ;
  - `main` est publié et synchronisé avec le dépôt distant au moment de la résolution ;
  - la visibilité `PUBLIC_DURING_DEVELOPMENT` est volontaire ; un éventuel passage en privé constitue une décision ultérieure et n’est pas un prérequis de STAGE 01 ;
  - l’absence locale éventuelle de GitHub CLI n’empêche ni le workflow Git existant ni le démarrage de STAGE 01.

## IMP-003 — Numérotation dupliquée des invariants d’architecture

- Date : 2026-08-16
- Statut : `CLARIFIED`
- Constat : dans l’architecture §71, les numéros 23 et 24 sont réutilisés après les numéros 29. Le contenu des quatre invariants est distinct et cohérent ; seuls leurs identifiants ordinaux sont ambigus.
- Décision : considérer chaque ligne comme normative par son texte, jamais par son numéro seul. Si des identifiants exécutables sont nécessaires, STAGE 01 crée des noms stables descriptifs (`TENANT_CHILD_JOB_GUILD_SCOPED`, `TRANSLATION_PROTECTED_TOKEN_STABLE`, etc.) sans modifier la source.

## IMP-004 — Entrée package `did.localization.*` répétée

- Date : 2026-08-16
- Statut : `CLARIFIED`
- Constat : l’architecture §72 énumère deux fois `did.localization.*`, une fois pour le catalogue UI et une fois pour les locale packs/préférences. Les responsabilités sont complémentaires, pas deux packages concurrents.
- Décision : conserver un seul package `did.localization` structuré en sous-modules catalogue, packs, résolution et préférences ; `did.translation` reste réservé à la traduction de contenu.
