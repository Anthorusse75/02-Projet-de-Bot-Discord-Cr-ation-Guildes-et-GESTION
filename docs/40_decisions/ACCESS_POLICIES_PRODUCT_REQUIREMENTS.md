# DID — Exigences produit pour les politiques d'accès simplifiées

**Statut :** exigences produit validées pour la refonte UI  
**Branche :** `ui/complete-redesign`  
**Date :** 2026-09-13  
**Portée :** expérience utilisateur de gestion des accès, rôles, catégories, salons, threads, vocaux et bots  

> Ce document consigne une clarification produit validée pendant la refonte. Il ne remplace pas silencieusement les deux sources de vérité de `docs/00_reference`; il doit être utilisé comme contrainte produit de la refonte puis intégré proprement à la traçabilité avant merge final.

---

## 1. Principe directeur

DID ne doit pas reproduire l'interface native de Discord avec les mêmes notions techniques simplement présentées autrement.

L'utilisateur exprime d'abord une **intention humaine** :

- qui voit ;
- qui écrit ;
- qui gère ;
- qui rejoint/parle en vocal ;
- qui peut mentionner ;
- qui peut créer des threads ;
- quelles exceptions sont voulues ;
- pendant combien de temps l'accès s'applique.

DID traduit ensuite cette intention en rôles, overwrites, permissions, bindings techniques ou opérations planifiées compatibles avec Discord.

Les détails Discord restent disponibles via un niveau secondaire du type **« Détails Discord »**, un menu contextuel, un inspecteur expert ou une vue de diagnostic. Ils ne constituent pas l'entrée principale du parcours normal.

### Exigences transverses

- **REQ-AP-001 — MUST** : toute politique native DID doit avoir un libellé humain, une explication courte visible et une aide détaillée accessible sans quitter l'écran.
- **REQ-AP-002 — MUST** : l'UI ne doit pas exiger la connaissance de `VIEW_CHANNEL`, `SEND_MESSAGES`, bitfields, overwrites ou Snowflakes pour réaliser un cas d'usage courant.
- **REQ-AP-003 — MUST** : le résultat Discord réel calculé reste inspectable en mode avancé.
- **REQ-AP-004 — MUST** : avant création d'un plan, DID détecte les contradictions connues entre rôles, membre, héritage et overrides applicables.
- **REQ-AP-005 — MUST** : une contradiction ne doit jamais être masquée derrière un simple état `UNKNOWN`; la cause disponible doit être expliquée avec une action de résolution lorsqu'elle existe.
- **REQ-AP-006 — MUST** : toute action de correction montre l'impact avant mutation.
- **REQ-AP-007 — MUST** : les politiques appliquées à une catégorie doivent distinguer clairement héritage, exception locale et conflit.
- **REQ-AP-008 — MUST** : les termes techniques ambigus tels que « Read Only », « Newcomer » ou « Role gated » ne sont jamais utilisés seuls comme libellés principal ; l'UI affiche une formulation explicite en langue utilisateur.

---

## 2. Types de politiques et cycle de vie

DID distingue deux familles.

### 2.1 Politiques natives DID

Politiques fournies par le produit, versionnées avec l'application.

- **REQ-AP-010 — MUST** : une politique native DID ne peut pas être supprimée par l'utilisateur.
- **REQ-AP-011 — MUST** : une politique native DID ne peut pas être modifiée globalement en place de façon à changer silencieusement les ressources qui l'utilisent.
- **REQ-AP-012 — MUST** : toute politique native peut servir de base à une nouvelle politique personnalisée.

### 2.2 Politiques personnalisées

Politiques créées par l'utilisateur ou clonées depuis une politique native/personnalisée.

- **REQ-AP-013 — MUST** : une politique personnalisée peut être créée, renommée, dupliquée, modifiée et supprimée.
- **REQ-AP-014 — MUST** : la suppression d'une politique personnalisée déjà utilisée est bloquée tant qu'une stratégie explicite n'est pas choisie : détacher, remplacer ou supprimer les bindings concernés.
- **REQ-AP-015 — MUST** : une politique personnalisée peut être créée à partir de n'importe quelle autre politique, native ou personnalisée.
- **REQ-AP-016 — MUST** : la liste des politiques distingue visuellement `DID` et `Personnalisée`.
- **REQ-AP-017 — SHOULD** : une politique personnalisée conserve sa provenance (`créée depuis ...`) à titre informatif.

---

## 3. Objets auxquels les politiques peuvent s'appliquer

Les politiques doivent être classées par type d'objet afin d'éviter un catalogue mélangé.

| Famille | Objets principaux |
|---|---|
| Visibilité / écriture | Catégorie, salon texte, forum, thread lorsque Discord le permet |
| Zone / audience | Catégorie, salon |
| Vocal | Salon vocal / stage |
| Threads / réactions / mentions | Salon texte / forum, avec défauts possibles au niveau serveur |
| Bots | Bot + catégorie/salon |
| Héritage / verrouillage | Catégorie et descendants |
| Temporaire | Binding membre/rôle vers catégorie/salon/vocal |
| Matrice / édition massive | Plusieurs catégories/salons/rôles/groupes |

- **REQ-AP-020 — MUST** : l'UI n'affiche que les politiques compatibles avec l'objet sélectionné.
- **REQ-AP-021 — MUST** : lorsqu'une politique n'est pas applicable à un type Discord donné, elle ne doit pas être présentée comme action valide.

---

# 4. Politiques de visibilité

## 4.1 « Visible uniquement par… » — Viewer Whitelist

**Intention utilisateur :** seuls les rôles/groupes sélectionnés voient la ressource ; tous les autres ne la voient pas.

Exemple : catégorie `Direction` visible uniquement par `Administrateurs` et `Managers`.

- **REQ-AP-VIS-001 — MUST** : l'utilisateur choisit une liste de rôles/groupes autorisés.
- **REQ-AP-VIS-002 — MUST** : DID calcule les refus/autorisations nécessaires pour que le reste de l'audience soit inversé par rapport à la liste.
- **REQ-AP-VIS-003 — MUST** : l'UI affiche avant validation « X rôles autorisés ; tous les autres masqués ».
- **REQ-AP-VIS-004 — MUST** : DID détecte tout membre qui verrait malgré tout la ressource à cause d'un autre rôle, d'`ADMINISTRATOR`, d'un overwrite membre ou d'une autre règle prioritaire observable.

## 4.2 « Visible par tous sauf… » — Viewer Blacklist

**Intention utilisateur :** la ressource est visible par défaut ; les rôles/groupes sélectionnés ne doivent pas la voir.

- **REQ-AP-VIS-010 — MUST** : l'utilisateur choisit la liste exclue.
- **REQ-AP-VIS-011 — MUST** : DID analyse les rôles cumulés et les exceptions effectives avant de déclarer la blacklist cohérente.
- **REQ-AP-VIS-012 — MUST** : pour chaque membre en conflit, l'UI montre une phrase concrète du type : `Exception : @user possède aussi le rôle X qui lui permet de voir ce salon.`
- **REQ-AP-VIS-013 — MUST** : le détail du conflit indique la source exacte de l'accès : rôle, rôle administrateur, overwrite membre, héritage ou autre règle connue.
- **REQ-AP-VIS-014 — MUST** : une action `Régler ce conflit` ouvre les remédiations possibles avec leur impact.
- **REQ-AP-VIS-015 — MUST** : DID ne supprime jamais automatiquement un rôle complet à un membre simplement pour résoudre un conflit sans montrer les autres conséquences de ce rôle.
- **REQ-AP-VIS-016 — SHOULD** : lorsqu'un conflit révèle un modèle de rôles incohérent ou redondant, DID propose `Optimiser les rôles` avec une analyse séparée.
- **REQ-AP-VIS-017 — MUST** : si l'exception est réellement voulue, l'utilisateur peut la conserver explicitement ; elle devient alors une exception documentée et non un conflit silencieux.

> Décision produit : la résolution de conflits du mode Blacklist est la stratégie privilégiée. Une politique séparée « Blacklist stricte » n'est pas imposée tant qu'un besoin non couvert n'est pas démontré.

## 4.3 « Espace privé — visible uniquement par… »

- **REQ-AP-VIS-020 — MUST** : cette politique encapsule un Viewer Whitelist avec une présentation simplifiée adaptée à une zone privée.
- **REQ-AP-VIS-021 — MUST** : un tooltip/aide explique clairement qui est exclu par défaut et comment le staff peut être ajouté.

---

# 5. Politiques d'écriture

## 5.1 « Seuls … peuvent écrire » — Writer Whitelist

- **REQ-AP-WRI-001 — MUST** : tous les utilisateurs autorisés à voir restent lecteurs ; seuls les rôles/groupes sélectionnés peuvent publier.
- **REQ-AP-WRI-002 — MUST** : l'UI distingue explicitement `Voir` et `Écrire`.

## 5.2 « Tout le monde peut écrire sauf… » — Writer Blacklist

- **REQ-AP-WRI-010 — MUST** : l'utilisateur choisit les rôles/groupes qui ne peuvent pas écrire.
- **REQ-AP-WRI-011 — MUST** : DID applique la même détection de conflits multi-rôles que pour Viewer Blacklist.

## 5.3 « Lecture ouverte, publication limitée à… »

Remplace le libellé ambigu `Read Only`.

**Comportement :** tout le monde autorisé à voir peut lire ; seuls les éditeurs choisis peuvent publier.

- **REQ-AP-WRI-020 — MUST** : le libellé principal doit expliciter que la restriction d'écriture ne concerne pas nécessairement tout le monde.
- **REQ-AP-WRI-021 — MUST** : l'utilisateur choisit les éditeurs autorisés.
- **REQ-AP-WRI-022 — SHOULD** : des options séparées contrôlent réactions, threads et réponses lorsqu'elles sont pertinentes.

---

# 6. Politiques de zones et d'audiences

## 6.1 « Zone publique + espace staff associé »

- **REQ-AP-ZONE-001 — MUST** : DID ne crée jamais de fausse sous-catégorie Discord.
- **REQ-AP-ZONE-002 — MUST** : si une zone publique et une zone staff doivent être liées logiquement, DID utilise deux structures Discord valides et peut les regrouper par une abstraction/logical group DID clairement identifiée.
- **REQ-AP-ZONE-003 — MUST** : la partie publique est visible selon sa politique ; la partie staff suit `Staff uniquement`.

## 6.2 « Staff uniquement »

- **REQ-AP-ZONE-010 — MUST** : l'utilisateur définit une fois quels rôles/groupes représentent le staff ou confirme une détection proposée.
- **REQ-AP-ZONE-011 — MUST** : DID ne suppose pas silencieusement qu'un rôle nommé `Admin`, `Staff` ou `Modérateur` représente effectivement le staff.
- **REQ-AP-ZONE-012 — MUST** : le tooltip affiche les groupes actuellement inclus dans `Staff`.

## 6.3 « Membres confirmés uniquement »

Remplace la notion floue de `Members only`.

- **REQ-AP-ZONE-020 — MUST** : chaque Guild possède une définition explicite de `membre confirmé`.
- **REQ-AP-ZONE-021 — MUST** : cette définition peut être basée sur un ou plusieurs rôles Discord ou une règle DID explicitement configurée.
- **REQ-AP-ZONE-022 — MUST** : lors du premier usage, si aucune définition n'existe, DID demande quels rôles signifient `membre confirmé` ; il ne devine pas.
- **REQ-AP-ZONE-023 — MUST** : l'UI indique clairement quelles personnes sont considérées comme confirmées et lesquelles ne le sont pas.

## 6.4 « Zone d'accueil avant validation »

Remplace le libellé principal `Newcomer Area`.

**Audience :** utilisateurs qui ne correspondent pas encore à la définition `membre confirmé`, avec staff optionnellement visible.

- **REQ-AP-ZONE-030 — MUST** : l'UI explique la condition en langage humain.
- **REQ-AP-ZONE-031 — MUST** : DID gère la transition lorsque l'utilisateur devient `membre confirmé`.
- **REQ-AP-ZONE-032 — MUST** : le staff peut être inclus via une option explicite.

## 6.5 « Au moins un de ces rôles »

- **REQ-AP-ZONE-040 — MUST** : la logique `Rôle A OU Rôle B OU ...` est affichée explicitement.
- **REQ-AP-ZONE-041 — MUST** : un tooltip donne un exemple concret du résultat.

## 6.6 « Tous ces rôles sont requis »

- **REQ-AP-ZONE-050 — MUST** : la logique `Rôle A ET Rôle B ET ...` est affichée explicitement.
- **REQ-AP-ZONE-051 — MUST** : lorsque Discord ne peut pas exprimer directement l'intention par de simples overwrites, DID peut créer/réutiliser un rôle technique de combinaison maintenu par le bot.
- **REQ-AP-ZONE-052 — MUST** : le rôle technique reste caché de l'expérience métier normale mais visible en diagnostic avancé.

## 6.7 « A mais pas B »

- **REQ-AP-ZONE-060 — MUST** : l'utilisateur peut exprimer `possède le rôle A ET ne possède pas le rôle B`.
- **REQ-AP-ZONE-061 — MUST** : DID montre la traduction technique et les éventuels membres en conflit avant apply.

---

# 7. Accès temporaires

- **REQ-AP-TMP-001 — MUST** : un accès peut être accordé jusqu'à une date/heure ou pour une durée.
- **REQ-AP-TMP-002 — MUST** : le bot/service DID pilote l'expiration et produit l'opération de retrait correspondante.
- **REQ-AP-TMP-003 — MUST** : l'accès temporaire est durable côté backend et survit à un redémarrage du frontend, du worker ou du bot.
- **REQ-AP-TMP-004 — MUST** : l'expiration et le retrait sont audités.
- **REQ-AP-TMP-005 — MUST** : si le retrait échoue, l'état devient actionnable et ne doit jamais être affiché comme réussi.
- **REQ-AP-TMP-006 — SHOULD** : l'UI propose des raccourcis (`1 h`, `24 h`, `7 jours`, `jusqu'à…`) plus une date personnalisée.

---

# 8. Presets de sécurité et d'usage

## 8.1 « Confidentiel »

Ce preset est une configuration guidée, pas un simple nom marketing.

- visibilité limitée aux audiences choisies ;
- gestion limitée aux rôles administratifs explicitement choisis ;
- mentions sensibles et création de contenu secondaire contrôlables ;
- preview obligatoire de tous les effets.

- **REQ-AP-PRS-001 — MUST** : l'assistant montre chaque sous-règle activée par `Confidentiel` avant validation.

## 8.2 « Salon d'annonces »

Ce preset n'implique **pas** un salon temporaire.

- **REQ-AP-PRS-010 — MUST** : il peut être appliqué à un salon existant ou utilisé lors de la création d'un nouveau salon.
- **REQ-AP-PRS-011 — MUST** : le comportement par défaut est persistant.
- **REQ-AP-PRS-012 — MUST** : l'utilisateur choisit qui publie ; les lecteurs restent définis séparément.
- **REQ-AP-PRS-013 — SHOULD** : réactions et threads disposent d'options explicites.

## 8.3 « Zone support »

Ce preset n'implique **pas** une zone temporaire.

- **REQ-AP-PRS-020 — MUST** : il peut créer une zone persistante ou configurer une zone existante.
- **REQ-AP-PRS-021 — MUST** : l'utilisateur choisit visibilité, capacité à écrire et groupe support.
- **REQ-AP-PRS-022 — SHOULD** : si un moteur de tickets existe, l'intégration ticket est une option séparée et non une hypothèse du preset.

---

# 9. Politiques vocales

## 9.1 « Peut rejoindre mais pas parler »

- **REQ-AP-VOC-001 — MUST** : les utilisateurs ciblés peuvent rejoindre le vocal mais pas parler.

## 9.2 « Seuls … peuvent parler »

- **REQ-AP-VOC-010 — MUST** : tout utilisateur autorisé peut rejoindre ; seuls les rôles/groupes choisis parlent.

## 9.3 « Vocal privé »

- **REQ-AP-VOC-020 — MUST** : seuls les rôles/groupes choisis peuvent rejoindre.
- **REQ-AP-VOC-021 — SHOULD** : une option `le staff peut toujours rejoindre` est explicite et désactivable.

## 9.4 « Gestionnaires du vocal »

- **REQ-AP-VOC-030 — MUST** : l'utilisateur choisit qui peut déplacer, mute/deafen et administrer le vocal, sans devoir sélectionner les flags Discord individuellement.

---

# 10. Threads, réactions et mentions

## 10.1 Créateurs de threads

- **REQ-AP-THR-001 — MUST** : l'utilisateur peut limiter la création de threads à certains rôles/groupes tout en laissant éventuellement les autres participer.

## 10.2 Réactions

- **REQ-AP-REA-001 — MUST** : les modes minimum sont `Tout le monde`, `Seulement…`, `Personne`.

## 10.3 Mentions

- **REQ-AP-MEN-001 — MUST** : l'utilisateur contrôle séparément les mentions sensibles supportées (`@everyone`, `@here`, rôles mentionnables lorsque pertinent).
- **REQ-AP-MEN-002 — MUST** : une valeur par défaut peut être définie au niveau de la Guild.
- **REQ-AP-MEN-003 — MUST** : une catégorie/salon peut hériter de ce défaut ou déclarer une exception.
- **REQ-AP-MEN-004 — MUST** : le niveau Discord expert reste consultable.

---

# 11. Accès des bots

- **REQ-AP-BOT-001 — MUST** : l'utilisateur sélectionne un bot puis configure des intentions humaines : `lire`, `écrire`, `gérer`, `threads`, `vocal` selon le contexte.
- **REQ-AP-BOT-002 — MUST** : DID calcule les permissions minimales nécessaires ; il ne recommande pas `ADMINISTRATOR` par défaut.
- **REQ-AP-BOT-003 — MUST** : DID montre où le bot manque réellement d'accès.
- **REQ-AP-BOT-004 — MUST** : toute capability `UNKNOWN` doit afficher la cause disponible et une remédiation ; un message générique permanent n'est pas acceptable.

---

# 12. Héritage de catégorie

## 12.1 Politique maître de catégorie

- **REQ-AP-INH-001 — MUST** : une catégorie peut porter une politique maître.
- **REQ-AP-INH-002 — MUST** : les salons descendants sont affichés comme `Hérité`, `Exception locale` ou `Conflit`.
- **REQ-AP-INH-003 — MUST** : l'utilisateur peut choisir `réappliquer la politique de catégorie` sur une ou plusieurs exceptions.
- **REQ-AP-INH-004 — MUST** : DID ne prétend jamais créer des niveaux de catégories imbriquées inexistants dans Discord.

## 12.2 Verrouillage de politique

- **REQ-AP-LOCK-001 — MUST** : une politique de catégorie ou de salon peut être marquée `Verrouillée`.
- **REQ-AP-LOCK-002 — MUST** : lorsqu'un changement Discord externe est détecté et viole une politique verrouillée, DID déclenche automatiquement une remise en conformité sans exiger une confirmation manuelle supplémentaire, sous réserve que les capacités nécessaires soient toujours valides.
- **REQ-AP-LOCK-003 — MUST** : la correction automatique est déclenchée dès réception/détection de l'événement Discord ; une réconciliation périodique sert de filet de sécurité si un événement est perdu.
- **REQ-AP-LOCK-004 — MUST** : toute correction automatique est auditée avec état avant/après et initiateur `POLICY_RECONCILER` ou équivalent explicite.
- **REQ-AP-LOCK-005 — MUST** : si la correction automatique est impossible, l'état est `À corriger / Intervention requise` et non `Conforme`.
- **REQ-AP-LOCK-006 — MUST** : une politique non verrouillée signale le drift et propose `Réparer` ou `Accepter l'exception`.

---

# 13. Matrice d'accès simplifiée

- **REQ-AP-MAT-001 — MUST** : DID fournit une matrice dont les lignes représentent des groupes/rôles/audiences et les colonnes des zones/catégories/salons.
- **REQ-AP-MAT-002 — MUST** : une cellule affiche une synthèse humaine minimum : `Aucun accès`, `Voir`, `Écrire`, `Gérer`.
- **REQ-AP-MAT-003 — MUST** : cliquer une cellule permet de modifier la politique/intention sans exposer immédiatement les flags Discord.
- **REQ-AP-MAT-004 — MUST** : les conflits et exceptions sont signalés visuellement dans la cellule.
- **REQ-AP-MAT-005 — MUST** : un filtre permet de n'afficher que les conflits, exceptions ou zones privées.
- **REQ-AP-MAT-006 — MUST** : les détails Discord restent accessibles depuis la cellule ou son menu contextuel.

---

# 14. Édition massive

- **REQ-AP-BULK-001 — MUST** : l'utilisateur peut sélectionner plusieurs catégories/salons puis appliquer une politique compatible en une opération.
- **REQ-AP-BULK-002 — MUST** : DID montre le nombre de ressources touchées et les différences avant/après.
- **REQ-AP-BULK-003 — MUST** : les objets incompatibles sont exclus avec une raison, jamais ignorés silencieusement.
- **REQ-AP-BULK-004 — SHOULD** : les opérations fréquentes sont disponibles depuis le menu contextuel de la sélection.

---

# 15. Résolution et optimisation des conflits de rôles

- **REQ-AP-CFL-001 — MUST** : DID sait lister les membres dont les rôles produisent un résultat contraire à l'intention déclarée de la politique.
- **REQ-AP-CFL-002 — MUST** : chaque conflit explique `qui`, `quelle ressource`, `quelle politique`, `quel rôle/règle donne l'accès` et `quelle règle cherche à l'interdire`.
- **REQ-AP-CFL-003 — MUST** : `Régler ce conflit` propose uniquement des solutions valides et affiche leurs impacts collatéraux.
- **REQ-AP-CFL-004 — MUST** : retirer un rôle à une personne n'est proposé qu'avec la liste des autres accès/fonctions perdus par ce retrait.
- **REQ-AP-CFL-005 — SHOULD** : DID détecte les rôles redondants, contradictoires, inutilisés ou servant uniquement à compenser d'autres rôles et propose une optimisation.
- **REQ-AP-CFL-006 — MUST** : l'optimisation de rôles reste un plan séparé et prévisualisable ; elle n'est jamais déclenchée implicitement par la résolution d'un conflit.

---

# 16. Exigences UX de présentation

- **REQ-AP-UX-001 — MUST** : chaque politique possède un résumé d'une phrase et un tooltip/aide développée.
- **REQ-AP-UX-002 — MUST** : l'UI affiche un exemple concret lorsque la logique comporte `OU`, `ET`, `SAUF` ou une négation.
- **REQ-AP-UX-003 — MUST** : les détails avancés (`permissions Discord`, bitfield, overrides, rôle technique) sont accessibles mais repliés par défaut.
- **REQ-AP-UX-004 — MUST** : depuis une catégorie/salon, le menu contextuel offre `Gérer l'accès` avant les entrées techniques de rôles/permissions.
- **REQ-AP-UX-005 — MUST** : un utilisateur peut comprendre le résultat attendu sans connaître la terminologie Discord.
- **REQ-AP-UX-006 — MUST** : un bouton désactivé expose toujours sa raison via texte/tooltip/action de diagnostic ; `UNKNOWN` sans cause n'est pas conforme.
- **REQ-AP-UX-007 — SHOULD** : les politiques les plus utilisées peuvent être épinglées en favoris par Guild.

---

# 17. Exigences de validation minimale par fonctionnalité

Ces exigences complètent le principe de validation de la refonte : peu de tests, mais des tests significatifs.

Pour chaque nouvelle primitive/politique importante :

- **REQ-AP-TST-001 — MUST** : un scénario nominal navigateur vérifie l'intention utilisateur et la donnée envoyée au backend.
- **REQ-AP-TST-002 — MUST** : un scénario de refus/conflit vérifie que l'action est bloquée avec une cause compréhensible.
- **REQ-AP-TST-003 — MUST** : un scénario recharge la page ou refetch le read model pour vérifier la persistance de l'état attendu.
- **REQ-AP-TST-004 — MUST** : toute logique de conflit multi-rôles possède au moins un test avec deux rôles contradictoires sur un même membre.
- **REQ-AP-TST-005 — MUST** : toute politique verrouillée possède un test `mutation externe -> détection -> remise en conformité` et un test d'échec de réconciliation.
- **REQ-AP-TST-006 — MUST** : les tests d'UI ne peuvent pas déclarer un résultat valide en mockant directement l'état que le backend est justement censé calculer lorsque ce calcul est au cœur de la fonctionnalité.

---

# 18. Catalogue initial des politiques natives DID

Catalogue validé à ce stade :

1. Visible uniquement par…
2. Visible par tous sauf…
3. Seuls … peuvent écrire
4. Tout le monde peut écrire sauf…
5. Lecture ouverte, publication limitée à…
6. Espace privé — visible uniquement par…
7. Zone publique + espace staff associé
8. Staff uniquement
9. Membres confirmés uniquement
10. Zone d'accueil avant validation
11. Au moins un de ces rôles
12. Tous ces rôles sont requis
13. A mais pas B
14. Accès temporaire
15. Confidentiel
16. Salon d'annonces
17. Zone support
18. Peut rejoindre le vocal mais pas parler
19. Seuls … peuvent parler
20. Vocal privé
21. Gestionnaires du vocal
22. Créateurs de threads limités à…
23. Réactions : tous / seulement / personne
24. Politique de mentions
25. Accès bot minimal par fonction
26. Politique maître de catégorie
27. Politique verrouillée
28. Matrice d'accès simplifiée
29. Édition massive de politiques
30. Politique personnalisée

Ce catalogue n'interdit pas de nouvelles politiques natives ultérieures ; toute nouvelle entrée doit respecter les mêmes règles d'explication, de conflit, de preview et de traduction Discord.

---

# 19. Points volontairement à affiner pendant conception

- représentation UX exacte des rôles techniques de combinaison `ET` ;
- stratégie optimale pour les exceptions membre lorsque le nombre d'overwrites devient important ;
- limites et quotas avant création de rôles/bindings techniques ;
- détails du moteur d'optimisation de rôles ;
- SLA précis de réconciliation d'une politique verrouillée selon disponibilité Gateway/REST ;
- nomenclature finale FR/EN/DE/ES des politiques après test utilisateur.

Ces points ne remettent pas en cause les intentions fonctionnelles validées ci-dessus.
