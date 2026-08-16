# Discord Infrastructure Designer
## Spécifications fonctionnelles détaillées

**Document :** 01 — Spécifications fonctionnelles  
**Statut :** Référence produit initiale  
**Cible :** Codex / VS Code / équipe de développement  
**Plateforme de développement initiale :** Windows 11, VS Code, Git Bash  
**Frontend :** React + TypeScript  
**Backend / Bot :** Python  
**Mode d'exploitation :** SaaS multi-tenant, une application Discord installable sur plusieurs serveurs indépendants  
**Date de référence :** 2026-08-16

---

# 1. Objet du produit

Discord Infrastructure Designer est une plateforme d'administration visuelle destinée à simplifier radicalement la création, la restructuration et l'exploitation de serveurs Discord complexes.

Le produit ne doit pas être conçu comme un simple « bot avec quelques commandes », mais comme un **outil d'infrastructure pour Discord** :

- le bot Discord fournit l'accès aux primitives et événements Discord ;
- le dashboard Web fournit l'expérience d'administration ;
- le moteur de permissions traduit des intentions humaines en permissions Discord réelles ;
- le moteur de planification permet de prévisualiser les changements avant de les appliquer ;
- l'audit et le versioning rendent les modifications compréhensibles et traçables ;
- l'architecture multi-tenant permet à plusieurs serveurs Discord indépendants d'utiliser le même bot sans partage d'informations entre eux ;
- le sous-système **Multilingual Content & Translation Topology** permet de déclarer, cloner, lier et administrer plusieurs variantes linguistiques sans confondre langue, audience et liaison de traduction.

Le principe directeur est :

> L'administrateur décrit l'organisation souhaitée. La plateforme vérifie ce que Discord permet réellement, calcule les modifications nécessaires, montre leur impact, puis applique uniquement une configuration valide.

---

# 2. Principes non négociables

## 2.1 Fidélité au modèle Discord

La plateforme ne doit jamais présenter comme « natif Discord » un objet qui n'existe pas dans Discord.

La structure Discord réelle est limitée à :

```text
Serveur Discord / Guild
├── Catégorie
│   ├── Salon texte
│   │   └── Threads éventuels
│   ├── Salon vocal
│   ├── Salon annonces
│   ├── Salon forum
│   │   └── Posts / threads
│   ├── Salon média
│   │   └── Posts / threads
│   └── Stage
├── Catégorie
└── Salons sans catégorie
```

Une catégorie Discord ne peut pas être placée dans une autre catégorie.

Un `parent_id` de salon référence une catégorie ; pour un thread, il référence son salon parent.

Les regroupements supplémentaires affichés dans le dashboard sont des **abstractions de présentation**, jamais de faux objets Discord.

## 2.2 Isolation multi-tenant

Chaque serveur Discord installé constitue un **tenant indépendant**.

Deux serveurs utilisant le bot :

- ne voient pas leurs données respectives ;
- ne partagent pas leurs membres ;
- ne partagent pas leurs rôles ;
- ne partagent pas leurs configurations ;
- ne partagent pas leurs journaux ;
- ne partagent pas leurs modèles privés ;
- ne partagent pas leurs secrets ;
- ne peuvent pas deviner l'existence des autres tenants via l'API.

L'identifiant primaire de tenant est le `guild_id` Discord.

### 2.2.1 Opérations inter-serveurs explicitement autorisées

L'isolation multi-tenant n'interdit pas qu'un **même utilisateur** autorisé sur plusieurs Guilds réalise volontairement une opération de copie, clonage ou export/import entre elles.

La règle est :

```text
Guild A ─X─> Guild B          # aucun accès direct tenant -> tenant
    ▲             ▲
    │             │
    └── User U ───┘           # pont explicite, authentifié et autorisé
```

Pour toute opération inter-serveurs :

1. l'utilisateur doit être autorisé à **lire/exporter** la source ;
2. l'utilisateur doit être autorisé à **créer/importer** sur la destination ;
3. le bot doit être installé et opérationnel sur la destination ;
4. pour un **LIVE_CLONE** directement lu depuis Discord A, DID doit également être installé et disposer d'une visibilité suffisante sur la source A ; un import depuis un artifact déjà exporté n'exige pas que DID soit encore installé sur la source ;
5. la source est convertie en **snapshot logique portable** ;
6. la destination ne reçoit jamais un droit de lecture permanent sur la source ;
7. aucun ID de rôle, salon ou membre source ne doit être réutilisé comme identité destination ;
8. les dépendances sont remappées ou explicitement exclues ;
9. l'opération destination passe par le moteur PLAN / PREFLIGHT / IMPACT / APPLY.

Une copie inter-serveurs est donc une **action utilisateur cross-tenant contrôlée**, pas une fédération de tenants.

### 2.2.2 Principe de portabilité contrôlée

Le produit doit permettre à un même utilisateur autorisé sur plusieurs Guilds de transporter volontairement des éléments entre elles, sans casser l'isolation multi-tenant.

Les mécanismes de portabilité autorisés sont :

- copier/coller inter-Guild ;
- Drag & Drop inter-Guild ;
- clonage vers une autre Guild ;
- export vers une bibliothèque personnelle ;
- import depuis une bibliothèque personnelle ;
- export/import fichier portable ;
- duplication directe « vers un autre serveur ».

Le pont de sécurité est **l'utilisateur authentifié**, jamais la Guild source elle-même.

```text
                 Utilisateur U
                    /     \
                   /       \
        EXPORT sur A       IMPORT sur B
                 |             |
              Guild A       Guild B
                 |             ^
                 +-- snapshot -+
```

Le snapshot portable doit être immutable pendant la compilation du plan destination. Toute nouvelle lecture de la source exige une nouvelle autorisation source.

### 2.2.3 Deux plans de données distincts

L'isolation tenant ne signifie pas que **toute** donnée de la plateforme porte un `guild_id`.

Le produit distingue explicitement :

```text
TENANT DATA PLANE
  données appartenant à une Guild
  -> contrôle par guild_id
  -> RLS tenant

USER CONTROL PLANE
  clipboard personnel
  bibliothèque personnelle
  préférences utilisateur globales
  -> contrôle par discord_user_id
  -> aucune lecture implicite d'une Guild source
```

Un artifact personnel peut conserver `source_guild_id` comme **provenance informative**, mais ce champ ne constitue jamais une capability et ne permet pas de relire la Guild source.

## 2.3 Prévisualisation avant mutation

Toute opération potentiellement destructive ou ayant un impact significatif doit passer par :

```text
INTENTION
   ↓
VALIDATION
   ↓
PLAN
   ↓
ANALYSE D'IMPACT
   ↓
CONFIRMATION
   ↓
APPLY
   ↓
VÉRIFICATION
   ↓
AUDIT
```

## 2.4 Aucune promesse de restauration impossible

Un salon supprimé dans Discord ne peut pas être restauré avec son ancien ID et son historique.

La plateforme peut uniquement :

- conserver un snapshot de sa configuration ;
- recréer un salon équivalent ;
- restaurer les réglages que Discord permet de recréer.

L'UI doit utiliser le terme **« Recréer depuis une sauvegarde »** plutôt que « Restaurer » lorsqu'une identité Discord originale est perdue.

## 2.5 UX compréhensible sans connaissance Discord

Le mode simple ne doit pas obliger l'utilisateur à comprendre les flags de permissions Discord.

Exemple :

```text
Qui peut voir ?
Qui peut écrire ?
Qui peut parler ?
Qui peut gérer ?
Quels bots peuvent intervenir ?
```

Le mode expert expose ensuite les permissions Discord réelles.

---

# 3. Terminologie

## 3.1 Guild Discord

Dans ce document, `Guild Discord` signifie le **serveur Discord réel**.

Une `guild_id` Discord correspond à un tenant.

## 3.2 Groupe logique

Un groupe logique est une abstraction du dashboard permettant de regrouper plusieurs catégories et rôles Discord.

Exemple :

```text
⚔ ALPHA
├── Catégorie Discord : ALPHA - MEMBRES
├── Catégorie Discord : ALPHA - STAFF
├── Rôle Discord : @Alpha
├── Rôle Discord : @Alpha-Officier
└── Rôle Discord : @Alpha-GM
```

Le groupe logique ne crée pas de hiérarchie supplémentaire dans Discord.

## 3.3 Plan

Un plan est la représentation immuable d'un ensemble d'opérations Discord à effectuer.

## 3.4 Snapshot

État connu d'une partie de la configuration Discord à un instant donné.

## 3.5 Drift

Modification faite directement dans Discord et divergeant de l'état géré ou attendu par la plateforme.

---


## 3.6 Language Profile

Un **Language Profile** est une langue/configuration linguistique interne à une Guild, identifiée par un code canonique BCP 47 (`fr`, `en`, `de`, `es`, `pt-BR`, etc.).

Il décrit la langue d'un contenu ou une préférence de visibilité. Il ne crée jamais à lui seul une relation de traduction.

## 3.7 Translation Group

Un **Translation Group** est l'identité interne unique d'une famille de contenus traduits entre eux.

Exemple :

```text
TG-GUIDES-42
├── FR
├── EN
├── DE
└── ES
```

Deux groupes utilisant exactement les mêmes langues restent totalement indépendants si leurs `translation_group_id` diffèrent.

## 3.8 Translation Channel Group

Un **Translation Channel Group** relie les variantes linguistiques d'un même salon logique.

Exemple :

```text
TC-FAQ-17
├── FR -> #aide
├── EN -> #help
├── DE -> #hilfe
└── ES -> #ayuda
```

## 3.9 Visibility Scope

Un **Visibility Scope** décrit une audience métier indépendamment de la langue :

- `GLOBAL` ;
- `ALPHA` ;
- `ALPHA_STAFF` ;
- `BETA` ;
- `PROJECT_X` ;
- autre portée explicite.

La règle fondamentale est :

```text
LANGUAGE != TRANSLATION GROUP != VISIBILITY SCOPE
```

Une langue décrit le contenu ; un Translation Group décrit ce qui est traduit ensemble ; un Visibility Scope décrit qui est autorisé à accéder au contenu.

# 4. Personas

## 4.1 Propriétaire du serveur

Peut :

- installer le bot ;
- initialiser le tenant ;
- administrer l'ensemble de la plateforme ;
- configurer les administrateurs du dashboard ;
- gérer les paramètres critiques.

## 4.2 Administrateur Discord

Par défaut, un utilisateur disposant de la permission Discord `ADMINISTRATOR` peut lancer la configuration initiale si la politique du tenant l'autorise.

## 4.3 Administrateur délégué du dashboard

Peut recevoir une portée limitée sans recevoir l'équivalent de `ADMINISTRATOR` dans Discord.

Exemple :

```text
Paul
├── Alpha : ADMIN_STRUCTURE
├── Alpha : ADMIN_MEMBERS
├── Beta  : READ_ONLY
└── Gamma : NONE
```

## 4.4 GM / responsable de groupe logique

Administre uniquement un sous-ensemble logique du serveur via le dashboard.

## 4.5 Modérateur

Dispose d'un ensemble d'actions de modération autorisées.

## 4.6 Membre

N'accède pas nécessairement au dashboard d'administration.

---

# 5. Installation du bot et onboarding du serveur

## 5.1 Application Discord unique

Le produit utilise une application Discord unique installable sur de nombreux serveurs.

Le bot n'est pas cloné par serveur.

Chaque installation crée un enregistrement `guild_installation` distinct.

## 5.2 Installation Discord

Discord permet une installation serveur à un utilisateur ayant `MANAGE_GUILD`.

Le produit applique une règle de bootstrap plus stricte :

- propriétaire du serveur ; OU
- membre disposant de `ADMINISTRATOR`.

La distinction suivante doit être claire :

```text
AUTORISATION D'INSTALLER CHEZ DISCORD
        ≠
AUTORISATION DE CONFIGURER DANS NOTRE APPLICATION
```

## 5.3 État d'installation

États fonctionnels :

```text
DISCOVERED
INSTALLED
PENDING_SETUP
ACTIVE
DEGRADED
REVOKED
UNINSTALLED
```

## 5.4 Assistant de première configuration

L'assistant de configuration doit :

1. vérifier que le bot est bien membre du serveur ;
2. vérifier l'identité du configurateur ;
3. vérifier owner / `ADMINISTRATOR` selon la politique de bootstrap ;
4. vérifier les permissions du bot ;
5. importer la structure du serveur ;
6. effectuer un premier audit ;
7. présenter les limites ou permissions manquantes ;
8. proposer la configuration du dashboard ;
9. activer le tenant.

## 5.5 Permissions bot

Le produit doit privilégier le principe de moindre privilège.

L'assistant doit être capable d'expliquer :

```text
Permission requise         Pourquoi
MANAGE_CHANNELS             Créer/déplacer/configurer des salons
MANAGE_ROLES                Créer des rôles et gérer les overwrites
VIEW_AUDIT_LOG              Rapprocher les changements et l'audit
MANAGE_WEBHOOKS             Uniquement si fonctions webhook activées
...
```

Le bot ne doit pas demander `ADMINISTRATOR` par défaut simplement pour simplifier le développement.

## 5.6 Perte de permissions

Si un administrateur retire une permission au bot directement dans Discord :

- le bot ne doit pas tenter de contourner la restriction ;
- les capacités concernées deviennent indisponibles ;
- l'UI doit afficher le diagnostic exact ;
- les mutations impossibles sont bloquées avant l'appel Discord.

---

# 6. Authentification du dashboard

## 6.1 Connexion

L'authentification du dashboard utilise **Discord OAuth2 officiel via Authorization Code Grant**.

Flux cible :

```text
Navigateur
   ↓ GET /auth/discord/login
Backend DID
   ↓ state cryptographiquement aléatoire, usage unique, TTL court
Discord /oauth2/authorize
   ↓ code + state
Backend DID /auth/discord/callback
   ↓ validation state
   ↓ échange du code côté serveur uniquement
Discord /api/oauth2/token
   ↓ access/refresh token
Backend DID
   ↓ GET /users/@me
   ↓ GET /users/@me/guilds
Session DID opaque
```

Scopes minimums du dashboard :

- `identify` ;
- `guilds`.

Ne demander un scope supplémentaire que s'il est réellement nécessaire à une fonctionnalité explicite. `email` n'est pas demandé pour le simple login.

Le `client_secret`, l'access token et le refresh token ne sont jamais exposés au JavaScript du navigateur. L'**Implicit Grant** n'est pas utilisé.

L'installation du bot sur une Guild et l'authentification utilisateur du dashboard sont deux flows distincts, même s'ils appartiennent à la même application Discord.

## 6.2 Liste des serveurs accessibles

Le dashboard affiche uniquement les serveurs pour lesquels :

- l'utilisateur est membre ;
- et le bot est installé ou peut être installé ;
- et la politique de la plateforme autorise une action.

## 6.3 Sélecteur de tenant

```text
┌────────────────────────────────────┐
│ Discord Infrastructure Designer    │
├────────────────────────────────────┤
│ Serveur actif :                    │
│ [ Hero Wars France        ▾ ]      │
│                                    │
│ Autres serveurs :                  │
│ • Clan Omega                       │
│ • Discord Test                     │
└────────────────────────────────────┘
```

Changer de serveur doit changer explicitement le contexte tenant.

Aucune donnée d'un tenant ne doit survivre dans l'état visible après changement de tenant, sauf données utilisateur globales non sensibles.

## 6.4 Session

Une session dashboard référence :

- l'utilisateur Discord ;
- le tenant actif ;
- les permissions effectives dans le dashboard ;
- une version de politique d'autorisation.

La session navigateur utilise un identifiant opaque dans un cookie `HttpOnly`, `Secure` en production et avec une politique `SameSite` adaptée au flow OAuth. L'identifiant de session est régénéré après authentification afin d'éviter la fixation de session.

Les mutations basées sur cookie appliquent en plus une protection CSRF explicite ; `state` protège le callback OAuth mais ne remplace pas à lui seul la protection des autres routes mutantes.

## 6.5 Cycle de vie OAuth2

DID conserve le refresh token Discord chiffré côté serveur afin de maintenir une session durable et de pouvoir rafraîchir proprement la liste des Guilds sans redemander une autorisation interactive à chaque expiration :

- il est chiffré au repos ;
- les scopes et expirations sont persistés explicitement ;
- le refresh est réalisé côté backend ;
- un échec de refresh invalide proprement le grant/session concerné ;
- aucune boucle de refresh infinie n'est autorisée.

`Déconnexion` invalide la session DID locale. Une action distincte **« Déconnecter Discord / révoquer l'autorisation »** peut révoquer le grant OAuth2 Discord lorsque l'utilisateur le demande explicitement.

## 6.6 OAuth2 n'est pas l'unique source d'autorisation tenant

`GET /users/@me/guilds` sert à découvrir les Guilds de l'utilisateur et fournit un signal d'autorisation, mais son résultat ne doit pas être considéré comme une permission éternelle.

Pour toute action sensible, le backend combine :

- identité OAuth2 ;
- état d'accès tenant local/cache ;
- RBAC/ACL DID ;
- état Discord observable pertinent ;
- revalidation ciblée lorsque la fraîcheur disponible est insuffisante.

La liste OAuth des Guilds est mise en cache avec fraîcheur explicite afin de ne pas appeler Discord à chaque navigation du dashboard.

Lorsque l'autorisation du dashboard dépend des rôles Discord du **seul utilisateur connecté**, DID utilise la stratégie suivante :

```text
member-role cache frais
    ↓ sinon
lookup ciblé Get Guild Member(user_id) via le bot
    ↓
refresh du cache de cet utilisateur uniquement
```

Le produit ne déclenche jamais un `List Guild Members` complet simplement pour authentifier/autoriser un utilisateur du dashboard.

La **fraîcheur d'autorisation** est plus stricte que la fraîcheur d'affichage. Le cache membre conserve au minimum `observed_at`, `source` et un état de validité. Lorsqu'un événement membre/role fiable est disponible, il invalide immédiatement les décisions dépendantes. Pour une action HIGH/CRITICAL ou toute mutation de droits, si l'état acteur dépasse la fenêtre de fraîcheur d'autorisation configurée, DID effectue un lookup membre ciblé avant d'autoriser l'action. Une page en lecture seule peut accepter une donnée plus ancienne à condition d'afficher sa fraîcheur.

---

# 7. Modèle d'autorisation du dashboard

## 7.1 Rôles de plateforme de base

Rôles de plateforme :

- `OWNER`
- `TENANT_ADMIN`
- `READ_ONLY`

## 7.2 RBAC par capacités

Le modèle complet inclut des capacités granulaires :

```text
structure.read
structure.write
structure.delete
roles.read
roles.write
members.read
members.write
bots.read
bots.audit
permissions.read
permissions.write
plans.create
plans.apply
audit.read
templates.read
templates.write
messages.publish
...
```

## 7.3 Portée par groupe logique

Les capacités peuvent être limitées à un groupe logique :

```text
Principal : ALPHA
Capabilities :
  structure.read
  structure.write
  members.read
  members.write
  messages.publish
```

## 7.4 Rôle Discord autorisant l'accès

Modèle cible :

- le **bootstrap initial** du tenant est réservé au propriétaire ou à un administrateur Discord ;
- après initialisation, les administrateurs autorisés peuvent désigner des utilisateurs et/ou des rôles Discord comme principals du dashboard ;
- les droits sont exprimés par capacités granulaires ;
- ces capacités peuvent être globales à la Guild ou limitées à un groupe logique / Visibility Scope ;
- aucune délégation dashboard n'est présentée comme une permission Discord native lorsqu'elle ne l'est pas.

---

# 8. Vue Structure

## 8.1 Arborescence fidèle

Le navigateur principal représente les objets Discord réels.

```text
▼ 📁 INFORMATIONS
    # règlement
    # annonces

▼ 📁 ALPHA - MEMBRES
    # général
    # stratégie
    🔊 Général

▼ 📁 ALPHA - STAFF
    # officiers
    # recrutement

  # salon-sans-categorie
```

## 8.2 Types de salons

Support prévu :

- texte ;
- vocal ;
- catégorie ;
- annonces ;
- stage ;
- forum ;
- media ;
- threads publics ;
- threads privés ;
- announcement threads.

Les fonctionnalités non documentées pour un type Discord ne doivent pas être inventées.

## 8.3 Badges

Exemples :

```text
# général       🔗 Sync
# direction     🔒 Privé  ⚠ Override local
# bot-stats     🤖 Bot write
```

## 8.4 Panneau de propriétés

Sélectionner un objet ouvre ses propriétés sans quitter l'arborescence.

## 8.5 Fil d'Ariane

```text
Serveur > ALPHA - STAFF > #officiers
```

---

# 9. Drag & Drop

## 9.1 Réordonner les catégories

Doit produire un plan de repositionnement.

## 9.2 Réordonner les salons

Doit respecter la catégorie courante et l'ordre Discord.

## 9.3 Changer de catégorie

Lors d'un déplacement :

```text
Déplacer #stratégie vers ALPHA - STAFF

Permissions :
( ) Conserver les overwrites actuels
(•) Synchroniser avec la catégorie de destination
```

## 9.4 Multi-sélection

Sélection de plusieurs salons puis déplacement groupé.

Le moteur doit toutefois exécuter les appels Discord selon les contraintes de l'API et ne jamais supposer une transaction atomique.


## 9.5 Drag & Drop inter-serveurs

Le sélecteur de serveurs et l'arborescence doivent permettre de glisser un objet depuis une Guild source vers une Guild destination que le même utilisateur est autorisé à administrer.

Exemple :

```text
SERVEUR A                         SERVEUR B
└── 📁 ALPHA - STAFF   ───────►  └── [déposer ici]
```

Le geste inter-serveurs ne doit **jamais signifier un déplacement destructif implicite**. Par défaut, il crée un plan de **copie/clonage**.

## 9.6 Drag gauche : action par défaut sûre

Comportement recommandé :

- dans une même Guild : proposer un déplacement/repositionnement ;
- vers une autre Guild : proposer une copie/clonage ;
- aucune mutation Discord n'est effectuée au simple relâchement avant validation du plan lorsque l'impact est significatif.

## 9.7 Drag droit : Drop Contextuel ⭐

Le maintien du bouton droit pendant le glisser-déposer doit ouvrir, **au relâchement sur une cible valide**, un menu contextuel listant uniquement les actions réellement possibles dans ce contexte.

Exemple catégorie A -> serveur B :

```text
Que voulez-vous faire ici ?

  Copier la structure
  Copier structure + paramètres
  Cloner structure + permissions
  Cloner avec rôles nécessaires...
  Clonage complet compatible...
  Enregistrer comme modèle ici...
  Annuler
```

Exemple salon -> autre catégorie du même serveur :

```text
  Déplacer ici
  Déplacer et synchroniser les permissions
  Copier ici
  Dupliquer avec permissions
  Annuler
```

Le menu dépend :

- du type de source ;
- du type de destination ;
- de la Guild source/destination ;
- des ACL utilisateur ;
- des permissions réelles du bot ;
- des capacités Discord disponibles ;
- des dépendances détectées.

## 9.8 Indicateur visuel de l'action

Pendant le drag, le curseur et l'overlay doivent indiquer clairement :

```text
↪ Déplacer
＋ Copier
⧉ Cloner
⛔ Impossible
? Choisir au relâchement
```

## 9.9 Cibles de drop

Les cibles valides peuvent inclure :

- une position dans la même catégorie ;
- une autre catégorie ;
- la racine de la Guild ;
- une autre Guild autorisée ;
- un groupe logique ;
- la bibliothèque personnelle de modèles ;
- une zone « créer un modèle ».

Une cible invalide doit être visuellement refusée avant le drop.

## 9.10 Accessibilité et alternative sans souris

Toute action disponible par drag & drop doit aussi être réalisable via menu contextuel, commande ou dialogue, afin que le drag reste un accélérateur UX et non la seule voie fonctionnelle.

## 9.11 Sémantique précise des boutons souris

Le dashboard doit différencier explicitement le Drag & Drop initié au bouton gauche et celui initié au bouton droit.

### Bouton gauche

- déplacement dans la même Guild lorsque la cible le permet ;
- copie/clonage proposée lorsqu'on change de Guild ;
- l'action par défaut doit toujours être la moins destructive ;
- les opérations à impact significatif ouvrent la prévisualisation du plan avant APPLY.

### Bouton droit

- un clic droit sans déplacement ouvre le menu contextuel normal de l'objet ;
- un déplacement dépassant le seuil de drag transforme le geste en **Right Drag** ;
- au relâchement sur une cible valide, **aucune mutation n'est exécutée directement** ;
- un **Drop Context Menu** s'ouvre à l'emplacement du relâchement ;
- ce menu propose uniquement les actions valides compte tenu de la source, de la destination, des ACL et des capacités Discord.

```text
RIGHT POINTER DOWN
        ↓
seuil de déplacement dépassé ?
   ├── non → clic droit classique → menu contextuel objet
   └── oui → RIGHT DRAG
                 ↓
          cible de drop valide ?
             ├── non → annulation visuelle
             └── oui → POINTER UP
                         ↓
                  DROP CONTEXT MENU
                         ↓
                  choix utilisateur
                         ↓
                PLAN / PREFLIGHT / APPLY
```

## 9.12 Drag & Drop inter-Guild comme fonction de copie native de l'UX

Un administrateur autorisé sur plusieurs Guilds doit pouvoir afficher plusieurs serveurs dans le navigateur de ressources du dashboard et glisser une ressource de l'un vers l'autre.

Exemples obligatoires :

- salon A → catégorie de Guild B ;
- catégorie A → racine de Guild B ;
- groupe logique A → Guild B ;
- multi-sélection de catégories/salons → Guild B ;
- objet → bibliothèque personnelle ;
- template personnel → Guild destination.

Le dashboard doit pouvoir ouvrir les deux arbres simultanément ou permettre une cible de drop sur le sélecteur de serveurs.

Une copie inter-Guild ne transfère jamais l'objet Discord lui-même : elle exporte un snapshot portable puis crée de nouveaux objets sur la destination.

---

# 10. Menus contextuels

## 10.0 Le clic droit appartient entièrement à l'application ⭐⭐⭐

Le menu contextuel natif du navigateur doit être **désactivé sur toute la surface du dashboard**, sans exception fonctionnelle.

Exigences :

- aucun menu contextuel Chrome/Edge/Firefox ne doit apparaître sur le fond de page ;
- aucun menu navigateur ne doit apparaître sur un champ, tableau, arbre, panneau, texte, icône ou composant ;
- aucun menu navigateur ne doit apparaître pendant ou après un Right Drag ;
- l'événement Web `contextmenu` est intercepté globalement par l'application ;
- l'application décide ensuite d'afficher son propre menu ou de ne rien afficher ;
- les menus contextuels applicatifs doivent être cohérents entre arbre, tableaux, cartes, éditeurs et Drop Context Menu.

```text
contextmenu navigateur
        ↓
 preventDefault() global
        ↓
 Context Action Resolver
        ↓
 ┌───────────────────────┐
 │ actions disponibles ? │
 ├───────────┬───────────┤
 │ oui       │ non       │
 │ menu DID  │ rien      │
 └───────────┴───────────┘
```

Cette règle est globale à l'application, pas seulement à l'arborescence Discord.

## 10.1 Catégorie

Le menu doit notamment pouvoir exposer, lorsque pertinent :

```text
🌐 Langue & traduction >
   Définir la langue...
   Créer des variantes...
   Ajouter une langue...
   Lier à une catégorie existante...
   Gérer les liaisons...
   Gérer la visibilité linguistique...
   Synchroniser la structure...
   Voir le Translation Group
   Dissocier...
```


```text
Ajouter un salon >
Dupliquer >
Permissions >
Visibilité >
Bots >
Synchronisation >
Analyser >
Créer un modèle >
Supprimer
```

## 10.2 Salon

Le menu doit notamment pouvoir exposer :

```text
🌐 Langue & traduction >
   Définir la langue...
   Créer une variante...
   Lier à un salon existant...
   Voir les salons liés
   Changer de groupe...
   Dissocier...
```


```text
Ouvrir
Dupliquer
Déplacer vers >
Synchroniser les permissions
Copier les permissions
Voir comme >
Pourquoi cet accès ? >
Bots autorisés >
Historique
Supprimer
```

## 10.3 Rôle

```text
Voir les membres
Comparer >
Dupliquer
Permissions
Canaux accessibles
Hiérarchie
Audit
Supprimer
```

## 10.4 Membre

```text
Voir les rôles
Voir comme ce membre
Pourquoi voit-il... >
Ajouter à un groupe logique >
Retirer d'un groupe logique >
Permissions effectives
Audit
```

## 10.5 Bot

```text
Voir les permissions
Où peut-il lire ?
Où peut-il écrire ?
Permissions critiques
Rôles
Audit
```

---

# 11. Groupes logiques

## 11.1 Objectif

Fournir une vue métier sans prétendre créer un objet Discord inexistant.

## 11.2 Composition

Un groupe logique peut référencer :

- plusieurs catégories Discord ;
- plusieurs rôles Discord ;
- éventuellement des salons isolés ;
- un ensemble de règles de présentation.

## 11.3 Exemple

```text
Dashboard :

▼ ⚔ ALPHA
   ├── Membres       -> catégorie Discord ALPHA - MEMBRES
   ├── Staff         -> catégorie Discord ALPHA - STAFF
   └── Direction     -> catégorie Discord ALPHA - DIRECTION

Discord réel :

📁 ALPHA - MEMBRES
📁 ALPHA - STAFF
📁 ALPHA - DIRECTION
```

## 11.4 Aucun groupe logique récursif

Éviter une UX qui laisserait croire à des catégories imbriquées.

Tout regroupement visuel plus riche éventuellement proposé par le dashboard doit rester explicitement marqué comme « dashboard only » et ne jamais être rendu comme une hiérarchie Discord native.

## 11.5 Appartenance à un groupe logique

Un groupe logique doit définir explicitement **comment DID détermine qu'un membre appartient à ce scope**.

Sources supportées :

```text
DISCORD_ROLE
  ex. @Alpha -> scope ALPHA

ANY_DISCORD_ROLE
  ex. @Alpha-GM OU @Alpha-Officier -> scope ALPHA_STAFF

ALL_DISCORD_ROLES
  combinaison explicite lorsque nécessaire

EXPLICIT_DID_MEMBERSHIP
  appartenance gérée dans DID lorsque le besoin n'est pas représentable simplement par un rôle Discord

CUSTOM_RULE
  règle personnalisée explicitement configurée, compilée par un resolver central et jamais par le frontend
```

La résolution d'appartenance doit être centralisée dans un **Scope Membership Resolver** utilisé par :

- le moteur de permissions ;
- les ACL du dashboard ;
- le module multilingue `Scope × Language` ;
- la recherche « qui voit quoi ? » ;
- les automatisations ;
- les analyses d'impact.

Un choix de langue ne peut jamais créer à lui seul une appartenance métier.

---

# 12. Création assistée d'une structure multi-groupe

## 12.1 Assistant

Exemple :

```text
Créer un groupe logique

Nom : Alpha
Préfixe salons : alpha
Couleur du rôle : [ ... ]

Modules :
[x] Membres
[x] Staff
[x] Vocal
[x] Annonces
[ ] Recrutement avancé
[ ] Logs
```

## 12.2 Plan généré

```text
+ rôle @Alpha
+ rôle @Alpha-Officier
+ rôle @Alpha-GM
+ catégorie ALPHA - MEMBRES
+ catégorie ALPHA - STAFF
+ #alpha-general
+ #alpha-annonces
+ #alpha-strategie
+ #alpha-officiers
+ vocal Alpha
~ 24 permission overwrites
```

## 12.3 Préflight

Le système vérifie :

- limites de serveur ;
- droits du bot ;
- hiérarchie des rôles ;
- noms ;
- conflits ;
- ressources existantes ;
- compatibilité des types de salon ;
- capacité à créer les overwrites.

---

# 13. Duplication

## 13.1 Duplication de salon

Options :

- structure seulement ;
- structure + paramètres ;
- structure + permissions.

Les messages existants ne font pas partie de la duplication structurelle.

## 13.2 Duplication de catégorie complète

Le moteur doit :

1. lire l'état source ;
2. créer la catégorie destination ;
3. créer les salons enfants ;
4. recopier les paramètres supportés ;
5. mapper les rôles ;
6. créer les overwrites ;
7. appliquer les positions ;
8. vérifier l'état final.

## 13.3 Duplication d'un groupe logique

Exemple :

```text
Source : Alpha
Destination : Beta

@Alpha             -> @Beta
@Alpha-Officier    -> @Beta-Officier
@Alpha-GM          -> @Beta-GM
@Administrateurs   -> @Administrateurs
```

## 13.4 Mapping interactif

L'utilisateur doit pouvoir corriger le mapping avant application.

## 13.5 Remplacement de variables

Templates :

```text
{{GROUP_NAME}}
{{GROUP_SLUG}}
{{MEMBER_ROLE}}
{{OFFICER_ROLE}}
{{GM_ROLE}}
```


## 13.6 Moteur de clonage profond ⭐⭐⭐

Le produit doit distinguer **copie**, **duplication** et **clonage profond**.

- **Copie** : reproduire un objet ou une configuration simple.
- **Duplication** : recréer l'objet et ses enfants directs supportés.
- **Clonage profond** : construire un graphe de dépendances, résoudre les références puis recréer le maximum compatible sur la destination.

## 13.7 Profils de clonage

Profils minimum :

1. `STRUCTURE_ONLY` : catégories/salons, sans permissions spécifiques ;
2. `STRUCTURE_SETTINGS` : structure + paramètres compatibles ;
3. `STRUCTURE_PERMISSIONS` : ajoute les overwrites avec mapping de rôles ;
4. `STRUCTURE_ROLES` : ajoute les rôles nécessaires et leur ordre relatif lorsque possible ;
5. `LOGICAL_GROUP_FULL` : groupe logique + catégories + salons + rôles + politiques dashboard associées ;
6. `MAXIMUM_COMPATIBLE` : reproduit tout ce que le moteur sait garantir comme recréable et fournit explicitement la liste de ce qui ne l'est pas.

## 13.8 Clonage inter-serveurs

Un clonage peut cibler une autre Guild administrée par le même utilisateur.

Avant application :

```text
SOURCE : Serveur A / ALPHA - STAFF
DESTINATION : Serveur B

Objets détectés :
  1 catégorie
  7 salons
  4 rôles référencés
  31 permission overwrites
  2 bots référencés

Mapping :
  @Alpha-Officier  -> @Beta-Officier     [proposé]
  @Alpha-GM        -> @Guild Master      [à confirmer]
  @StatBot         -> ABSENT             [action requise]
```

## 13.9 Graphe de dépendances

Le moteur doit représenter les dépendances avant de cloner :

```text
ALPHA - STAFF
├── #officiers
│   ├── overwrite -> @Alpha-Officier
│   └── overwrite -> @Alpha-GM
├── #stats
│   └── overwrite -> @StatBot
└── 🔊 Réunion
    └── overwrite -> @Alpha-Officier
```

Chaque dépendance reçoit un statut :

- `MAPPED_EXISTING` ;
- `CREATE_NEW` ;
- `SKIP` ;
- `UNRESOLVED` ;
- `IMPOSSIBLE`.

Aucun `UNRESOLVED` critique ne peut être appliqué silencieusement.

## 13.10 Clonage d'un ensemble sélectionné

La multi-sélection permet de construire un bundle portable comprenant, par exemple :

- 3 catégories ;
- 18 salons ;
- 6 rôles ;
- leurs permissions ;
- les métadonnées dashboard associées.

Le moteur déduplique les dépendances communes avant création.

## 13.11 Clonage quasi-complet d'un serveur

Le produit peut proposer **« Cloner la configuration du serveur »**, mais ne doit jamais appeler cela « clone exact » si Discord ne permet pas de recréer certains éléments.

Le rapport de clonage doit distinguer :

```text
RECRÉABLE        PARTIEL / À REMAPPER       NON CLONÉ
structure         bots/intégrations          membres
rôles             webhooks selon cas         historique messages
overwrites        fonctionnalités serveur    audit log
paramètres API    références externes        IDs Discord originaux
```

La liste exacte est calculée par le Capability Engine au moment du plan, afin de rester conforme aux capacités Discord courantes.

## 13.12 Aucune identité source réutilisée

Un clonage crée de nouveaux IDs Discord. Les liens internes du snapshot portable doivent utiliser des identifiants symboliques, jamais considérer qu'un `role_id`, `channel_id` ou `webhook_id` source existera sur la destination.

## 13.13 Presse-papiers utilisateur inter-serveurs

Le clipboard appartient à l'utilisateur, pas à une Guild :

```text
USER
├── clipboard temporaire
├── bibliothèque personnelle
└── Guilds autorisées
    ├── A
    └── B
```

Le clipboard contient un snapshot sérialisé et une provenance, mais ne confère jamais à la Guild destination un accès à la Guild source.

## 13.14 Menu contextuel de clonage

Le clic droit classique et le Drop Contextuel doivent exposer la même famille d'actions :

```text
Cloner >
  Ici
  Vers un autre serveur >
  Comme nouveau groupe logique...
  En remappant les rôles...
  Clonage maximum compatible...
  Enregistrer comme modèle...
```

## 13.15 Pipeline unique de clonage

Toutes les variantes de clonage doivent utiliser le même pipeline fonctionnel :

```text
SOURCE
  ↓
PORTABLE SNAPSHOT
  ↓
DEPENDENCY GRAPH
  ↓
MAPPING / VARIABLES
  ↓
DISCORD CAPABILITY CHECK
  ↓
DESTINATION PLAN
  ↓
PREFLIGHT + IMPACT
  ↓
CONFIRMATION
  ↓
APPLY
  ↓
VERIFY + REPORT
```

Ce pipeline est utilisé par :

- Dupliquer ;
- Copier/Coller ;
- Right Drag ;
- Drag inter-Guild ;
- Export/Import ;
- Bibliothèque personnelle ;
- Clone de groupe logique ;
- Clone de configuration de serveur.

## 13.16 Niveaux de clonage proposés à l'utilisateur

Le dialogue de clonage doit permettre au minimum :

```text
[ ] Structure catégories/salons
[ ] Paramètres des salons
[ ] Permissions / overwrites
[ ] Rôles nécessaires
[ ] Ordre relatif des rôles
[ ] Groupes logiques du dashboard
[ ] Définitions de politiques dashboard portables compatibles (sans bindings utilisateur/rôle implicites)
[ ] Webhooks recréables explicitement sélectionnés
[ ] Onboarding/configurations Discord supportées par le Capability Engine
[ ] Automatisations propres à la plateforme
[ ] Templates associés
```

Les éléments impossibles ou partiels sont affichés avant confirmation.

### 13.16A Portabilité des ACL dashboard

Une politique d'autorisation peut être portable comme **définition**, mais les bindings de principals ne le sont pas par défaut.

Exemple portable :

```text
POLICY ALPHA_MANAGER
  structure.read
  structure.write
  members.read
  members.write
```

Exemple **non portable implicitement** :

```text
Discord user 123 -> ALPHA_MANAGER
Discord role 456 -> TENANT_ADMIN
```

Lors d'un clone cross-Guild :

- aucun utilisateur source ne devient administrateur destination automatiquement ;
- aucun rôle source ne reçoit des droits dashboard destination sans mapping explicite ;
- tout binding destination est une nouvelle décision d'autorisation, auditée et confirmée.

## 13.17 Clonage de configuration de Guild vers Guild

Un utilisateur autorisé sur la source et la destination peut lancer :

> **Cloner la configuration vers...**

La plateforme doit permettre de choisir la Guild destination puis afficher un wizard de mapping.

Exemple :

```text
SOURCE : Production
DESTINATION : Préproduction

Structure                       OK
Rôles                           18 à créer / 4 à mapper
Overwrites                      126 à compiler
Bots                            3 présents / 2 absents
Webhooks                        4 recréables / 1 exclu
Automatisations DID             7 compatibles
Messages historiques            NON CLONÉS
Membres                          NON CLONÉS
Audit Discord                    NON CLONÉ
IDs Discord originaux            NON CONSERVÉS
```

Le clonage doit pouvoir fonctionner en mode :

- **MERGE** : créer uniquement ce qui manque et remapper l'existant ;
- **COPY_AS_NEW** : créer une nouvelle structure parallèle ;
- **RECONCILE** : rapprocher la destination du snapshot source avec diff détaillé ;
- **MAXIMUM_COMPATIBLE** : cloner automatiquement tout ce que le Capability Engine garantit comme compatible.

`RECONCILE` ne doit jamais supprimer automatiquement un objet destination non présent dans la source sans confirmation renforcée.

## 13.18 Bibliothèque personnelle portable

Un utilisateur peut conserver des composants réutilisables indépendamment d'une Guild :

```text
MA BIBLIOTHÈQUE
├── Catégories
├── Groupes logiques
├── Structures complètes
├── Hiérarchies de rôles
├── Profils de permissions
├── Automatisations
└── Bundles personnalisés
```

Une entrée personnelle conserve :

- le snapshot portable ;
- la version du schéma ;
- la provenance informative ;
- les dépendances symboliques ;
- les variables ;
- les capacités requises ;
- la date de création ;
- éventuellement une date d'expiration.

La provenance n'accorde jamais un droit permanent sur la Guild d'origine.

## 13.19 Copie rapide inter-serveurs par menu contextuel

Depuis n'importe quelle ressource clonable :

```text
Clic droit
└── Copier / Cloner vers >
    ├── Serveur A
    ├── Serveur B
    ├── Serveur de test
    ├── Bibliothèque personnelle
    └── Choisir une destination...
```

La liste ne montre que les Guilds pour lesquelles l'utilisateur possède l'autorisation destination requise et où le bot est disponible ou installable selon le workflow prévu.

---

# 14. Permissions : mode simple

## 14.1 Objectif

Exprimer les permissions par intentions.

## 14.2 Visibilité

```text
Qui peut voir ?
[ Tout le monde                    ]
[ Tous les membres                 ]
[ Groupe Alpha                     ]
[ Staff Alpha                      ]
[ Personnalisé...                  ]
```

## 14.3 Écriture

```text
Qui peut écrire ?
[ Tous ceux qui voient             ]
[ Officiers uniquement             ]
[ GM + Bot d'annonces              ]
[ Personnalisé...                  ]
```

## 14.4 Vocal

Questions métier :

- qui voit ;
- qui rejoint ;
- qui parle ;
- qui peut streamer ;
- qui peut gérer.

## 14.5 Bots

Questions :

- quels bots voient ;
- quels bots écrivent ;
- quels bots gèrent.

---

# 15. Permissions : mode expert

## 15.1 Flags Discord

Affichage explicite des permissions Discord.

## 15.2 Sources de permission

Pour chaque permission effective, l'UI doit pouvoir indiquer :

- base `@everyone` ;
- rôle ;
- combinaison des rôles ;
- overwrite catégorie ;
- overwrite salon ;
- overwrite utilisateur ;
- effet d'`ADMINISTRATOR`.

## 15.3 Valeurs tri-état

```text
ALLOW
DENY
INHERIT / UNSET
```

## 15.4 Big integer

Les permission bitfields Discord doivent être traitées comme des entiers de taille suffisante, jamais comme un entier JavaScript classique susceptible de perdre de la précision.

Dans le frontend, utiliser une représentation string/BigInt adaptée.

---

# 16. Synchronisation catégorie / salon

## 16.1 État synchronisé

Le dashboard doit identifier les salons dont les overwrites correspondent à leur catégorie.

## 16.2 État divergent

```text
#direction
⚠ 3 différences avec ALPHA - STAFF
```

## 16.3 Diff détaillé

```text
@Alpha
VIEW_CHANNEL
Catégorie : ALLOW
Salon     : DENY
```

## 16.4 Resynchronisation

Créer un plan avant modification.

---

# 17. Matrice d'accès

## 17.1 Rôles × Salons

```text
                 Alpha   Officier   GM   StatBot
#général           V/E      V/E     V/E     -
#annonces          V        V       V/E     V/E
#officiers         -        V/E     V/E     -
#stats             V        V       V       V/E
```

Légende :

- `V` = voir ;
- `E` = écrire.

## 17.2 Filtres

- rôle ;
- membre ;
- bot ;
- catégorie ;
- groupe logique ;
- permission spécifique.

## 17.3 Édition

Une modification depuis la matrice crée un plan, elle ne doit pas muter Discord directement sans validation.

---

# 18. Voir comme

## 18.1 Membre

Simuler les permissions effectives d'un membre.

## 18.2 Rôle

Simuler un membre fictif ayant un ensemble de rôles.

## 18.3 Nouveau membre

Simuler `@everyone` + rôles par défaut.

## 18.4 Prévisualisation UI

```text
VOIR COMME : Thomas

📁 INFORMATIONS
📁 ALPHA - MEMBRES
📁 ALPHA - STAFF       [masqué]
📁 BETA                [masqué]
```

## 18.5 Après modification

Comparer avant/après sans appliquer.

---

# 19. Pourquoi a-t-il accès ?

## 19.1 Explication

```text
Thomas
  ↓
@Alpha-Officier
  ↓
Permissions de base du rôle
  ↓
Overwrite ALPHA - STAFF
  ↓
VIEW_CHANNEL = ALLOW
```

## 19.2 Cas Administrator

```text
⚠ Thomas possède ADMINISTRATOR.
Les overwrites de salon ne peuvent pas limiter son accès.
```

## 19.3 Action corrective

L'outil peut suggérer une correction, mais ne doit pas appliquer automatiquement une modification sensible sans plan.

---

# 20. Analyse d'impact

## 20.1 Résumé

```text
Modification : ALPHA - STAFF

Membres analysés        : 438
Aucun changement        : 417
Gagnent la visibilité   : 14
Perdent la visibilité   : 7
Bots affectés           : 2
Permissions critiques   : 1
```

## 20.2 Drill-down

Cliquer sur un compteur affiche les membres concernés.

## 20.3 Analyse critique

Exemples :

- gain de `ADMINISTRATOR` ;
- gain de `MANAGE_ROLES` ;
- gain de `MANAGE_CHANNELS` ;
- bot sur-permissionné ;
- salon privé devenant public ;
- perte d'accès du bot lui-même.

---

# 21. Administration déléguée

## 21.1 Principe

Ne pas essayer de reproduire des limitations impossibles dans Discord avec `MANAGE_ROLES`.

La délégation fine est une fonction du dashboard.

## 21.2 Exemple

```text
GM Alpha

Dashboard :
  lire structure Alpha        YES
  modifier salons Alpha       YES
  gérer membres Alpha         YES
  modifier rôles globaux      NO
  voir Beta                   NO
  exécuter plan critique      NO
```

## 21.3 Actions via le bot

Le bot, après validation de l'ACL interne, effectue l'action Discord en son propre nom.

Toutes les actions doivent être auditables avec :

- tenant ;
- utilisateur initiateur ;
- action ;
- cible ;
- résultat ;
- identifiant du plan ;
- raison d'audit Discord si applicable.

---

# 22. Gestion des rôles

## 22.1 Hiérarchie

Vue linéaire réelle de Discord.

## 22.2 Réorganisation

Drag & Drop avec préflight.

## 22.3 Rôle géré

Identifier les rôles gérés par des intégrations lorsque Discord l'indique.

## 22.4 Rôle au-dessus du bot

Afficher :

```text
⛔ Le bot ne peut pas gérer @Direction.
Le rôle du bot doit être placé au-dessus du rôle cible.
```

## 22.5 Duplication

Copier :

- nom ;
- couleur ;
- hoist ;
- mentionable ;
- permissions supportées.

Puis choisir la position.

## 22.6 Détection

- rôle inutilisé ;
- rôle à permissions critiques ;
- rôle redondant ;
- rôle très proche d'un autre.

---

# 23. Gestion des membres

## 23.1 Recherche

Recherche par :

- username ;
- display name ;
- Discord ID ;
- rôle ;
- groupe logique.

## 23.2 Multi-sélection

Actions de masse :

- ajouter rôle ;
- retirer rôle ;
- ajouter au groupe logique ;
- retirer du groupe logique.

## 23.3 Membres et intents

La plateforme doit fonctionner avec le moins d'intents privilégiés possible.

Les fonctionnalités qui nécessitent `GUILD_MEMBERS` doivent être explicitement identifiées et isolées.

## 23.4 Jamais de dépendance à MESSAGE_CONTENT pour l'administration structurelle

Le produit principal doit rester utilisable sans lire le contenu général des messages.

---

# 24. Gestion des bots

## 24.1 Inventaire

Identifier les comptes bots présents dans le serveur.

## 24.2 Fiche bot

```text
StatBot
├── rôles
├── permissions globales
├── salons visibles
├── salons inscriptibles
├── permissions critiques
└── diagnostic
```

## 24.3 Analyse de sur-permission

Exemples :

- `ADMINISTRATOR` ;
- `MANAGE_GUILD` ;
- `MANAGE_ROLES` ;
- `MANAGE_WEBHOOKS`.

## 24.4 Salon bot -> lecture humaine

Profil :

```text
@everyone
VIEW_CHANNEL   ALLOW
SEND_MESSAGES  DENY

@StatBot
VIEW_CHANNEL   ALLOW
SEND_MESSAGES  ALLOW
```

## 24.5 Limite

Un bot disposant d'`ADMINISTRATOR` contourne les overwrites de salon.

L'UI doit le signaler.

---

# 25. Templates

## 25.1 Types

- salon ;
- catégorie ;
- groupe logique ;
- rôles ;
- structure de serveur ;
- permissions ;
- topologie multilingue ;
- profils de langues ;
- politique de visibilité linguistique ;
- liaison de Translation Group sans contenu de messages.

## 25.2 Visibilité

- privé au tenant ;
- système / fourni par la plateforme ;
- partagé explicitement entre tenants uniquement via un mécanisme organisationnel/portable autorisé et consentant.

Aucun template privé ne doit devenir visible à un autre tenant.

## 25.3 Variables

Les variables doivent être typées :

```text
STRING
ROLE_REFERENCE
CHANNEL_REFERENCE
CATEGORY_REFERENCE
COLOR
BOOLEAN
```

## 25.4 Validation

Un template ne doit pas pouvoir produire une structure impossible.

---

# 26. Synchronisation par modèle

## 26.1 Modèle maître

Plusieurs catégories peuvent être liées conceptuellement au même modèle.

## 26.2 Divergence

```text
ALPHA   ✅ conforme
BETA    ⚠ 2 divergences
GAMMA   ✅ conforme
```

## 26.3 Propagation

L'utilisateur sélectionne les cibles.

Aucune propagation automatique destructive n'est autorisée.

---

# 26A. Multilingual Content & Translation Topology ⭐⭐⭐

Ce sous-système est une fonctionnalité majeure du produit.

Il permet d'administrer plusieurs variantes linguistiques d'une même structure Discord, de les rendre visibles aux bonnes audiences, de les relier au bot/service de traduction et de conserver des liaisons strictement indépendantes entre plusieurs familles de contenu d'un même serveur.

## 26A.1 Principe fondamental

Le système doit séparer trois notions :

```text
LANGUE
  "ce contenu est en français"

TRANSLATION GROUP
  "ces contenus sont des variantes traduites les uns des autres"

VISIBILITY SCOPE
  "cette famille est destinée à GLOBAL / ALPHA / ALPHA_STAFF / PROJECT_X..."
```

La plateforme ne doit **jamais** déduire une liaison de traduction uniquement parce que deux ressources partagent la même langue, le même préfixe de nom ou la même position.

## 26A.2 Exemple de deux groupes totalement indépendants

```text
TG-001 : GUIDES
├── FR  -> 📁 GUIDES FR
├── EN  -> 📁 GUIDES EN
└── DE  -> 📁 GUIDES DE

TG-002 : NEWS
├── FR  -> 📁 NEWS FR
├── EN  -> 📁 NEWS EN
└── DE  -> 📁 NEWS DE
```

`TG-001` et `TG-002` utilisent les mêmes langues mais ne sont jamais reliés entre eux.

Toute propagation, traduction, synchronisation ou réparation doit être limitée au groupe explicitement concerné.

## 26A.3 Langue d'une catégorie

Une catégorie Discord peut recevoir une métadonnée DID de langue :

```text
📁 COMMUNAUTÉ FR
Language Profile = fr
```

Cette métadonnée appartient à la plateforme ; Discord ne possède pas de champ natif de langue par catégorie.

## 26A.4 Héritage de langue par les salons

Par défaut, un salon peut hériter de la langue déclarée sur sa catégorie :

```text
📁 COMMUNAUTÉ                      🇫🇷 fr
   # général                       🇫🇷 ↳
   # annonces                      🇫🇷 ↳
   # help                          🇬🇧 en  # override local
```

Valeurs possibles pour un salon :

```text
INHERIT
EXPLICIT_LANGUAGE
UNSPECIFIED
```

L'héritage de langue DID est indépendant du mécanisme Discord de synchronisation des permission overwrites.

## 26A.5 Langues différentes dans une même catégorie

Le système doit supporter :

```text
📁 SUPPORT
├── #aide-fr       🇫🇷
├── #help-en       🇬🇧
├── #hilfe-de      🇩🇪
└── #annonces      —
```

La liaison se fait alors au niveau des salons, pas nécessairement au niveau de la catégorie.

## 26A.6 Translation Category Group

Lorsqu'une catégorie entière est déclinée dans plusieurs langues, la plateforme crée un Translation Group de type `CATEGORY_SET`.

Exemple :

```text
TG-GUIDES-42
│
├── FR -> 📁 GUIDES FR
│       ├── #général
│       └── #aide
│
├── EN -> 📁 GUIDES EN
│       ├── #general
│       └── #help
│
└── DE -> 📁 GUIDES DE
        ├── #allgemein
        └── #hilfe
```

## 26A.7 Translation Channel Groups internes

Chaque salon logique possède sa propre liaison :

```text
TG-GUIDES-42
│
├── TC-GENERAL-001
│   ├── FR -> #général
│   ├── EN -> #general
│   └── DE -> #allgemein
│
└── TC-HELP-002
    ├── FR -> #aide
    ├── EN -> #help
    └── DE -> #hilfe
```

La liaison au niveau catégorie ne remplace jamais la liaison explicite entre salons.

## 26A.8 Groupe de salons sans catégories liées

Un Translation Group peut être de type `CHANNEL_SET` et relier des salons situés dans des catégories totalement différentes :

```text
TC-DISCUSSION-88
├── FR -> 📁 France / #discussion
├── EN -> 📁 International / #chat
└── ES -> 📁 España / #charla
```

La position physique dans Discord ne définit pas la topologie de traduction.

## 26A.9 Topologie HUB_AND_SPOKE

Le cas « une langue pivot reliée à huit langues satellites » doit être nativement supporté.

Exemple :

```text
                   EN
                    ↑
             DE ←   │   → ES
                    │
          IT ←     FR      → PL
                    │
             PT ←   │   → NL
                    ↓
                   TR
```

Configuration :

```text
routing_mode = HUB_AND_SPOKE
hub_language = fr
satellites    = [en, de, es, it, pl, pt, nl, tr]
```

Le provider traduit entre la langue pivot et les satellites selon ses capacités.

## 26A.10 Topologie FULL_MESH

Option : toutes les langues peuvent être sources de toutes les autres.

```text
FR ↔ EN
FR ↔ DE
EN ↔ DE
...
```

Cette topologie doit être activée uniquement si le Translation Provider la supporte et si son coût/charge est accepté.

## 26A.11 Topologie CUSTOM

Le produit doit permettre une matrice de routes explicites :

```text
FR -> EN
FR -> DE
EN -> FR
DE -> FR
ES -> FR
```

Chaque route est une configuration DID indépendante ; aucune route implicite ne doit être ajoutée.

## 26A.12 Création de variantes à partir d'une catégorie source

Depuis :

```text
📁 GUIDES FR
├── #général
├── #aide
└── #annonces
```

Clic droit :

```text
🌐 Langue & traduction
└── Créer des variantes...
```

Assistant :

```text
Langue source : Français

Créer :
☑ English
☑ Deutsch
☑ Español
☑ Italiano
☑ Polski
☑ Português
☑ Nederlands
☑ Türkçe
```

Le système compile une opération de **clone structurel multilingue**, puis crée les liaisons de traduction après création confirmée des ressources Discord.

## 26A.13 Clonage multilingue

Le pipeline fonctionnel est :

```text
CATEGORY SOURCE
      ↓
Portable Snapshot
      ↓
Language Expansion
      ↓
Dependency Graph
      ↓
Visibility Resolver
      ↓
Translation Topology Builder
      ↓
Preflight Discord + Provider
      ↓
Impact Preview
      ↓
Destination Plan
      ↓
Apply
      ↓
Bind Translation Provider
```

La création de ressources Discord et la configuration du provider doivent être deux étapes identifiables et auditables.

## 26A.14 Traduction des noms

Lors du clonage, l'utilisateur choisit :

```text
Noms des catégories/salons
○ identiques dans toutes les langues
○ traduction proposée automatiquement
● personnalisés par langue
```

Une traduction de nom proposée automatiquement est toujours éditable avant APPLY.

Aucune dépendance interne ne doit utiliser le nom comme clé de liaison ; les clés logiques restent stables.

## 26A.15 Ajouter une langue à un groupe existant

Exemple :

```text
TG-GUIDES-42
FR ✓
EN ✓
DE ✓
ES ✓
IT +
```

La plateforme doit pouvoir créer uniquement la variante manquante et ses Channel Groups sans reconstruire les variantes existantes.

## 26A.16 Retirer une langue

Options obligatoires :

```text
Retirer EN du Translation Group

○ Conserver les ressources Discord et les dissocier
○ Conserver les ressources et désactiver le routage de traduction
○ Supprimer les ressources Discord après analyse d'impact
```

La suppression doit être un plan destructif explicite.

## 26A.17 Dissocier sans supprimer

Une catégorie ou un salon lié peut sortir d'un Translation Group sans être supprimé de Discord.

Après dissociation :

- la ressource reste dans Discord ;
- sa métadonnée de langue peut être conservée ;
- aucune traduction du groupe ne doit plus la cibler ;
- la structure des autres variantes n'est pas affectée automatiquement.

## 26A.18 Lier des catégories existantes

Le produit doit permettre :

```text
GUIDES FR   +   GUIDES EN
       ↓ Right Drag / menu contextuel
Créer une liaison de traduction
```

Un assistant propose les correspondances de salons :

```text
FR                         EN
#général       <->         #general
#aide          <->         #help
#annonces      <->         #announcements
```

Toute correspondance ambiguë exige une validation utilisateur.

## 26A.19 Lier des salons existants

Même principe pour :

```text
#aide-fr  <->  #help-en  <->  #hilfe-de
```

Les salons peuvent appartenir ou non à des catégories linguistiques liées.

## 26A.20 Right Drag vers une langue

Un panneau ou une cible de drop représentant une langue peut accepter une catégorie/salon source.

Exemple :

```text
Right Drag : 📁 GUIDES FR -> 🇬🇧 English
```

Menu au relâchement :

```text
Créer une variante anglaise liée...
Cloner sans liaison...
Lier à une ressource anglaise existante...
Créer un modèle multilingue...
Prévisualiser uniquement
Annuler
```

## 26A.21 Right Drag ressource -> ressource

Exemple : `GUIDES EN` déposé au bouton droit sur `GUIDES FR`.

Actions possibles :

```text
Créer un Translation Group FR <-> EN
Ajouter EN au Translation Group de FR
Comparer les structures avant liaison
Cloner les salons manquants puis lier
Annuler
```

Le système ne fusionne jamais deux Translation Groups existants sans action explicite et confirmation d'impact.

## 26A.22 Vue Traductions

Le dashboard doit posséder une vue dédiée :

```text
🌐 TRADUCTIONS

▼ GUIDES                         TG-GUIDES-42
   🇫🇷 GUIDES FR                 ✓
   🇬🇧 GUIDES EN                 ✓
   🇩🇪 GUIDES DE                 ✓
   🇪🇸 GUIDES ES                 ✓

   ├── GENERAL                   TC-001
   │    FR #général
   │    EN #general
   │    DE #allgemein
   │    ES #general
   │
   └── HELP                      TC-002
        FR #aide
        EN #help
        DE #hilfe
        ES #ayuda

▼ NEWS                           TG-NEWS-73
   🇫🇷 NEWS FR                   ✓
   🇬🇧 NEWS EN                   ✓
```

Cette vue doit rendre visuellement impossible la confusion entre `TG-GUIDES-42` et `TG-NEWS-73`.

## 26A.23 Badges dans l'arborescence principale

Exemple :

```text
📁 GUIDES FR        🇫🇷 🔗4
📁 GUIDES EN        🇬🇧 🔗4
📁 NEWS FR          🇫🇷 🔗2
```

Le badge de liaison doit ouvrir directement le Translation Group correspondant.

## 26A.24 Détection de dérive structurelle

Si quelqu'un modifie Discord directement :

```text
GUIDES FR : #faq présent
GUIDES EN : #faq absent
```

Le dashboard affiche :

```text
⚠ Translation Group incomplet

GENERAL      FR ✓ EN ✓ DE ✓
HELP         FR ✓ EN ✓ DE ✓
FAQ          FR ✓ EN ✗ DE ✗
```

Actions :

- ignorer l'écart ;
- ajouter la variante manquante ;
- dissocier le salon source ;
- déclarer une exception structurelle.

## 26A.25 Synchronisation structurelle

Un Translation Group peut utiliser une politique :

```text
MANUAL
PROMPT_ON_DRIFT
TEMPLATE_SYNC
```

Aucune suppression structurelle ne doit être propagée automatiquement sans confirmation explicite et analyse d'impact.

## 26A.26 Langue et visibilité sont indépendantes

Le fait qu'une catégorie soit déclarée `fr` **ne signifie pas automatiquement** qu'elle est cachée aux non-francophones.

Politiques possibles :

```text
OPEN_ALL
LANGUAGE_FILTERED
SCOPE_AND_LANGUAGE
CUSTOM
```

### OPEN_ALL

La langue est une métadonnée de traduction ; aucune restriction supplémentaire n'est créée.

### LANGUAGE_FILTERED

La ressource est visible aux utilisateurs ayant choisi cette langue.

### SCOPE_AND_LANGUAGE

La ressource exige à la fois une portée métier et une langue.

### CUSTOM

L'administrateur configure une politique spécifique, avec validation du Permission Engine.

## 26A.27 Rôles langue globaux

Pour une ressource globale filtrée seulement par langue :

```text
@LANG_FR
@LANG_EN
@LANG_DE
```

Exemple catégorie FR :

```text
@everyone   VIEW_CHANNEL = DENY
@LANG_FR    VIEW_CHANNEL = ALLOW
```

Les rôles langue doivent être réutilisés entre tous les Translation Groups qui utilisent la même audience globale.

## 26A.28 Pourquoi `@ALPHA + @LANG_FR` ne suffit pas

Discord agrège les overwrites des rôles d'un membre ; il ne fournit pas un opérateur logique `AND` entre deux rôles.

La plateforme ne doit donc jamais compiler naïvement :

```text
@ALPHA   -> VIEW_CHANNEL ALLOW
@LANG_FR -> VIEW_CHANNEL ALLOW
```

pour exprimer « Alpha ET Français ».

Ce modèle pourrait donner accès à un membre satisfaisant seulement l'une des dimensions selon les autres overwrites.

## 26A.29 Rôles techniques composés Scope × Language

Lorsque l'accès exige une intersection métier :

```text
Visibility Scope = ALPHA
Language         = FR
```

la plateforme utilise un rôle technique dérivé :

```text
@DID·ALPHA·FR
```

Pour Alpha + FR + EN :

```text
@DID·ALPHA·FR
@DID·ALPHA·EN
```

Ces rôles :

- sont de vrais rôles Discord ;
- ont par défaut `permissions = 0` au niveau Guild ;
- sont `hoist = false` ;
- sont `mentionable = false` ;
- servent principalement de cibles d'overwrites ;
- doivent rester sous le rôle du bot pour être gérables ;
- sont identifiés comme **rôles techniques DID** dans la base ;
- peuvent être masqués par défaut dans la vue métier du dashboard, sans prétendre les masquer dans Discord.

## 26A.30 Mutualisation des rôles techniques

La formule normale est :

```text
TECHNICAL ROLE = VISIBILITY_SCOPE × LANGUAGE
```

et non :

```text
TECHNICAL ROLE = TRANSLATION_GROUP × LANGUAGE
```

Exemple :

```text
TG-GUIDES scope=ALPHA
TG-NEWS   scope=ALPHA
```

réutilisent tous deux :

```text
@DID·ALPHA·FR
@DID·ALPHA·EN
@DID·ALPHA·DE
```

Cela évite une explosion du nombre de rôles.

## 26A.31 Portée spécifique à une liaison

Si un Translation Group possède une audience unique (`PROJECT_X`) alors le scope spécifique peut produire :

```text
@DID·PROJECT_X·FR
@DID·PROJECT_X·EN
```

Ce n'est toujours pas le `translation_group_id` qui crée le rôle ; c'est son Visibility Scope.

## 26A.32 Sélection de plusieurs langues par un membre

Le dashboard doit permettre :

```text
Langues visibles :
☑ Français
☑ English
☐ Deutsch
☑ Español
```

Le Role Resolver attribue les rôles globaux/composés nécessaires selon les scopes auxquels appartient déjà le membre.

Aucune langue n'est obligatoire ni considérée comme « principale » pour un membre. Un membre peut avoir zéro, une ou plusieurs langues visibles. La suppression ou désactivation d'une langue de contenu ne doit donc jamais casser un profil utilisateur parce qu'elle aurait été désignée comme langue principale.

### 26A.32A Cycle de vie des préférences de langue

- si une langue n'est plus utilisée par aucune catégorie/salon mais reste enregistrée comme préférence utilisateur, elle peut être conservée comme préférence inactive ou nettoyée explicitement ;
- désactiver un Language Profile empêche la création de nouveaux bindings actifs pour cette langue sans modifier silencieusement les autres langues d'un membre ;
- supprimer définitivement un Language Profile exige un Dependency Check et un plan explicite pour les variantes, rôles techniques, routes et préférences qui le référencent ;
- aucun fallback automatique vers une autre langue n'est inventé ;
- un membre sans langue visible continue à accéder uniquement aux ressources dont la politique ne nécessite pas de filtre linguistique, sous réserve de ses autres permissions/scopes.

## 26A.33 « Voir toutes les langues »

Le produit ne crée pas automatiquement un rôle universel `ALL_LANGUAGES` qui pourrait casser l'isolation des scopes.

Il calcule et attribue les rôles linguistiques nécessaires dans les scopes effectivement accessibles au membre.

## 26A.34 Exceptions utilisateur

Un administrateur peut autoriser un membre à voir une langue supplémentaire.

L'implémentation privilégiée reste l'attribution du rôle langue/scopé approprié.

Les member-specific overwrites ne doivent pas devenir la stratégie par défaut.

## 26A.35 Optimiseur de rôles

Avant création :

```text
Rôles actuels : 173 / 250

Demandés pour ALPHA :
FR existe
EN existe
DE existe
ES à créer
IT à créer
PL à créer
PT à créer
NL à créer

Nouveaux rôles : 5
Après plan : 178 / 250
```

Le moteur doit :

1. réutiliser les bindings existants ;
2. détecter les rôles techniques orphelins ;
3. calculer le nombre de nouveaux rôles ;
4. tenir compte de la limite Discord ;
5. refuser un plan impossible ;
6. proposer une simplification si possible.

Discord documente actuellement une limite de 250 rôles par Guild.

## 26A.36 Budget d'overwrites

Discord documente actuellement une limite de 1000 permission overwrites par salon.

Le moteur doit exposer :

```text
current_overwrites
projected_overwrites
remaining_budget
```

Les member-specific overwrites massifs sont à éviter.

## 26A.37 Rôles techniques et drift

Si un administrateur modifie manuellement un rôle technique DID dans Discord :

- le changement est détecté ;
- l'UI explique que le rôle est géré par la plateforme ;
- le tenant choisit éventuellement `RECONCILE`, `ADOPT` ou `DETACH` selon la politique ;
- aucune correction destructive silencieuse n'est appliquée.

## 26A.38 Translation Provider

Le produit ne doit pas être couplé à une implémentation unique de traduction.

Concept :

```text
DID Translation Topology
          ↓
Translation Provider Adapter
          ↓
Existing Translation Bot / other provider adapter
```

Le bot de traduction existant peut devenir le premier provider.

La plateforme de gestion reste responsable de :

- la topologie ;
- les langues ;
- les liaisons ;
- les scopes de visibilité ;
- le plan de ressources Discord ;
- le statut de configuration du provider.

Le provider reste responsable de la traduction effective selon son contrat.

## 26A.39 Capacités d'un Translation Provider

C'est **l'adapter DID** qui expose au domaine un modèle de capacités normalisé :

```text
supports_hub_and_spoke
supports_full_mesh
supports_custom_routes
supports_message_edits
supports_message_deletes
supports_attachments
supports_embeds
supports_threads
supports_webhooks
max_languages_per_group
configuration_mode
```

Le bot de traduction existant **n'a pas besoin d'être modifié pour publier lui-même ces capacités**. L'adapter DID les déclare à partir de ce qui est connu et testé de son comportement actuel.

Le Capability Engine refuse ou dégrade explicitement une fonction non supportée.

## 26A.40 Configuration d'un provider existant

### Contrainte : intégration non invasive

Le bot de traduction existant ne doit **pas** être modifié comme prérequis au projet DID.

DID ne doit donc pas imposer :

- l'ajout d'une API dans le bot existant ;
- une modification de son schéma de base de données ;
- une modification de son protocole interne ;
- le partage de son token Discord.

L'adapter doit fonctionner uniquement avec les surfaces déjà disponibles et réellement documentées du bot actuel. Tant que son mécanisme de configuration n'a pas été analysé ou qu'aucune interface existante sûre n'est disponible, DID doit supporter le mode :

```text
MANUAL_CONFIGURATION_REQUIRED
```

Dans ce mode DID :

1. crée et maintient la topologie Discord ;
2. crée les liaisons logiques et les permissions ;
3. vérifie la présence et les permissions du bot de traduction lorsqu'elles sont observables ;
4. génère la configuration attendue / les instructions nécessaires ;
5. marque le Translation Group `PROVIDER_PENDING` jusqu'à validation ;
6. ne prétend jamais avoir configuré le bot si aucune interface existante sûre ne le permet.

Aucune hypothèse non vérifiée sur le bot de traduction existant ne doit être codée dans le domaine.

## 26A.40A Accès Discord du bot/provider de traduction

Si le Translation Provider est lui-même un bot Discord présent sur la Guild, le preflight doit vérifier ses **permissions effectives** sur chaque variante ciblée.

Selon ses capacités, il peut notamment nécessiter :

```text
VIEW_CHANNEL
READ_MESSAGE_HISTORY
SEND_MESSAGES
SEND_MESSAGES_IN_THREADS          # si threads pris en charge
EMBED_LINKS                       # selon rendu
ATTACH_FILES                      # selon transfert de pièces jointes
```

La plateforme ne doit pas recommander `ADMINISTRATOR` comme solution de facilité.

Si le provider n'a pas accès à une catégorie/salon, le plan peut proposer un overwrite minimal explicite pour son identité/rôle Discord lorsque cela est techniquement possible et autorisé.

Les rôles `@LANG_*` ou `@DID·SCOPE·LANG` sont des rôles d'audience humaine et ne doivent pas être détournés comme mécanisme principal d'accès du bot provider.

## 26A.40B Provider absent de la Guild

Si le provider correspond à une application/bot Discord devant être membre du serveur et qu'il est absent :

```text
Provider : ExistingTranslationBot
État     : NOT_INSTALLED
```

Le plan ne doit pas prétendre que la traduction est opérationnelle.

Options :

- structure seulement, provider en attente ;
- installation/configuration du provider si un flow officiel existe ;
- choix d'un autre provider ;
- annulation.

Si le bot est présent mais qu'aucune interface de configuration automatique non invasive n'est disponible, l'état est `MANUAL_CONFIGURATION_REQUIRED` plutôt que `ERROR`.

## 26A.41 Liaison des messages traduits

Si le provider expose le suivi message-à-message, la plateforme peut conserver un identifiant logique :

```text
LM-928372
├── FR message_id=10001 channel=#aide
├── EN message_id=10002 channel=#help
├── DE message_id=10003 channel=#hilfe
└── ES message_id=10004 channel=#ayuda
```

Cette fonction doit être optionnelle et ne transforme pas DID en archive générale des messages Discord.

## 26A.42 Prévention des boucles

Le provider doit garantir qu'un message traduit qu'il republie ne déclenche pas une boucle infinie de retraduction.

La stratégie exacte appartient à l'adapter/provider et doit être testée.

## 26A.43 MESSAGE_CONTENT

La gestion de topologie, des rôles et des liaisons ne nécessite pas `MESSAGE_CONTENT`.

Si le provider de traduction lit le contenu des messages via Gateway, **le provider** doit documenter et gérer l'intent requis selon les règles Discord applicables.

DID ne doit pas demander `MESSAGE_CONTENT` uniquement parce qu'un provider séparé en a besoin.

## 26A.44 Visibilité des catégories traduites

Lorsque possible, les overwrites linguistiques sont posés sur la catégorie et les salons restent synchronisés avec elle.

Cela permet :

- configuration plus lisible ;
- moins de divergence ;
- maintenance simplifiée.

Une exception de salon reste possible si sa langue ou son audience diffère.

## 26A.45 Catégorie mixte

Si une catégorie contient plusieurs langues, la visibilité doit être gérée au niveau salon lorsque nécessaire.

Exemple :

```text
📁 SUPPORT GLOBAL
├── #aide-fr     @LANG_FR
├── #help-en     @LANG_EN
└── #staff       @SUPPORT_STAFF
```

## 26A.45A Onboarding et choix des langues

Les Language Profiles doivent pouvoir être utilisés dans le parcours d'onboarding DID/Discord lorsque les capacités disponibles le permettent.

Exemple utilisateur :

```text
Quelles langues voulez-vous voir ?
☑ Français
☑ English
☐ Deutsch
☑ Español
```

Le choix met à jour l'intention de préférence linguistique, puis le Role Resolver calcule les rôles nécessaires selon les scopes métier du membre.

Si Discord Onboarding attribue un rôle langue comme signal, DID peut observer cette attribution et réconcilier les rôles techniques `Scope × Language` nécessaires.

La sélection d'une langue ne doit jamais donner accès à un scope métier dont le membre ne fait pas partie.

## 26A.46 Source de vérité

Discord reste source de vérité pour l'existence des catégories/salons/rôles.

PostgreSQL DID est source de vérité pour :

- Language Profiles ;
- Translation Groups ;
- Channel Groups ;
- Visibility Scopes ;
- bindings Scope × Language -> rôle Discord ;
- politique de routage ;
- configuration provider ;
- exceptions de synchronisation.

## 26A.47 Suppression d'une ressource Discord liée

Si une catégorie/salon lié est supprimé directement dans Discord :

- la variante est marquée `MISSING` ;
- le groupe reste existant ;
- aucune autre variante n'est supprimée ;
- l'UI propose recréer, remapper, dissocier ou accepter la perte.

## 26A.48 Clonage inter-Guild d'une topologie multilingue

Un Translation Group peut être exporté/cloné vers une autre Guild si l'utilisateur possède les droits source/destination.

Le clone transporte :

- langues ;
- clés logiques ;
- topologie ;
- politique de visibilité ;
- variables ;
- configuration provider portable lorsque compatible.

Il ne transporte jamais comme identités valides :

- IDs de catégories/salons source ;
- IDs de rôles source ;
- IDs de messages ;
- secrets provider ;
- tokens.

Sur la destination, un **nouveau Translation Group indépendant** est créé.

## 26A.49 Pas de traduction live inter-tenant implicite

Par défaut, un Translation Group appartient à **une seule Guild**.

Cloner `TG-A` de Guild A vers Guild B crée `TG-B` indépendant.

Aucune relation de traduction live A ↔ B n'est créée implicitement. Toute liaison organisationnelle entre Guilds exige une configuration explicite, des ACL des deux côtés et un consentement vérifiable.

## 26A.50 Plan et ordre d'application

Pour un nouveau groupe multilingue :

```text
1. validate language profiles
2. resolve/create visibility roles
3. create destination categories
4. create destination channels
5. apply/sync permission overwrites
6. persist translation topology bindings
7. configure Translation Provider
8. verify provider state
9. mark plan complete
```

Si l'étape provider échoue après création Discord, le plan devient `PARTIALLY_APPLIED` avec un diagnostic clair ; les ressources créées ne sont pas supprimées automatiquement.

## 26A.51 Analyse d'impact multilingue

Avant APPLY, afficher :

```text
4 catégories à créer
12 salons à créer
3 rôles techniques à créer
2 rôles techniques réutilisés
48 membres concernés
4 langues
1 Translation Group
3 Translation Channel Groups
Provider : ExistingTranslationBot
Routage : HUB_AND_SPOKE (FR -> EN/DE/ES)
```

Et :

- membres gagnant une visibilité ;
- membres perdant une visibilité ;
- budget de rôles ;
- budget d'overwrites ;
- capacité provider ;
- éléments non traduisibles ou non pris en charge.

## 26A.52 Recherche universelle multilingue

La recherche doit comprendre :

```text
language:fr
translation-group:GUIDES
scope:ALPHA language:en
missing-translation:true
provider:error
```

## 26A.53 Command palette

Exemples :

```text
> ajouter anglais à GUIDES
> afficher les groupes incomplets
> lier #aide-fr avec #help-en
> voir les contenus visibles en français
> resynchroniser ALPHA FR
```

## 26A.54 Audit

Événements DID spécifiques :

```text
LANGUAGE_PROFILE_CREATED
TRANSLATION_GROUP_CREATED
TRANSLATION_VARIANT_BOUND
TRANSLATION_VARIANT_UNBOUND
TRANSLATION_ROUTE_CHANGED
VISIBILITY_SCOPE_LANGUAGE_ROLE_CREATED
MEMBER_LANGUAGE_CHANGED
TRANSLATION_PROVIDER_CONFIGURED
TRANSLATION_DRIFT_DETECTED
TRANSLATION_DRIFT_RESOLVED
```

## 26A.55 Expérience débutant

Le mode Simple ne doit pas exposer `Scope × Language` en premier niveau.

Il demande :

```text
Cette catégorie est dans quelle langue ?
Qui doit pouvoir la voir ?
Quelles autres langues voulez-vous créer ?
Quelle langue sert de source principale ?
```

Le moteur compile la stratégie technique.

## 26A.56 Expérience expert

Le mode Expert permet d'inspecter :

- Language Profile ID ;
- Translation Group ID ;
- Channel Group ID ;
- Visibility Scope ;
- rôle Discord de binding ;
- overwrites compilés ;
- routes provider ;
- statut de synchronisation ;
- dépendances ;
- plan généré.

---

# 27. Plans, brouillons et application

## 27.1 Brouillon

Un plan peut rester non appliqué.

## 27.2 États

```text
DRAFT
VALIDATING
READY
APPLYING
PARTIALLY_APPLIED
APPLIED
FAILED
CANCELLED
SUPERSEDED
```

## 27.3 Opérations

Chaque opération contient :

- type ;
- ressource ;
- état avant ;
- état souhaité ;
- préconditions ;
- dépendances ;
- niveau de risque ;
- stratégie de compensation éventuelle.

## 27.4 Confirmation

Les opérations destructives exigent une confirmation renforcée.

---

# 28. Rollback réaliste

## 28.1 Réversible

Exemples :

- renommer ;
- déplacer ;
- changer permissions ;
- créer un rôle puis le supprimer.

## 28.2 Recréable mais non restaurable

Suppression d'un salon :

- snapshot ;
- recréation possible ;
- nouvel ID ;
- historique perdu.

## 28.3 Non compensable

Le moteur doit savoir marquer une étape `NON_REVERSIBLE`.

---

# 29. Snapshots et versioning

## 29.1 Snapshot de configuration

Contient au minimum :

- guild metadata utile ;
- catégories ;
- salons ;
- positions ;
- rôles ;
- positions des rôles ;
- permission overwrites ;
- groupes logiques ;
- paramètres dashboard.

## 29.2 Diff

```text
Snapshot 104 -> 105

+ #alpha-planning
~ @Alpha-Officier : permissions
- #old-test
```

## 29.3 Recréation

Le bouton doit indiquer exactement ce qui est restaurable.

---

# 30. Audit

## 30.1 Audit Discord

Récupérer les audit logs lorsque la permission est disponible.

Discord conserve actuellement les entrées d'audit pendant 45 jours.

## 30.2 Audit interne

Conserver plus longtemps selon politique de rétention.

## 30.3 Corrélation

Lorsqu'une action est déclenchée par la plateforme :

```text
User dashboard -> Plan -> Operation -> Discord API -> Audit Discord
```

Le système conserve la corrélation.

## 30.4 Drift

Détecter les modifications faites directement dans Discord.

---

# 31. Centre de diagnostic

## 31.1 Santé tenant

```text
Bot connecté                    OK
Permissions nécessaires         9/10
Audit log                       OK
Drift                           3
Plans en erreur                 1
Rôles critiques                 4
Bots Administrator              2
```

## 31.2 Explication

Chaque anomalie propose :

- cause ;
- impact ;
- correction ;
- opération requise.

---

# 32. Recherche universelle

## 32.1 Command palette

`Ctrl+K`

## 32.2 Requêtes structurées

Exemples :

```text
qui peut voir #direction
où StatBot peut écrire
rôles avec administrator
salons non synchronisés
membres Alpha
```

## 32.3 Principe

Peut être implémentée comme moteur de commandes déterministe.

L'IA générative n'est pas une dépendance fonctionnelle du produit.

---

# 33. Commandes Discord

## 33.1 Slash commands

Exemples :

```text
/setup
/status
/access
/dashboard
```

## 33.2 User commands

Exemples :

```text
Voir les accès
Ouvrir dans le dashboard
```

## 33.3 Message commands

Les Message Commands sont supportées pour les actions où le contexte d’un message apporte une valeur réelle (audit, modération, publication, inspection), sans dupliquer inutilement les fonctions déjà plus simples dans le dashboard.

## 33.4 Sécurité

Une commande Discord ne doit jamais contourner les ACL du dashboard.

## 33.5 Localisation des commandes Discord

Les commandes Discord exposées aux utilisateurs doivent elles aussi utiliser les capacités de localisation natives de Discord lorsque disponibles :

- nom de commande ;
- description ;
- sous-commandes ;
- options ;
- choix.

Les packs UI EN/FR/DE/ES alimentent un catalogue de localisation de commandes distinct, compilé vers les locales réellement supportées par Discord. Les réponses aux interactions utilisent la locale fournie dans le payload Discord lorsque l'interaction est initiée dans le client Discord.

Cette localisation Discord ne change pas la préférence `UI Locale` du dashboard.

---

# 34. Communication, campagnes et messages automatisés ⭐⭐⭐

Le produit doit fournir un **Message & Campaign Center** complet. Il ne s'agit pas d'un simple formulaire « envoyer un message », mais d'un moteur de publication multi-Guild, multi-canal, multilingue, planifiable, récurrent et déclenchable par événements.

## 34.1 Principes fondamentaux

Une campagne est un objet applicatif durable qui décrit :

- le contenu à publier ;
- les destinations ;
- les règles de traduction ;
- les mentions autorisées ;
- le mode d'exécution ;
- la planification éventuelle ;
- les conditions événementielles éventuelles ;
- l'historique des livraisons Discord ;
- la politique de validation et de retry.

Une campagne ne confère jamais de droits supplémentaires. Chaque Guild et chaque salon cible sont autorisés et revalidés indépendamment.

## 34.2 Modes de contenu

Le compositeur doit supporter au minimum :

- message texte simple ;
- message texte + un ou plusieurs embeds supportés par Discord ;
- embeds sans texte principal ;
- pièces jointes lorsque la fonction est activée ;
- composants Discord supportés lorsque leur usage est pertinent ;
- templates de messages avec variables ;
- aperçu fidèle avant publication.

Les limites réelles Discord sont validées au moment du plan/preflight et ne doivent pas être dupliquées comme constantes dispersées dans le frontend.

## 34.3 Ciblage des destinations

Discord ne possède pas de « message envoyé à une Guild » sans salon. Une sélection de Guild doit donc être résolue vers un ou plusieurs salons réels.

Le moteur de ciblage doit permettre :

- un salon précis ;
- plusieurs salons d'une Guild ;
- plusieurs Guilds indépendantes administrées par le même utilisateur ;
- le canal de communication par défaut configuré pour chaque Guild ;
- tous les salons compatibles d'un groupe logique explicitement sélectionné ;
- une ou plusieurs variantes d'un Translation Group ;
- une ou plusieurs langues dans un Translation Group ;
- tous les salons portant une politique/tag DID explicitement ciblable ;
- une sélection manuelle multi-Guild/multi-canal ;
- une requête de ciblage enregistrée, résolue à chaque occurrence si la campagne le demande.

Une catégorie n'est jamais traitée comme une destination Discord directe. Si l'utilisateur cible une catégorie, le produit affiche les salons éligibles qu'elle contient et demande/compile la règle de sélection.

## 34.4 Campagnes cross-Guild

Un utilisateur autorisé peut créer une campagne visant plusieurs Guilds qu'il administre.

Exemple :

```text
Campagne : Maintenance dimanche

Destinations :
  Guild A -> #annonces
  Guild B -> #news
  Guild C -> #general-information
```

Règles obligatoires :

1. autorisation de publication vérifiée pour chaque Guild ;
2. permission effective du bot vérifiée pour chaque salon ;
3. aucune Guild cible ne peut lire les données d'une autre Guild ;
4. chaque livraison reste tenant-scopée ;
5. une révocation d'accès sur une Guild peut bloquer cette cible sans bloquer nécessairement les autres ;
6. toutes les livraisons sont auditées individuellement.

## 34.5 Publication immédiate, différée et récurrente

Modes minimum :

```text
MANUAL_NOW
SCHEDULED_ONCE
RECURRING
EVENT_TRIGGERED
EVENT_TRIGGERED_WITH_DELAY
```

Une campagne récurrente utilise une représentation canonique **RRULE + timezone IANA**. L'interface peut proposer un assistant humain (hebdomadaire, premier jour du mois, etc.), mais compile toujours vers cette représentation unique afin d'éviter deux moteurs de planning divergents.

Exemples :

- tous les lundis à 09:00 Europe/Paris ;
- le premier jour du mois ;
- chaque vendredi à 18:00 ;
- 30 minutes après un événement ;
- pendant une fenêtre temporelle définie ;
- jusqu'à une date de fin ou un nombre d'occurrences.

## 34.6 Déclencheurs événementiels

Le moteur peut déclencher une campagne à partir des événements DID/Discord normalisés compatibles, par exemple :

- membre rejoint la Guild ;
- membre reçoit/perd un rôle ;
- membre rejoint/quitte un scope logique ;
- création/suppression/modification d'une ressource ;
- événement Discord planifié ;
- plan DID terminé/échoué ;
- drift détecté ;
- Translation Group dégradé/réparé ;
- provider de traduction indisponible/rétabli ;
- événement métier interne configuré.

Toute condition nécessitant le contenu des messages Discord doit être explicitement identifiée comme dépendante de `MESSAGE_CONTENT`; cette dépendance ne doit jamais apparaître implicitement.

### 34.6A Sources de déclenchement explicites

Une campagne événementielle multi-Guild doit déclarer **dans quelles Guilds/sous-scopes les événements sont autorisés à la déclencher**.

Un événement reçu pour Guild A ne peut jamais déclencher une campagne simplement parce que son `event_type` correspond. Il faut un binding de source explicite et autorisé :

```text
Trigger WELCOME
Source autorisée : Guild A / scope ALPHA
Destinations      : Guild A #welcome + Guild B #news
```

La source du trigger et chacune des destinations constituent des décisions d'autorisation séparées.

## 34.7 Conditions composables

Les déclencheurs peuvent être filtrés par conditions `AND/OR/NOT` :

```text
WHEN member_joined
AND logical_group == ALPHA
AND member_has_role != BANNED
THEN send WELCOME_ALPHA
```

Le moteur doit afficher en langage humain le résultat de la règle avant activation.

### 34.7A Prévention des boucles d'automatisation

Tout événement interne conserve une chaîne de causalité/corrélation. Une campagne événementielle doit pouvoir distinguer :

```text
HUMAN/DISCORD_EXTERNAL
DID_PLAN
DID_CAMPAIGN
DID_TRANSLATION
SYSTEM
```

Par défaut :

- une campagne ignore les événements qu'elle a elle-même causés lorsque ceux-ci pourraient la redéclencher ;
- une profondeur maximale d'automatisation est appliquée ;
- les cycles de causalité connus sont bloqués ;
- un cycle potentiel cross-Guild est diagnostiqué avant activation lorsque le graphe des triggers permet de le détecter ;
- un événement redélivré avec le même `event_id` ne crée pas une nouvelle occurrence.

## 34.8 Idempotence des livraisons

Une occurrence ne doit pas être publiée deux fois parce qu'un worker redémarre ou qu'un job est redélivré.

Chaque livraison possède une clé d'idempotence logique au minimum dérivée de :

```text
campaign_id
occurrence_id
Guild destination
channel destination
language/variant
```

Pour `Create Message`, DID utilise un `nonce` déterministe avec `enforce_nonce=true` lorsque ce mécanisme est supporté par la version Discord ciblée, en plus du contrôle local. Le nonce reste stable lors des retries d'une même delivery.

## 34.9 Historique des publications

Pour chaque livraison :

- campagne ;
- occurrence ;
- Guild ;
- salon ;
- langue/variante ;
- utilisateur ou trigger initiateur ;
- snapshot du contenu réellement envoyé ;
- `discord_message_id` ;
- statut ;
- dates de tentative/succès/échec ;
- erreur Discord normalisée ;
- état de traduction/validation ;
- état d'embed ;
- politique de mentions.

Le produit ne doit pas devenir une archive générale des conversations Discord : seuls les messages créés/gérés par le Campaign Engine sont conservés selon la politique de rétention.

## 34.10 Mentions sûres

Le compositeur expose explicitement les mentions réellement autorisées.

Par défaut, une campagne ne doit pas pouvoir déclencher accidentellement `@everyone`, `@here`, une mention de rôle massive ou des pings utilisateurs simplement parce qu'un texte contient une syntaxe ressemblante.

L'UI doit séparer :

```text
Texte affiché
≠
Notifications/pings réellement autorisés
```

La configuration `allowed_mentions` est construite explicitement par le backend.

## 34.11 Publication dans un salon multilingue

La **langue source du contenu de campagne** est une propriété du message/template et n'est jamais déduite du `UI Locale` du dashboard. Changer l'interface de français vers anglais ne change donc aucune traduction ou variante de campagne.

Lorsqu'une destination appartient à un `Translation Channel Group`, le compositeur détecte les variantes liées et demande :

```text
Ce salon possède des variantes liées : FR EN DE ES

Que souhaitez-vous publier ?

○ Uniquement dans le salon sélectionné
○ Publier la source et laisser le bot de traduction existant travailler
● Traduire et publier dans les variantes liées avec DID
○ Choisir les langues...
```

Le choix est mémorisable au niveau du template/campagne mais reste modifiable.

## 34.12 Prévention des doubles traductions

Le bot de traduction existant n'est pas modifié comme prérequis.

Avant d'activer `DID_TRANSLATE_AND_FANOUT`, la plateforme doit connaître ou faire confirmer le comportement du bot de traduction existant vis-à-vis des messages envoyés par DID/bots.

Modes :

```text
SOURCE_ONLY
SOURCE_ONLY_PROVIDER_HANDLES_TRANSLATION
DID_TRANSLATE_AND_FANOUT
MANUAL_LANGUAGE_VARIANTS
```

Si DID ne peut pas garantir qu'un fan-out direct n'entraînera pas une nouvelle traduction par le bot existant, l'UI affiche un avertissement et le mode doit rester explicitement confirmé/configuré.

## 34.13 Traduction DID avec `googletrans`

Pour les campagnes traduites directement par DID, l'implémentation Python demandée utilise `googletrans` derrière un adapter interne dédié.

Le moteur ne doit **jamais** transmettre le message Discord brut à `googletrans` puis republier aveuglément le résultat.

Pipeline obligatoire :

```text
MESSAGE MODEL
   ↓
DiscordSafeParser
   ↓
Protected AST / token stream
   ↓
Glossary + terminology policy
   ↓
Context-preserving masked translation unit
(message/paragraph/block as large as safely possible)
   ↓
googletrans
   ↓
Reassembly
   ↓
TechnicalIntegrityValidator
   ↓
Semantic/terminology checks
   ↓
Preview / approval policy
   ↓
Publish
```

## 34.13A Conserver le contexte linguistique et valider par tests réels

La protection des tokens techniques ne doit **pas** conduire à traduire des fragments de phrase isolés lorsque cela détruit le contexte grammatical ou sémantique.

Principe cible :

```text
MESSAGE / PARAGRAPHE COHÉRENT
        ↓
parser Discord-safe
        ↓
remplacement des seuls spans non traduisibles par placeholders robustes
        ↓
UNITÉ MASQUÉE CONSERVANT LE CONTEXTE
        ↓
googletrans
        ↓
restauration exacte des placeholders
        ↓
validation technique + contrôle qualité
```

Le choix exact de l'unité envoyée à `googletrans` **ne doit pas être figé arbitrairement avant tests réels**. L'implémentation doit comparer au minimum :

1. message complet masqué ;
2. paragraphe/bloc cohérent masqué ;
3. découpage aux frontières de paragraphes lorsque la taille ou la structure l'exige ;
4. découpage plus fin uniquement pour les cas où les essais démontrent un meilleur résultat ou lorsqu'une contrainte technique l'impose.

La stratégie retenue peut différer selon le type de contenu (message simple, Markdown complexe, embed, liste, texte multiligne), mais elle doit toujours privilégier **le contexte linguistique maximal compatible avec l'intégrité Discord**.

Avant de considérer le moteur prêt, un **corpus de régression réel** doit être constitué avec des messages représentatifs en français, anglais, allemand et espagnol, comprenant notamment :

- phrases longues et courtes ;
- négations, pronoms et références contextuelles ;
- plusieurs phrases dans un même paragraphe ;
- listes et Markdown ;
- mentions, URLs, emojis, timestamps et commandes au milieu des phrases ;
- termes Hero Wars / noms propres / acronymes ;
- embeds ;
- mélanges de texte et code ;
- contenus contenant plusieurs placeholders techniques.

Les tests doivent comparer plusieurs stratégies de masquage et de segmentation avec le **vrai `googletrans`**, et non seulement des mocks. Le meilleur compromis observé devient la stratégie par défaut et reste couvert par des tests de non-régression.

Critères :

- **100 % d'intégrité technique** sur le corpus : aucun token protégé modifié, perdu, dupliqué ou déplacé de façon invalide ;
- aucune publication automatique si la restauration ou le fingerprint technique échoue ;
- qualité linguistique évaluée sur le texte reconstruit avec son contexte complet ;
- les traductions validées manuellement de templates/campagnes récurrentes doivent pouvoir être réutilisées afin d'éviter une nouvelle variation inutile ;
- une back-translation éventuelle peut servir de signal de diagnostic mais ne constitue pas, seule, une preuve de qualité.

L'objectif produit est de tendre au plus près de 100 % de qualité observée, sans prétendre qu'un moteur statistique/non officiel garantit mathématiquement zéro erreur sémantique.

## 34.14 Éléments techniques protégés de la traduction

Au minimum, ne doivent jamais être modifiés par le moteur de traduction :

- URL brutes ;
- destination URL des liens Markdown ;
- mentions utilisateur `<@...>` / `<@!...>` ;
- mentions rôle `<@&...>` ;
- mentions salon `<#...>` ;
- commandes slash référencées `</...:ID>` ;
- emojis Discord custom `<:name:id>` ;
- emojis animés `<a:name:id>` ;
- timestamps Discord `<t:...>` ;
- navigation Discord `<id:...>` ;
- blocs de code ;
- code inline ;
- identifiants techniques explicitement protégés ;
- variables/template placeholders ;
- `custom_id` de composants ;
- URLs d'embed, images, thumbnails, author URLs ;
- identifiants de ressources ;
- fragments configurés `DO_NOT_TRANSLATE`.

Les marqueurs Markdown structurels sont parsés et reconstruits ; leur contenu textuel peut être traduit uniquement lorsque cela est sûr.

## 34.15 Validation fail-closed

Après traduction, le système reconstruit une empreinte technique de l'original et du résultat.

Exemple :

```text
Original protected tokens : 17
Translated protected tokens: 17
Exact token identities      : 17/17
URL identities              : 4/4
Discord mention IDs         : 6/6
Template variables          : 3/3
Markdown/code integrity     : OK
```

Si une seule contrainte technique échoue :

> **LA VERSION TRADUITE N'EST PAS PUBLIÉE.**

Le moteur peut retenter avec une segmentation plus fine, puis demander une validation manuelle si nécessaire.

Cette règle permet de garantir l'intégrité technique des balises et références même si le moteur linguistique externe se comporte de manière inattendue.

## 34.16 Glossaire et terminologie

Chaque Guild, groupe logique ou Translation Group peut définir un glossaire :

```text
Hero Wars        -> DO_NOT_TRANSLATE
Guild Master     -> FR: Maître de guilde
Outland          -> DO_NOT_TRANSLATE
Energy           -> FR: Énergie | DE: Energie | ES: Energía
```

Types de règles :

- `DO_NOT_TRANSLATE` ;
- `FORCE_TRANSLATION` par langue ;
- remplacement exact ;
- remplacement sensible/insensible à la casse ;
- règle regex bornée et validée ;
- terme contextualisé par Translation Group/template.

Les termes protégés sont contrôlés avant et après traduction.

Lorsque plusieurs glossaires s'appliquent, la résolution est déterministe du plus spécifique au plus général :

```text
TEMPLATE
→ TRANSLATION_GROUP
→ LOGICAL_GROUP
→ GUILD
```

À niveau identique, la priorité explicite puis l'identifiant stable départagent les règles. Une collision de deux `FORCE_TRANSLATION` incompatibles au même niveau est signalée avant publication et ne doit pas être résolue silencieusement.

## 34.17 Traduction des embeds

La traduction distingue les champs textuels des champs techniques.

Traduisibles selon configuration :

- titre ;
- description ;
- noms de fields ;
- valeurs de fields ;
- footer text ;
- author name.

Jamais traduits :

- URLs ;
- couleurs ;
- timestamps structurés ;
- URLs d'images/icons ;
- IDs ;
- metadata Discord.

## 34.18 Traduction des composants

Pour les composants supportés :

- `label` peut être traduit ;
- texte descriptif peut être traduit ;
- `custom_id` n'est jamais traduit ;
- URL d'un bouton lien n'est jamais traduite ;
- valeurs techniques/select values ne sont pas traduites sauf déclaration explicite.

## 34.19 Templates localisés et campagnes récurrentes

Pour une campagne récurrente, la stratégie privilégiée est de **pré-générer et valider les variantes linguistiques** plutôt que de retraduire exactement le même texte à chaque occurrence.

```text
Template Maintenance
├── FR APPROVED
├── EN APPROVED
├── DE APPROVED
└── ES APPROVED
```

Le scheduler publie ensuite les snapshots approuvés.

Si des variables dynamiques existent, chaque variable déclare son type :

```text
{{server_name}}        NON_TRANSLATABLE
{{event_date}}         LOCALIZED_VALUE
{{dynamic_sentence}}   TRANSLATABLE_TEXT
{{url}}                PROTECTED_URL
```

## 34.20 Politique de qualité de traduction

La plateforme doit distinguer :

- **intégrité technique** : vérifiable et obligatoire ;
- **respect du glossaire** : vérifiable et obligatoire ;
- **qualité linguistique/sémantique** : contrôlable mais jamais considérée mathématiquement parfaite par simple traduction automatique.

Politiques possibles :

```text
AUTO_PUBLISH_AFTER_TECHNICAL_VALIDATION
REVIEW_ON_WARNING
ALWAYS_REVIEW_NEW_TRANSLATION
APPROVED_VARIANTS_ONLY
```

Une campagne automatique critique peut imposer `APPROVED_VARIANTS_ONLY`.

## 34.21 Preview multilingue

Avant publication :

```text
┌──────────── FR ────────────┬──────────── EN ────────────┐
│ Maintenance à 22h          │ Maintenance at 10 PM      │
│ <@&123...>                 │ <@&123...>                │
│ https://status...          │ https://status...         │
└────────────────────────────┴────────────────────────────┘

Technical integrity: ✅
Glossary:             ✅
Mentions:              1 role, ping disabled/enabled explicit
```

L'utilisateur peut éditer manuellement une variante avant approbation.

## 34.22 Édition et suppression d'une campagne

Le produit doit distinguer :

- modifier le template pour les occurrences futures ;
- modifier un message déjà publié lorsque Discord et l'auteur le permettent ;
- annuler les occurrences futures ;
- désactiver temporairement une campagne ;
- supprimer la campagne DID sans supprimer rétroactivement les messages Discord ;
- supprimer explicitement des messages déjà publiés via une action séparée et auditée.

Lors de l'édition d'un message DID déjà publié :

- `allowed_mentions` est toujours envoyé explicitement à nouveau ;
- les attachments à conserver sont reconstruits explicitement selon le contrat Discord ;
- aucune édition ne doit réactiver accidentellement un ping précédemment neutralisé ;
- le nouvel état et l'ancien sont audités.

## 34.23 Simulation

Une campagne peut être simulée sans publier :

```text
12 Guilds ciblées
48 salons résolus
4 langues
132 livraisons prévues
3 salons non accessibles au bot
2 traductions nécessitent une revue
0 corruption technique
```

---

# 35. Onboarding Discord

## 35.1 Support

Fournir une UI dédiée lorsque le serveur est compatible.

## 35.2 Validation

Le dashboard vérifie les exigences Discord avant mutation.

## 35.3 Aucun faux onboarding

Si Discord refuse une configuration, le produit l'indique clairement plutôt que de simuler un état non appliqué.

---

# 36. Webhooks

## 36.1 Inventaire

Lister les webhooks lorsque les permissions le permettent.

## 36.2 Sécurité

Les tokens webhook sont des secrets.

Ils ne doivent jamais :

- être exposés au frontend ;
- être journalisés ;
- apparaître dans les erreurs ;
- être stockés en clair si la persistance est nécessaire.

---

# 37. Limites Discord à gérer

À la date du document, Discord documente notamment :

- 500 channels maximum par Guild, catégories incluses ;
- 250 rôles maximum ;
- 1000 permission overwrites maximum par salon ;
- 50 salons enfants maximum par catégorie ;
- audit log Discord conservé 45 jours.

**Ne pas introduire de limite `50 catégories/Guild` : aucune limite officielle distincte n'est retenue tant qu'elle n'est pas explicitement documentée par Discord. Les catégories consomment le budget global de channels.**

Ces valeurs doivent être centralisées dans une couche de capacité et revalidées périodiquement contre la documentation Discord.

Ne jamais disperser des constantes Discord dans le code métier.

## 37.1 Channel Obfuscation — changement Discord du 16 novembre 2026

Discord a annoncé qu'à partir du **16 novembre 2026** :

- le Gateway continue à envoyer les salons non visibles par le bot, mais avec métadonnées obfusquées et flag `CHANNEL_OBFUSCATED` ;
- `id`, `type`, `position` et `parent_id` restent exploitables côté Gateway ;
- `GET /guilds/{guild.id}/channels` omet les salons pour lesquels le bot n'a pas `VIEW_CHANNEL` ;
- un salon redevient complet via `CHANNEL_UPDATE` lorsque le bot récupère la visibilité.

DID doit être compatible **avant** cette date et tester le mode d'obfuscation proposé par Discord.

Le produit doit distinguer :

```text
VISIBLE
OBFUSCATED
ACCESS_LOST
UNKNOWN
DELETED_CONFIRMED
USER_CONFIRMED_DELETED
```

Après purge détaillée, l'objet quitte le cache actif et n'est plus représenté que par un `PURGED_TOMBSTONE` minimal dans le registre de tombstones.

Une absence dans une réponse HTTP **ne suffit jamais à conclure qu'un salon connu a été supprimé**.

---

# 38. Rate limits et gouvernance des requêtes Discord

## 38.1 Principe cache-first

Une consultation du dashboard ne doit pas provoquer automatiquement un appel Discord.

Chemin normal :

```text
Frontend
  -> API DID
  -> cache local PostgreSQL / Redis
  -> réponse
```

Discord REST est utilisé pour :

- synchronisation initiale ;
- réconciliation périodique ;
- vérification ciblée avant/après mutation lorsque nécessaire ;
- données explicitement demandées et absentes/stale du cache ;
- opérations de création/modification/suppression.

## 38.2 Gateway-first pour la fraîcheur

Les événements Gateway constituent le mécanisme principal de mise à jour incrémentale du cache :

```text
CHANNEL_CREATE / UPDATE / DELETE
GUILD_ROLE_CREATE / UPDATE / DELETE
GUILD_UPDATE
GUILD_MEMBER_* lorsque GUILD_MEMBERS est activé
THREAD_*
...
```

Les réponses réussies aux mutations DID doivent également mettre à jour le cache immédiatement (**write-through**) sans attendre un GET supplémentaire.

## 38.3 Pas de temporisation ou quota codé en dur

Ne pas implémenter une stratégie générale telle que :

```text
sleep(1)
```

Discord demande de respecter les headers de rate limit et `Retry-After` / `retry_after`.

La limite globale actuelle de référence est de 50 requêtes/s par bot, mais DID ne doit pas construire sa logique en supposant qu'elle est immuable.

## 38.4 Rate Limit Governor

Toutes les requêtes REST utilisant le bot token passent par une chaîne contrôlée à deux niveaux :

```text
DID Workload Governor
  -> Discord Adapter / library limiter
  -> Discord REST
```

Le **limiteur protocolaire** de la librairie Discord retenue reste responsable du respect concret des buckets, headers et `429` lorsqu'il fournit cette garantie. DID ne doit pas réimplémenter de façon concurrente un second limiteur incompatible avec la librairie.

Le **DID Workload Governor**, au-dessus, est responsable de la charge applicative :

- limiter la concurrence globale et par type de travail ;
- mettre en file les plans massifs ;
- coalescer les lectures identiques ;
- ralentir/suspendre les réconciliations de fond sous pression ;
- appliquer une équité entre Guilds afin qu'un tenant très actif ne monopolise pas le token partagé ;
- prioriser les travaux sans affamer les tâches de maintenance ;
- éviter que plusieurs processus utilisant le même token consomment indépendamment le budget global sans coordination ;
- mesurer les waits, `429`, erreurs invalides et profondeur de queue.

Ordre de priorité indicatif :

```text
1. continuation sûre d'un APPLY déjà engagé
2. vérification post-mutation / récupération UNKNOWN_OUTCOME
3. preflight/refresh ciblé nécessaire à une action utilisateur
4. refresh utilisateur explicite
5. réconciliation de fond
```

La solution retenue centralise la majorité des appels bot-token REST dans un **Discord I/O Worker** unique. Si plusieurs processus doivent émettre des appels REST avec le même token, ils partagent obligatoirement l'état de coordination des budgets, backoff, concurrence et fairness.

## 38.5 Invalid Request Budget

Discord applique actuellement une limite de **10 000 requêtes invalides sur 10 minutes par IP** pour les statuts concernés (`401`, `403`, `429`, avec nuances documentées par Discord).

DID doit donc :

- prévalider les permissions afin d'éviter les `403` prévisibles ;
- stopper rapidement après token invalide ;
- ne pas retry aveuglément les `4xx` ;
- mesurer le nombre de réponses invalides sur fenêtre glissante ;
- alerter avant d'approcher le seuil ;
- considérer une série de `403` comme un défaut de preflight et non comme une charge normale.

## 38.6 Coalescing et single-flight

Deux demandes simultanées de refresh de la même ressource ne doivent pas déclencher deux GET Discord identiques.

```text
refresh guild 123 roles
refresh guild 123 roles
refresh guild 123 roles
        -> 1 requête REST partagée
```

Les refresh de fond doivent être dédupliqués, regroupés et étalés avec jitter.

## 38.7 Réconciliation adaptative

La réconciliation périodique n'utilise pas un polling agressif identique pour toutes les Guilds.

La priorité dépend notamment de :

- temps depuis le dernier reconcile ;
- activité récente de la Guild ;
- perte/reprise de Gateway ;
- détection d'un gap de séquence ou session non reprise ;
- plan en attente ;
- drift déjà détecté ;
- niveau de couverture/obfuscation ;
- budget rate-limit disponible.

Les Guilds ne doivent pas toutes être réconciliées à la même seconde.

Politique initiale recommandée, **configurable et adaptative** :

```text
Gateway connecté + aucun gap     -> pas de polling fréquent
Guild active                     -> full structural reconcile cible <= 6 h
Guild peu active                 -> full structural reconcile cible <= 24 h
Gateway gap / non-resume         -> reconcile prioritaire immédiat
Avant plan critique sur état âgé -> refresh ciblé des ressources concernées
```

Ces valeurs sont des objectifs d'exploitation DID, pas des limites Discord codées en dur. Le scheduler peut les allonger sous pression rate-limit.

## 38.8 Optimisation des mutations massives

Le Plan Compiler doit utiliser les endpoints bulk Discord lorsqu'ils existent et sont adaptés, par exemple pour :

- modifier plusieurs positions de salons ;
- modifier plusieurs positions de rôles.

Les créations restent dépendantes de nouveaux IDs Discord et sont séquencées selon le DAG.

## 38.9 Métriques obligatoires

Au minimum :

```text
discord_rest_requests_total
cache_hit_ratio
cache_age_seconds
rate_limit_wait_seconds
rate_limit_429_total
invalid_requests_10m
rest_queue_depth
reconcile_duration_seconds
reconcile_requests_total
singleflight_saved_requests_total
```

---

# 39. Gestion des erreurs

## 39.1 Erreur lisible

Exemple :

```text
Discord a refusé l'opération.

Cause :
Le bot ne possède pas MANAGE_ROLES sur cette cible.

Action :
Déplacer le rôle du bot au-dessus de @Officier
ou modifier sa permission.
```

## 39.2 Erreur partielle

Un plan peut être partiellement appliqué.

L'UI doit afficher chaque étape.

---

# 40. Exigences UX

## 40.1 Aucun rechargement complet pour les opérations courantes

## 40.2 Optimistic UI uniquement si l'état peut être corrigé

Pour les mutations Discord sensibles, préférer :

```text
planned -> applying -> confirmed
```

plutôt qu'une illusion de succès instantané.

## 40.3 Desktop first

Le constructeur avancé est d'abord optimisé desktop.

## 40.4 Responsive

Le dashboard doit rester consultable sur mobile pour :

- audit ;
- validation ;
- membres ;
- alertes ;
- plans.

## 40.5 Accessibilité

Navigation clavier, contrastes, focus visible, ARIA adaptée.

## 40.6 Dashboard intégralement multilingue ⭐⭐⭐

**Aucune chaîne d'interface destinée à l'utilisateur ne doit être codée en dur dans une langue.**

Doivent être traduits sans exception :

- titres ;
- labels ;
- boutons ;
- menus ;
- menus contextuels ;
- Drop Context Menus ;
- Command Palette ;
- toasts ;
- tooltips ;
- placeholders ;
- dialogues ;
- confirmations ;
- erreurs ;
- avertissements ;
- états vides ;
- loaders et progression ;
- badges système ;
- propriétés ;
- filtres ;
- colonnes de tableaux ;
- textes d'aide ;
- onboarding ;
- écrans d'audit ;
- diagnostics ;
- descriptions de permissions ;
- textes ARIA/accessibilité ;
- notifications internes ;
- messages de jobs ;
- descriptions des actions du `ActionRegistry` ;
- textes des assistants/wizards ;
- toute autre chaîne système visible.

Les noms/texte créés par l'utilisateur ou provenant de Discord restent naturellement du contenu utilisateur et ne sont pas considérés comme une chaîne UI à traduire automatiquement.

## 40.7 Langues UI fournies par défaut

Le produit est livré au minimum avec des packs **complets** :

```text
🇬🇧 English   en
🇫🇷 Français  fr
🇩🇪 Deutsch   de
🇪🇸 Español   es
```

Ces quatre packs de base sont également embarqués avec le frontend sous forme de ressources/chunks versionnés compatibles avec son catalogue. Ils constituent un **fallback local complet** pour le bootstrap, l'écran de connexion et les écrans d'erreur si le service de locale packs est temporairement indisponible. Les langues supplémentaires restent ajoutables à chaud depuis le backend sans rebuild.

Le pack `en` constitue le fallback technique ultime et ne peut pas être désactivé sans qu'un autre fallback bootstrap complet soit explicitement désigné et validé. Cela n'impose jamais l'anglais comme préférence utilisateur.

## 40.8 Ajout de langues UI à la volée

Une nouvelle langue UI doit pouvoir être ajoutée **sans recompilation du frontend** et sans modifier le code React.

Le produit charge des `UI Locale Packs` versionnés depuis le backend.

Cycle :

```text
UPLOAD/REGISTER LOCALE PACK
       ↓
VALIDATE SCHEMA
       ↓
COMPARE WITH CURRENT UI CATALOG
       ↓
100% COVERAGE REQUIRED
       ↓
ACTIVATE
       ↓
AVAILABLE IMMEDIATELY
```

Un pack incomplet peut être enregistré comme brouillon mais **ne peut pas être activé pour les utilisateurs**.

## 40.9 Zéro fallback visible pour une langue active

Pour respecter l'exigence « tout est traduit », une locale active doit couvrir 100 % des clés obligatoires du catalogue courant.

Le produit ne doit pas afficher silencieusement :

- une clé brute `permissions.manage_roles.label` ;
- un texte anglais au milieu d'une interface française ;
- un message backend non localisé ;
- un tooltip manquant.

Une évolution du catalogue ne peut pas être déployée tant qu'un pack marqué `ACTIVE` n'a pas 100 % des nouvelles clés. Un opérateur peut explicitement désactiver une locale avant le déploiement, mais le système ne doit jamais conserver une locale active partiellement traduite.

## 40.10 Erreurs backend localisables

Le backend ne doit pas obliger le frontend à afficher une phrase française/anglaise figée.

Il renvoie :

```json
{
  "code": "DISCORD_ROLE_HIERARCHY",
  "message_key": "errors.discord.roleHierarchy",
  "params": {
    "roleName": "Officier"
  }
}
```

Le frontend traduit `message_key` dans le `UI Locale` courant.

Le détail technique brut peut être disponible dans un panneau expert/audit sans devenir le message UX principal.

## 40.11 Préférence de langue UI

La langue du dashboard est une préférence utilisateur globale indépendante :

```text
UI Locale
!=
Language Profile de contenu Discord
!=
langues visibles du membre dans une Guild
```

### Résolution par défaut

Par défaut, **DID suit la langue du navigateur**. Le mode visible dans les préférences est :

> **Automatique (langue du navigateur)**

Ordre de résolution :

```text
1. override explicite utilisateur, s'il existe
2. navigator.languages / langue préférée du navigateur
3. correspondance exacte BCP 47 active       fr-FR -> fr-FR si disponible
4. correspondance langue de base active      fr-FR -> fr
5. fallback bootstrap -> en
```

Le fallback `en` sert uniquement lorsqu'aucune locale active ne correspond au navigateur ; il ne permet jamais à une locale active partiellement traduite d'afficher des chaînes anglaises manquantes.

Avant même l'authentification OAuth2, l'écran de connexion applique la préférence navigateur. Le backend peut utiliser `Accept-Language` pour le bootstrap serveur ; le runtime navigateur utilise `navigator.languages`.

Après authentification :

- tant qu'aucun override n'est enregistré, DID continue à suivre le navigateur ;
- si l'utilisateur choisit explicitement `Français`, `English`, `Deutsch`, `Español` ou une autre locale active, cet override est persisté ;
- l'utilisateur peut revenir à **Automatique (langue du navigateur)**, ce qui supprime l'override ;
- si la locale explicitement choisie devient `DISABLED`, incompatible avec le catalogue courant ou momentanément indisponible, DID ne tente jamais d'afficher un pack incomplet : il applique temporairement la résolution navigateur puis le fallback bootstrap. La préférence explicite peut rester mémorisée comme `UNAVAILABLE_OVERRIDE` afin d'être automatiquement réutilisée si la locale redevient compatible ;
- en mode automatique, un changement de préférence navigateur est repris au prochain chargement et peut être appliqué immédiatement si l'environnement émet un événement `languagechange`.

La valeur `locale` éventuellement retournée dans le profil Discord OAuth2 n'est **pas** utilisée comme langue par défaut du dashboard : la règle produit demandée est le navigateur.

Un utilisateur peut par exemple :

- afficher DID en français ;
- administrer des salons anglais/allemands ;
- n'avoir aucun rôle de langue française dans une Guild.

La suppression d'une langue de contenu Discord n'a donc aucun impact sur la langue du dashboard.

## 40.12 Formatage localisé

Le `UI Locale` pilote également :

- dates ;
- heures ;
- nombres ;
- pluriels ;
- durées ;
- temps relatifs ;
- séparateurs ;
- ordre de lecture lorsque des locales RTL seront ajoutées.

Les timestamps Discord intégrés dans le contenu des messages restent des tokens Discord et ne sont pas réécrits par ce mécanisme.

## 40.13 Fonts, drapeaux et emojis

La charte frontend doit prévoir une pile de fontes Unicode complète et une stratégie emoji explicite.

Exemple de pile :

```css
font-family:
  Inter,
  ui-sans-serif,
  system-ui,
  "Segoe UI",
  "Segoe UI Emoji",
  "Noto Color Emoji",
  "Apple Color Emoji",
  sans-serif;
```

Exigences :

- aucun carré/tofu pour les caractères supportés par la locale ;
- emojis couleur lorsque le navigateur/OS le permet ;
- drapeaux visibles dans les sélecteurs de langues ;
- rendu cohérent sur Windows 11, macOS, Linux et navigateurs modernes.

Pour les drapeaux de sélection de langue, le produit ne doit pas dépendre uniquement du rendu d'une fonte emoji, qui peut varier selon l'OS. Il utilise un composant d'icône/flag normalisé avec fallback emoji.

Les emojis insérés dans les textes UI peuvent être rendus via une stratégie cohérente de type Twemoji/emoji renderer lorsqu'un rendu natif n'est pas suffisant.

## 40.14 Sécurité des packs UI et textes riches

Les packs de locale chargés à chaud sont des données de présentation, **jamais du HTML de confiance**.

Règles :

- aucun `dangerouslySetInnerHTML` alimenté par un pack de locale ;
- les textes riches utilisent des composants/tokens explicitement autorisés (`strong`, lien applicatif sûr, code inline, etc.) ;
- les URLs éventuelles sont validées par une allowlist de schémas/destinations ;
- les interpolations sont échappées ;
- un pack contenant une construction interdite est refusé avant activation ;
- le rôle permettant d'enregistrer/activer un locale pack est une capability d'administration explicite et auditée.

## 40.15 Tests d'exhaustivité i18n

La CI doit échouer si :

- une nouvelle clé est absente d'un pack UI obligatoire ;
- une chaîne UI interdite est hardcodée dans un composant ;
- une clé n'existe pas dans le catalogue de référence ;
- un namespace est manquant ;
- une interpolation requise est absente ;
- un test de rendu détecte une clé brute visible.

Les tests E2E critiques sont exécutés au minimum en EN, FR, DE et ES.

---

# 41. Exigences multi-tenant

## 41.1 Tenant obligatoire

Toute donnée métier appartenant à un serveur doit avoir un `guild_id`.

## 41.2 API

Toute route tenant-scopée doit recevoir le tenant dans le chemin ou le contexte de session.

Exemple :

```text
/api/v1/guilds/{guild_id}/channels
```

## 41.3 Vérification d'autorisation

Le `guild_id` fourni par le client n'est jamais considéré comme autorisé en soi.

Le backend doit prouver :

1. utilisateur authentifié ;
2. utilisateur autorisé sur ce `guild_id` ;
3. action autorisée ;
4. cible appartenant à ce même `guild_id`.

## 41.4 Protection IDOR

Aucune ressource ne doit être récupérable par son UUID sans vérification du tenant.

## 41.5 Tâches asynchrones

Tout **job tenant-scopé** contient obligatoirement un `guild_id`.

Une orchestration appartenant au **User Control Plane** peut être multi-Guild et ne possède donc pas nécessairement un `guild_id` unique. Dans ce cas :

- elle ne réalise aucune mutation Discord directement ;
- elle contient explicitement `actor_user_id` et son identifiant de campagne/transfert/orchestration ;
- elle résout les tenants autorisés ;
- elle fan-out en jobs enfants strictement tenant-scopés ;
- chaque job enfant qui lit/mute Discord contient son `guild_id` et repasse l'autorisation du tenant concerné.

Exemple campagne :

```text
CAMPAIGN_OCCURRENCE(user-scoped)
    ├── DELIVERY guild=A
    ├── DELIVERY guild=B
    └── DELIVERY guild=C
```

---

# 42. Exigences de sécurité

## 42.1 Bot token

Jamais côté navigateur.

## 42.2 OAuth tokens

Stockage sécurisé, chiffrement au repos si persistés.

## 42.3 CSRF OAuth

Utiliser `state`.

## 42.4 Cookies

Session sécurisée, `HttpOnly`, `Secure` en production, stratégie SameSite adaptée.

## 42.5 Audit

Les mutations sensibles doivent être auditables.

## 42.6 Secrets

Jamais dans Git.

---

# 43. Données personnelles

Minimisation :

- Discord ID ;
- username/display metadata utile ;
- rôles nécessaires ;
- pas de collecte de contenu de messages par défaut ;
- pas de présence utilisateur si inutile ;
- pas d'email si `identify` suffit.

Prévoir :

- politique de rétention ;
- suppression d'un tenant ;
- purge après désinstallation ;
- export administratif selon les droits et politiques de rétention.

---

# 44. Performance et cache local

## 44.1 Cache persistant obligatoire

Le cache de structure n'est pas une optimisation facultative : c'est un composant central du produit.

PostgreSQL conserve le **dernier état connu** de :

- Guild ;
- catégories/salons ;
- rôles ;
- overwrites ;
- threads utiles à la fonction ;
- état d'accès/obfuscation ;
- membres/rôles de membres uniquement selon les fonctions et intents activés.

Redis peut conserver un cache chaud dérivé et des verrous/single-flight ; PostgreSQL reste la copie locale durable.

## 44.2 Source de vérité et observabilité

Discord reste source de vérité externe pour les ressources Discord, **mais DID peut ne plus être autorisé à observer toutes leurs métadonnées**.

La base locale doit donc distinguer :

```text
LAST_KNOWN_STATE    dernière métadonnée complète observée
OBSERVED_STATE      état actuellement observable
ACCESS_STATE        VISIBLE | OBFUSCATED | ACCESS_LOST | UNKNOWN | DELETED_CONFIRMED
FRESHNESS           FRESH | AGING | STALE
```

Les anciennes métadonnées d'un salon devenu invisible peuvent être conservées pour audit/diagnostic, mais l'UI doit les afficher comme **« dernière valeur connue »**, jamais comme vérité actuelle garantie.

## 44.3 Mise à jour du cache

Ordre privilégié :

```text
1. Gateway incremental events
2. write-through depuis les réponses aux mutations DID
3. REST ciblé sur cache miss/stale critique
4. reconciliation REST de fond
```

Un chargement de page n'est pas une raison suffisante pour appeler Discord si le cache est exploitable.

Pour les lectures non critiques, DID doit privilégier un comportement **stale-while-revalidate** : retourner immédiatement l'état local exploitable avec son indicateur de fraîcheur, puis programmer éventuellement un refresh en arrière-plan si la policy le juge nécessaire.

Pour une décision de sécurité ou un APPLY dépendant d'un état potentiellement périmé, la policy peut au contraire imposer un refresh ciblé avant de poursuivre.

## 44.4 Métadonnées de fraîcheur

Chaque ressource cache importante conserve lorsque pertinent :

```text
last_full_observed_at
last_gateway_seen_at
last_rest_seen_at
last_mutation_confirmed_at
access_lost_at
obfuscated_at
cache_updated_at
state_version
```

## 44.5 Cache négatif prudent

Un `404`, une omission HTTP ou une absence de résultat n'est mis en cache comme suppression que si le contexte permet réellement de conclure `DELETED_CONFIRMED`.

Après Channel Obfuscation, `GET Guild Channels` peut omettre un salon simplement parce que le bot ne possède plus `VIEW_CHANNEL`.

## 44.6 Frontend

L'API expose l'âge et la qualité de l'information lorsque cela affecte la décision :

```text
Données à jour il y a 12 s
Dernier état complet connu il y a 3 h
⚠ Le bot ne voit actuellement plus ce salon
```

## 44.7 Vue normale et vue des éléments masqués / supprimés

La vue Structure normale doit privilégier la lisibilité : les ressources `OBFUSCATED`, `ACCESS_LOST`, `DELETED_CONFIRMED` et les tombstones de purge ne sont **pas affichées par défaut** dans l'arborescence principale.

Le menu contextuel de la racine de Guild, de l'explorateur ou le menu « Affichage » doit proposer une action explicite et compréhensible :

> **Afficher les salons et catégories masqués ou supprimés**

Lorsque cette option est activée, les éléments non pleinement observables apparaissent avec un rendu différencié :

```text
📁 Direction            ⚠ Accès perdu — dernier état connu
# secret                👁 Masqué au bot
# ancien-salon          🗑 Suppression confirmée
```

L'utilisateur peut revenir à tout moment à :

> **Masquer les salons et catégories masqués ou supprimés**

Ce choix d'affichage est une préférence UI utilisateur ; il ne modifie ni Discord ni le cache.

## 44.8 Purge manuelle du cache

Un utilisateur disposant de la capability appropriée peut nettoyer les ressources historiques qu'il sait réellement supprimées.

Actions contextuelles :

```text
Marquer comme supprimé et purger du cache...
Purger les éléments supprimés confirmés...
```

La purge doit être disponible :

- individuellement ;
- sur multi-sélection ;
- en bulk par état / ancienneté / catégorie logique lorsque le filtre le permet.

La purge :

- **ne supprime jamais une ressource dans Discord** ;
- supprime les métadonnées locales détaillées devenues inutiles ;
- supprime les derniers overwrites détaillés associés lorsque la politique de rétention le permet ;
- conserve un **tombstone minimal auditable** afin d'éviter une résurrection locale ambiguë ;
- trace l'utilisateur, la date et la raison de la purge.

Lorsqu'un utilisateur confirme manuellement qu'une ressource obfusquée est réellement supprimée, DID peut passer par :

```text
OBFUSCATED / ACCESS_LOST
        ↓ user confirmation
USER_CONFIRMED_DELETED
        ↓ purge detailed cache
PURGED_TOMBSTONE
```

Si Discord émet ultérieurement un événement non ambigu prouvant que le même `channel_id` existe encore, DID invalide automatiquement le tombstone, recrée l'entrée cache minimale/complète selon l'observation et produit un événement d'audit `PURGED_RESOURCE_REOBSERVED`.

---

# 45. Réconciliation

## 45.1 Sync initiale

À l'installation, importer tout ce que DID est autorisé à observer et enregistrer le niveau de couverture atteint.

## 45.2 Sync événementielle

Les événements Gateway mettent à jour le cache local sans effectuer systématiquement un GET de confirmation.

Les événements provenant de nos propres mutations sont dédupliqués avec le write-through local.

## 45.3 Reconcile périodique adaptatif

Un scheduler déclenche des vérifications périodiques avec :

- jitter ;
- priorité ;
- backpressure rate-limit ;
- déduplication ;
- fréquence adaptative ;
- possibilité de reconcile manuel.

## 45.4 Perte de visibilité

Exemple :

```text
10:00 #direction visible
      name = direction
      overwrites complets

10:05 rôle du bot modifié

10:05 CHANNEL_UPDATE obfusqué
      id connu
      type connu
      position connue
      parent_id connu
      name actuel non fiable

Cache DID :
  access_state = ACCESS_LOST / OBFUSCATED
  last_known_name = direction
  last_full_observed_at = 10:00
```

Le salon reste représentable dans la vue d'administration comme **ressource connue mais non observable**, avec un diagnostic permettant à l'admin de rétablir la visibilité si nécessaire.

## 45.5 Reprise de visibilité

Lorsqu'un `CHANNEL_UPDATE` complet arrive après récupération de `VIEW_CHANNEL` :

- remplacer l'état observé ;
- conserver la trace d'audit de la période d'obfuscation ;
- remettre `access_state = VISIBLE` ;
- invalider/recalculer les analyses de permissions dépendantes.

## 45.6 Suppression vs invisibilité

Une suppression n'est confirmée automatiquement que par une preuve suffisante, notamment un événement `CHANNEL_DELETE` applicable ou une autre observation non ambiguë.

Une simple omission dans un `GET /guilds/{guild.id}/channels` ne constitue plus une preuve de suppression.

## 45.7 Confirmation utilisateur, purge et réobservation

DID doit accepter que l'utilisateur possède une connaissance opérationnelle que l'API Discord ne permet plus de confirmer directement. Un utilisateur autorisé peut donc sélectionner un salon ou une catégorie `OBFUSCATED`, `ACCESS_LOST` ou `DELETED_CONFIRMED` et choisir :

> **Marquer comme supprimé et purger du cache...**

Avant confirmation, l'UI affiche :

- le dernier nom connu ;
- le `channel_id` Discord ;
- le type (catégorie/salon/thread lorsque pertinent) ;
- le dernier parent connu ;
- la date de dernière observation complète ;
- l'état d'accès actuel ;
- le fait que cette opération **ne supprime rien dans Discord**.

La même action est disponible en multi-sélection et en bulk depuis la vue « salons et catégories masqués ou supprimés ».

Après purge, DID conserve uniquement un tombstone minimal auditable. Si Discord émet plus tard une observation non ambiguë du même `channel_id`, l'observation Discord prévaut : le tombstone est invalidé et la ressource est reconstruite dans le cache.

## 45.8 Couverture DID

Le dashboard affiche un indicateur de couverture :

```text
Structure observable     97 %
Salons complets          194
Salons obfusqués           6
Permissions auditables   PARTIELLES
Dernier reconcile        il y a 8 min
```

Un audit incomplet doit être explicitement étiqueté comme tel.

---

# 46. Exigences non fonctionnelles

- code typé ;
- API versionnée ;
- migration DB versionnée ;
- idempotence des jobs ;
- logs structurés ;
- correlation IDs ;
- métriques ;
- tests unitaires ;
- tests d'intégration ;
- environnement de test Discord dédié ;
- aucune dépendance directe du frontend au bot token ;
- séparation claire lecture / plan / mutation.

---

# 47. Écrans cibles

## 47.1 Connexion

Discord OAuth.

## 47.2 Sélection serveur

Liste des serveurs pertinents.

## 47.3 Setup

Assistant initial.

## 47.4 Dashboard

```text
┌─────────────────────────────────────────────────────────────────┐
│ Hero Wars France        🔍 Search     🔔 3      👤 Olivier       │
├───────────────┬─────────────────────────────────┬───────────────┤
│ STRUCTURE     │                                 │ PROPRIÉTÉS    │
│               │       VUE PRINCIPALE            │               │
│ 📁 Info       │                                 │ #annonces     │
│ 📁 Alpha      │                                 │ visibilité    │
│ 📁 Staff      │                                 │ écriture      │
│               │                                 │ bots          │
├───────────────┴─────────────────────────────────┴───────────────┤
│ Plan : 3 changements en attente                     [Examiner]  │
└─────────────────────────────────────────────────────────────────┘
```

## 47.5 Permissions

Matrice + explication.

## 47.6 Membres

Liste et rôles.

## 47.7 Bots

Audit des bots.

## 47.8 Plans

Plan, impact, apply.

## 47.9 Audit

Timeline.

## 47.10 Traductions

Vue des Language Profiles, Translation Groups, variantes, routes, dérives, scopes et état du Translation Provider.

---

# 48. Périmètre fonctionnel complet

Le document décrit **une seule cible produit complète**. Les blocs ci-dessous font tous partie du périmètre à implémenter ; leur ordre éventuel de construction est une contrainte de dépendances techniques, pas un découpage en versions produit.

## 48.1 Socle plateforme et Discord

- installation multi-serveurs ;
- OAuth dashboard ;
- isolation multi-tenant + User Control Plane ;
- cache local persistant ;
- Gateway incremental cache ;
- Channel Obfuscation ;
- Discord REST Governor / I/O Worker ;
- import et réconciliation de structure ;
- rôles, salons, catégories, threads supportés ;
- audit interne ;
- diagnostic des permissions/capacités du bot.

## 48.2 Administration et mutations

- plans de modification ;
- Desired State Graph ;
- DAG et références symboliques ;
- preflight / impact / confirmation / apply / verify ;
- résilience `UNKNOWN_OUTCOME` ;
- duplication et clonage profond ;
- copier/coller et Drag & Drop intra/inter-Guild ;
- menus contextuels et Right Drag ;
- templates et bibliothèque personnelle ;
- snapshots, drift et réconciliation.

## 48.3 Permissions, scopes et délégation

- Permission Evaluator ;
- Permission Intent Compiler ;
- mode simple et expert ;
- « Voir comme » ;
- « Pourquoi a-t-il accès ? » ;
- matrice et analyse d'impact ;
- groupes logiques ;
- Scope Membership Resolver ;
- RBAC dashboard granulaire ;
- délégation par utilisateur/rôle/scope.

## 48.4 Multilingue et traduction

- Language Profiles ;
- langues visibles d'un membre, sans langue principale obligatoire ;
- métadonnée langue catégorie/salon ;
- Translation Groups / Translation Channel Groups ;
- topologies `HUB_AND_SPOKE`, `FULL_MESH` lorsque supporté, et `CUSTOM` ;
- Visibility Scope × Language ;
- clonage multilingue ;
- liaison manuelle et par Drag & Drop ;
- drift/synchronisation de topologie ;
- adapter non invasif du bot de traduction existant ;
- `MANUAL_CONFIGURATION_REQUIRED` lorsqu'aucune interface existante sûre ne permet une configuration automatique.

## 48.5 Dashboard internationalisé

- UI Locale distinct des Language Profiles ;
- EN/FR/DE/ES complets par défaut ;
- ajout de locales à chaud sans rebuild ;
- couverture 100 % obligatoire pour une locale active ;
- menus/toasts/tooltips/context menus/ARIA/erreurs entièrement localisés ;
- dates/nombres/pluriels localisés ;
- fonts Unicode + emoji + drapeaux normalisés ;
- contrôle CI anti-chaînes hardcodées.

## 48.6 Communication et automatisations

- Message & Campaign Center ;
- ciblage multi-Guild/multi-salon/groupe logique/langue/Translation Group ;
- message simple ou embeds ;
- envoi immédiat, programmé, récurrent ou événementiel ;
- conditions AND/OR/NOT ;
- simulation avant publication ;
- idempotence et historique des deliveries ;
- `allowed_mentions` explicite ;
- traduction DID via `googletrans` pour les campagnes demandées ;
- parser Discord-safe et validation fail-closed ;
- glossaires et termes protégés ;
- variantes approuvées pour les campagnes récurrentes ;
- intégration des salons multilingues sans imposer de modification du bot de traduction existant.

## 48.7 Fonctions complémentaires

- onboarding ;
- webhooks ;
- recherche universelle ;
- gestion des bots ;
- gestion des membres ;
- multi-serveur organisationnel explicitement opt-in ;
- suivi message-à-message uniquement si le Translation Provider le permet sans imposer de modification du bot existant.

---

# 49. Critères d'acceptation globaux

## 49.1 Isolation

Avec deux guildes de test A et B :

- un admin A ne peut consulter aucune ressource B ;
- modifier l'URL avec le `guild_id` de B renvoie 403/404 selon stratégie ;
- aucun événement websocket de B n'est envoyé à une session A.

## 49.2 Installation

Un owner/admin peut initialiser le tenant.

Un membre non autorisé ne peut pas terminer le setup.

## 49.3 Structure

L'arborescence affichée correspond à Discord.

## 49.4 Mutation

Déplacer un salon :

- génère un plan ;
- valide ;
- applique ;
- confirme l'état final.

## 49.5 Permissions

Le moteur reproduit les permissions effectives Discord pour les scénarios testés.

## 49.6 Duplication

Une catégorie de test est dupliquée avec :

- salons ;
- paramètres ;
- mapping rôles ;
- overwrites.

## 49.7 Cache / observabilité / rate limits

Le produit est conforme sur ce volet si :

- ouvrir et naviguer dans le dashboard ne provoque pas une rafale de GET Discord ;
- un `CHANNEL_UPDATE` met à jour le cache sans GET systématique ;
- un salon auparavant visible puis obfusqué conserve son dernier état connu avec `ACCESS_LOST/OBFUSCATED` ;
- la vue normale masque par défaut les ressources masquées/supprimées et l'utilisateur peut les afficher explicitement ;
- un utilisateur autorisé peut marquer une ressource comme supprimée puis la purger individuellement ou en bulk ;
- une purge conserve un tombstone minimal et ne déclenche aucune suppression Discord ;
- une réobservation Discord invalide un tombstone erroné ;
- une omission HTTP n'est pas interprétée comme suppression ;
- un refresh concurrent identique est coalescé ;
- un plan massif respecte la queue et les réponses rate-limit Discord ;
- les `429` et invalid requests sont mesurés ;
- un `CREATE` en `UNKNOWN_OUTCOME` n'est pas retry aveuglément.

## 49.8 Audit

Chaque mutation possède un initiateur et un résultat.

## 49.9 Multilingue

Avec deux Translation Groups indépendants utilisant tous deux FR/EN :

- un message/topology event de `TG-A` ne cible jamais `TG-B` ;
- l'ajout de DE à `TG-A` ne modifie pas `TG-B` ;
- une catégorie FR clonée en EN/DE reçoit de nouveaux IDs Discord et des bindings explicites ;
- un utilisateur Alpha+FR ne voit pas automatiquement le contenu Beta+FR ;
- un utilisateur Alpha+FR+EN obtient les bindings techniques Alpha/FR et Alpha/EN nécessaires ;
- aucun utilisateur n'a besoin d'une langue principale ; retirer/désactiver une langue ne change pas implicitement ses autres langues visibles ;
- le preflight refuse une création de rôles dépassant la capacité Discord ;
- le provider peut échouer sans provoquer une suppression automatique des catégories/salons déjà créés.

## 49.10 Dashboard i18n

Le produit est conforme si :

- EN/FR/DE/ES couvrent 100 % des clés obligatoires ;
- changer de locale traduit immédiatement menus, context menus, toasts, tooltips, dialogues et erreurs ;
- aucune clé brute n'est visible ;
- une locale incomplète est impossible à activer ;
- une nouvelle locale valide peut être ajoutée sans rebuild du frontend ;
- les noms/ressources Discord utilisateur ne sont pas confondus avec les chaînes UI ;
- drapeaux et emojis restent visibles sous Windows 11 dans les écrans de test.

## 49.11 Campaign Engine

Le produit est conforme si :

- une campagne peut cibler plusieurs Guilds/salons autorisés ;
- un target non autorisé échoue sans dupliquer les targets déjà livrés ;
- une occurrence récurrente n'est pas envoyée deux fois sur retry ;
- plain text et embeds sont supportés ;
- un salon appartenant à un Translation Channel Group propose les modes de fan-out attendus ;
- une URL, mention, commande Discord, emoji custom, timestamp, code block ou variable protégée ressort strictement identique après traduction ;
- une corruption simulée de token bloque la publication ;
- un glossaire `DO_NOT_TRANSLATE/FORCE_TRANSLATION` est respecté ;
- une variante récurrente approuvée peut être réutilisée sans retraduction ;
- les pings sont contrôlés indépendamment du texte via `allowed_mentions` ;
- une simulation permet de voir le nombre de deliveries et erreurs avant publication.

---

# 50. Hors périmètre produit

- stockage général de l'historique des messages Discord ;
- clonage des messages d'un salon ;
- restauration d'identifiants Discord supprimés ;
- faux sous-niveaux de catégories ;
- faux rôles hiérarchiques imbriqués ;
- contournement de la hiérarchie Discord ;
- contournement des permissions Discord ;
- IA obligatoire pour gérer le serveur ;
- self-bot ;
- utilisation d'un token utilisateur Discord en dehors d'OAuth2 officiel.

---

# 51. Références Discord officielles

Références à revalider avant chaque version majeure :

- Application / installation context : https://docs.discord.com/developers/resources/application
- OAuth2 : https://docs.discord.com/developers/topics/oauth2
- OAuth2 et permissions : https://docs.discord.com/developers/platform/oauth2-and-permissions
- User / Current User Guilds : https://docs.discord.com/developers/resources/user
- Guild : https://docs.discord.com/developers/resources/guild
- Channels : https://docs.discord.com/developers/resources/channel
- Permissions : https://docs.discord.com/developers/topics/permissions
- Gateway : https://docs.discord.com/developers/events/gateway
- Gateway events : https://docs.discord.com/developers/events/gateway-events
- Audit log : https://docs.discord.com/developers/resources/audit-log
- Application commands : https://docs.discord.com/developers/interactions/application-commands
- Rate limits : https://docs.discord.com/developers/topics/rate-limits
- Message resource / allowed mentions / create message : https://docs.discord.com/developers/resources/message
- Message formatting / mentions / emojis / timestamps : https://docs.discord.com/developers/reference#message-formatting
- Privileged intents review : https://docs.discord.com/developers/gateway/getting-started-with-privileged-intent-review
- Channel Obfuscation / change log : https://docs.discord.com/developers/change-log
- Opcodes / status codes / limites : https://docs.discord.com/developers/topics/opcodes-and-status-codes
- Limites serveur complémentaires : https://support.discord.com/hc/en-us/articles/33694251638295-Discord-Account-Caps-Server-Caps-and-More

Internationalisation / traduction :

- i18next : https://www.i18next.com/
- react-i18next : https://react.i18next.com/
- googletrans : https://pypi.org/project/googletrans/

Note : `googletrans` est une librairie non officielle utilisant l'interface Web de Google Translate. DID l'encapsule et ne considère jamais sa sortie comme suffisamment sûre pour être publiée sans validation technique Discord-safe.

---

# 52. Règle de développement pour Codex

Toute nouvelle fonctionnalité proposée ou implémentée doit répondre aux questions suivantes :

1. Quel objet Discord réel est concerné ?
2. Quel endpoint REST, événement Gateway ou mécanisme Discord permet l'action ?
3. Quelle permission bot est requise ?
4. Quel intent est requis ?
5. La fonction nécessite-t-elle un intent privilégié ?
6. Quelles sont les contraintes de hiérarchie ?
7. Est-elle multi-tenant safe ?
8. Peut-elle être prévisualisée ?
9. Est-elle réversible ?
10. Que se passe-t-il si Discord refuse l'appel ?
11. Comment est-elle auditée ?
12. Comment est-elle testée ?
13. Si elle concerne une langue, est-ce une simple métadonnée, une audience, une liaison de traduction ou les trois ?
14. Si elle concerne plusieurs variantes linguistiques, quel `translation_group_id` les relie explicitement ?
15. Le plan réutilise-t-il les rôles `Visibility Scope × Language` existants avant d'en créer ?
16. L'adapter connaît-il et valide-t-il réellement les capacités du Translation Provider pour la topologie demandée ?

Si aucune primitive Discord ne permet la fonction, elle doit être soit :

- identifiée comme abstraction pure du dashboard ;
- reformulée ;
- ou rejetée.

Aucune fonctionnalité impossible ne doit être simulée comme si Discord la supportait.
---

# 53. Registre normatif des exigences

Les mots **MUST**, **SHOULD** et **MAY** sont utilisés au sens suivant :

- **MUST** : obligatoire pour considérer la fonctionnalité conforme ;
- **SHOULD** : attendu sauf justification technique documentée ;
- **MAY** : optionnel.

Ce registre sert de référence de traçabilité pour les tickets, branches, commits, tests et prompts Codex.

## 53.1 Installation et identité

- **REQ-INST-001 — MUST** : une seule application Discord doit pouvoir être installée sur plusieurs Guild Discord indépendantes.
- **REQ-INST-002 — MUST** : chaque installation doit être représentée par un enregistrement distinct indexé par `guild_id`.
- **REQ-INST-003 — MUST** : la plateforme doit distinguer l'autorisation Discord d'installer l'application de l'autorisation interne d'initialiser le tenant.
- **REQ-INST-004 — MUST** : le bootstrap initial d'une Guild est réservé au propriétaire ou à un membre ayant `ADMINISTRATOR`; après bootstrap, les délégations configurées par le tenant peuvent autoriser d'autres principals du dashboard.
- **REQ-INST-005 — SHOULD** : une installation non initialisée doit rester dans l'état `PENDING_SETUP`.
- **REQ-INST-006 — MUST** : une désinstallation doit invalider les capacités de mutation de la Guild.
- **REQ-INST-007 — MUST** : la suppression/réinstallation du bot ne doit jamais relier automatiquement une Guild à une autre Guild.

## 53.2 Multi-tenancy

- **REQ-TEN-001 — MUST** : `guild_id` doit être présent dans toute donnée métier tenant-scopée.
- **REQ-TEN-002 — MUST** : toute lecture tenant-scopée doit vérifier l'autorisation de l'utilisateur sur le tenant.
- **REQ-TEN-003 — MUST** : toute mutation tenant-scopée doit vérifier utilisateur, tenant, capability interne et appartenance de la cible.
- **REQ-TEN-004 — MUST** : un identifiant de ressource d'une autre Guild ne doit jamais permettre de contourner l'isolation.
- **REQ-TEN-005 — MUST** : aucun WebSocket d'une Guild A ne reçoit d'événement de Guild B.
- **REQ-TEN-006 — MUST** : chaque tâche asynchrone tenant-scopée contient explicitement le `guild_id`; une orchestration User Control Plane multi-Guild ne mute jamais Discord directement et fan-out en jobs enfants tenant-scopés.
- **REQ-TEN-007 — MUST** : les caches et locks Redis tenant-scopés incluent le `guild_id`.
- **REQ-TEN-008 — MUST** : les templates privés sont isolés par tenant.
- **REQ-TEN-009 — MUST** : les audits internes sont isolés par tenant.
- **REQ-TEN-010 — SHOULD** : PostgreSQL RLS doit être utilisé comme défense en profondeur.
- **REQ-TEN-011 — MUST** : toute fonction liant plusieurs Guilds nécessite une association explicite et volontaire ; aucune découverte ou fédération automatique n'est autorisée.
- **REQ-TEN-012 — MUST** : une copie/clonage inter-Guild exige une autorisation de lecture/export sur la source ET une autorisation d'import/mutation sur la destination.
- **REQ-TEN-013 — MUST** : un transfert inter-Guild utilise un snapshot portable ; la Guild destination ne reçoit jamais une capacité de lecture permanente sur la source.
- **REQ-TEN-014 — MUST** : un clipboard inter-Guild est user-scopé, chiffré/isolé côté serveur et ne doit jamais être exposé à un autre utilisateur.

## 53.3 Structure Discord

- **REQ-STR-001 — MUST** : l'arborescence doit représenter fidèlement les catégories, salons et threads Discord.
- **REQ-STR-002 — MUST** : le produit ne doit jamais créer ou présenter une sous-catégorie Discord inexistante.
- **REQ-STR-003 — MUST** : les groupes logiques doivent être visuellement identifiables comme abstraction dashboard.
- **REQ-STR-004 — MUST** : un déplacement de salon doit respecter les règles `parent_id` de Discord.
- **REQ-STR-005 — MUST** : la suppression d'une catégorie doit tenir compte du comportement réel Discord vis-à-vis des salons enfants.
- **REQ-STR-006 — SHOULD** : toute action d'arborescence complexe doit être disponible depuis un menu contextuel.
- **REQ-STR-007 — SHOULD** : le drag & drop doit produire un changement proposé, pas une mutation cachée immédiate.
- **REQ-STR-008 — MUST** : un drag inter-Guild ne doit jamais supprimer implicitement la source ; son comportement par défaut est la copie/clonage.
- **REQ-STR-009 — MUST** : le drag avec bouton droit doit ouvrir au relâchement un menu contextuel de drop contenant uniquement les actions valides.
- **REQ-STR-010 — MUST** : toute action drag & drop doit disposer d'une alternative accessible via menu/dialogue/commande.
- **REQ-STR-011 — MUST** : un drag gauche inter-Guild ne doit jamais déplacer/supprimer la ressource source ; il compile une copie ou un clonage destination.
- **REQ-STR-012 — MUST** : un clic droit sans drag ouvre le menu contextuel de l'objet ; un clic droit avec déplacement au-delà du seuil ouvre le Drop Context Menu au relâchement.
- **REQ-STR-013 — MUST** : le navigateur de ressources doit permettre une destination inter-Guild lorsque l'utilisateur est autorisé sur les deux côtés nécessaires.

## 53.4 Permissions

- **REQ-PERM-001 — MUST** : le moteur doit traiter les bitfields de permissions sans perte de précision.
- **REQ-PERM-002 — MUST** : l'effet de `ADMINISTRATOR` doit être reproduit correctement.
- **REQ-PERM-003 — MUST** : le mode simple doit compiler vers des permissions Discord réelles.
- **REQ-PERM-004 — MUST** : le mode expert doit afficher les flags et overwrites réels.
- **REQ-PERM-005 — MUST** : la fonction « Voir comme » ne doit pas inventer de permissions.
- **REQ-PERM-006 — MUST** : « Pourquoi ? » doit fournir une trace explicable de la résolution.
- **REQ-PERM-007 — MUST** : une permission impossible à limiter à cause d'`ADMINISTRATOR` doit générer un avertissement visible.
- **REQ-PERM-008 — SHOULD** : le moteur doit pouvoir comparer état actuel et état proposé pour chaque membre affecté.
- **REQ-PERM-009 — MUST** : la délégation fine du dashboard ne doit pas être présentée comme une restriction native Discord si elle ne l'est pas.

## 53.5 Plans et mutations

- **REQ-PLAN-001 — MUST** : toute mutation structurelle significative passe par un plan.
- **REQ-PLAN-002 — MUST** : un plan contient l'état avant et l'état désiré lorsque pertinent.
- **REQ-PLAN-003 — MUST** : un plan est validé avant application.
- **REQ-PLAN-004 — MUST** : les permissions du bot sont vérifiées avant application.
- **REQ-PLAN-005 — MUST** : la hiérarchie des rôles est vérifiée avant application.
- **REQ-PLAN-006 — MUST** : les limites Discord sont vérifiées avant application.
- **REQ-PLAN-007 — MUST** : un plan basé sur une structure devenue obsolète est marqué `STALE` ou équivalent avant mutation.
- **REQ-PLAN-008 — MUST** : le résultat de chaque opération du plan est persisté.
- **REQ-PLAN-009 — MUST** : un échec partiel doit être visible et diagnostiquable.
- **REQ-PLAN-010 — MUST** : aucune opération non réversible ne doit être présentée comme parfaitement rollbackable.
- **REQ-PLAN-011 — SHOULD** : l'utilisateur doit disposer d'un résumé d'impact avant une opération HIGH ou CRITICAL.
- **REQ-PLAN-012 — MUST** : les opérations destructives HIGH/CRITICAL nécessitent une confirmation renforcée.
- **REQ-PLAN-013 — MUST** : les dépendances entre opérations sont persistées explicitement ; un simple ordre numérique ne remplace pas le DAG logique.
- **REQ-PLAN-014 — MUST** : toute opération créant une ressource Discord produit/consomme des références symboliques jusqu'à résolution de l'ID destination.
- **REQ-PLAN-015 — MUST** : une opération dont l'appel Discord peut avoir réussi avant un crash local passe en état `UNKNOWN_OUTCOME` ou équivalent et n'est jamais retry aveuglément.
- **REQ-PLAN-016 — MUST** : avant de retry une création à outcome inconnu, DID tente une réconciliation déterministe et demande une intervention si l'identité de la ressource créée ne peut pas être prouvée sans ambiguïté.

## 53.6 Duplication et templates

- **REQ-DUP-001 — MUST** : la duplication de catégorie doit recréer les objets via les primitives Discord supportées.
- **REQ-DUP-002 — MUST** : la duplication de messages historiques n'est pas incluse dans une duplication structurelle.
- **REQ-DUP-003 — MUST** : la duplication de groupe logique doit résoudre un mapping de rôles.
- **REQ-DUP-004 — MUST** : un rôle source ne doit pas être réutilisé silencieusement comme rôle destination si le template exige un nouveau rôle.
- **REQ-DUP-005 — SHOULD** : les templates utilisent des références symboliques plutôt que des IDs Discord portables.
- **REQ-DUP-006 — MUST** : un template invalide vis-à-vis des capacités Discord ne peut pas être appliqué.
- **REQ-DUP-007 — MUST** : le clonage profond construit et valide un graphe de dépendances avant mutation.
- **REQ-DUP-008 — MUST** : les références Discord source sont converties en références symboliques ou mappings explicites pour la destination.
- **REQ-DUP-009 — MUST** : un mapping ambigu de rôle/bot/webhook ne peut jamais être accepté silencieusement.
- **REQ-DUP-010 — SHOULD** : le produit propose un profil `MAXIMUM_COMPATIBLE` avec rapport explicite des éléments clonés, remappés, ignorés et impossibles.
- **REQ-DUP-011 — MUST** : le clonage inter-Guild vérifie les ACL utilisateur et les capacités du bot sur les deux côtés nécessaires à l'opération.
- **REQ-DUP-012 — MUST** : un clonage présenté comme complet ne doit jamais prétendre recréer les membres, messages historiques, audit logs ou IDs Discord originaux.
- **REQ-DUP-013 — MUST** : copier/coller, drag inter-Guild, menu contextuel « Cloner vers » et import de bibliothèque utilisent le même pipeline Portable Snapshot → Dependency Graph → Mapping → Destination Plan.
- **REQ-DUP-014 — MUST** : un plan de clonage cross-Guild mute uniquement la Guild destination ; la lecture de la source est terminée avant compilation finale du plan destination.
- **REQ-DUP-015 — MUST** : le moteur expose les modes `MERGE`, `COPY_AS_NEW`, `RECONCILE` et `MAXIMUM_COMPATIBLE` lorsque le type de clone les supporte.
- **REQ-DUP-016 — MUST** : tout élément non clonable, partiellement clonable ou nécessitant un remapping est listé explicitement avant APPLY.
- **REQ-DUP-017 — MUST** : aucune suppression de destination issue d'un mode de réconciliation ne peut être silencieuse.
- **REQ-DUP-018 — MUST** : un `LIVE_CLONE` A→B exige une source A observable par DID au moment de l'export ; un import depuis un artifact déjà portable ne dépend plus de l'installation source.
- **REQ-DUP-019 — MUST** : les définitions de politiques dashboard peuvent être portables, mais aucun binding utilisateur/rôle source n'est appliqué à la destination sans mapping et confirmation explicites.

## 53.7 Bots et sécurité

- **REQ-BOT-001 — MUST** : le token bot n'est jamais envoyé au frontend.
- **REQ-BOT-002 — MUST** : le bot ne demande pas `ADMINISTRATOR` par défaut.
- **REQ-BOT-003 — MUST** : les permissions manquantes doivent être diagnostiquées précisément.
- **REQ-BOT-004 — MUST** : les bots possédant `ADMINISTRATOR` sont signalés dans l'audit de sécurité.
- **REQ-BOT-005 — SHOULD** : le dashboard doit indiquer où chaque bot peut lire et écrire.
- **REQ-BOT-006 — MUST** : une configuration « bot écrit / humains lisent » doit être basée sur de vrais overwrites Discord.
- **REQ-BOT-007 — MUST** : aucun self-bot ou token utilisateur non OAuth2 n'est autorisé dans cette architecture.

## 53.8 OAuth et sessions

- **REQ-AUTH-001 — MUST** : le dashboard utilise le Discord OAuth2 Authorization Code Grant officiel.
- **REQ-AUTH-002 — MUST** : le flow OAuth protège le callback via un `state` cryptographiquement aléatoire, usage unique et expirant.
- **REQ-AUTH-003 — MUST** : l'échange du code et tout refresh sont réalisés côté backend ; `client_secret`, access token et refresh token ne sont jamais exposés au JavaScript du navigateur.
- **REQ-AUTH-004 — MUST** : les sessions Web utilisent un cookie opaque `HttpOnly` et `Secure` en production, régénéré après authentification.
- **REQ-AUTH-005 — MUST** : changer de Guild active force une nouvelle vérification d'autorisation.
- **REQ-AUTH-006 — MUST** : les permissions du tenant ne sont jamais déterminées uniquement à partir d'un état client.
- **REQ-AUTH-007 — MUST** : l'Implicit Grant OAuth2 n'est pas utilisé pour authentifier le dashboard.
- **REQ-AUTH-008 — MUST** : les scopes de login initiaux sont `identify` et `guilds`; tout scope supplémentaire doit être justifié par une fonctionnalité explicite.
- **REQ-AUTH-009 — MUST** : la liste `/users/@me/guilds` est traitée comme un état de découverte/fraîcheur contrôlée et non comme une autorisation éternelle.
- **REQ-AUTH-010 — MUST** : le refresh token OAuth2 Discord nécessaire aux sessions durables est persisté uniquement côté serveur, chiffré au repos, avec scopes/version de clé/état de révocation explicites.
- **REQ-AUTH-011 — MUST** : `Déconnexion` invalide la session DID ; la révocation du grant Discord est une action explicite distincte.
- **REQ-AUTH-012 — MUST** : les mutations cookie-authenticated disposent d'une protection CSRF dédiée en plus du `state` OAuth.
- **REQ-AUTH-013 — MUST** : lorsqu'un binding de rôle Discord est nécessaire pour autoriser l'utilisateur connecté et que le cache membre est insuffisant, DID privilégie un lookup ciblé de ce membre plutôt qu'une liste complète de la Guild.
- **REQ-AUTH-014 — MUST** : la fraîcheur exigée pour une décision d'autorisation sensible est distincte de la fraîcheur d'affichage ; les actions HIGH/CRITICAL et mutations de droits imposent une revalidation ciblée de l'acteur si le cache dépasse la fenêtre de sécurité configurée.

## 53.9 Gateway et intents

- **REQ-GW-001 — MUST** : l'application déclare uniquement les intents nécessaires.
- **REQ-GW-002 — MUST** : `MESSAGE_CONTENT` n'est pas requis pour les fonctions principales de structure et permissions.
- **REQ-GW-003 — MUST** : les fonctionnalités nécessitant un intent privilégié sont identifiées comme telles.
- **REQ-GW-004 — MUST** : les événements Gateway sont normalisés avant propagation au domaine.
- **REQ-GW-005 — SHOULD** : les consumers tolèrent la répétition d'événements.
- **REQ-GW-006 — MUST** : une modification externe pertinente invalide ou rend stale les plans concernés.
- **REQ-GW-007 — MUST** : DID supporte `CHANNEL_OBFUSCATED` et ne déduit jamais une suppression de salon de la seule absence de celui-ci dans `GET Guild Channels`.
- **REQ-GW-008 — MUST** : les fonctions nécessitant joins/leaves/updates membres ou une liste complète de membres déclarent explicitement leur dépendance à l'intent privilégié `GUILD_MEMBERS` et disposent d'un mode dégradé si cet accès n'est pas disponible.

## 53.10 Audit, observabilité et données

- **REQ-AUD-001 — MUST** : chaque mutation via le dashboard est associée à son initiateur.
- **REQ-AUD-002 — MUST** : chaque mutation via un plan possède un `plan_id`.
- **REQ-AUD-003 — SHOULD** : utiliser `X-Audit-Log-Reason` lorsque l'endpoint Discord le permet.
- **REQ-AUD-004 — MUST** : aucun secret n'apparaît dans les logs.
- **REQ-AUD-005 — MUST** : le produit ne dépend pas des 45 jours de rétention Discord comme unique audit durable.
- **REQ-AUD-006 — SHOULD** : les changements directs Discord sont identifiés comme drift lorsqu'ils peuvent être déterminés.
- **REQ-DATA-001 — MUST** : aucune collecte générale de contenu de messages n'est effectuée par défaut.
- **REQ-DATA-002 — MUST** : la suppression d'un tenant suit une politique de rétention/purge documentée.

## 53.11 UX

- **REQ-UX-001 — MUST** : une action impossible doit être désactivée ou rejetée avec une cause compréhensible.
- **REQ-UX-002 — MUST** : le mode simple utilise un vocabulaire humain.
- **REQ-UX-003 — MUST** : le mode expert permet d'inspecter la réalité Discord.
- **REQ-UX-004 — SHOULD** : les actions de structure principales sont accessibles via drag & drop et/ou menu contextuel.
- **REQ-UX-CTX-001 — MUST** : le menu contextuel natif du navigateur est désactivé globalement sur toute la surface du dashboard.
- **REQ-UX-CTX-002 — MUST** : tout événement `contextmenu` est intercepté par l'application avant affichage d'un menu natif.
- **REQ-UX-CTX-003 — MUST** : le clic droit est routé vers le moteur de contexte applicatif, qui affiche soit un menu DID valide, soit aucun menu.
- **REQ-UX-CTX-004 — MUST** : le menu contextuel doit être filtré par type de ressource, sélection, cible, ACL utilisateur et capacités Discord.
- **REQ-UX-CTX-005 — MUST** : le Drop Context Menu du Right Drag réutilise le même registre d'actions que les menus contextuels classiques afin d'éviter des comportements divergents.
- **REQ-UX-005 — SHOULD** : une command palette fournit des actions rapides.
- **REQ-UX-006 — MUST** : les opérations longues affichent une progression par étape.
- **REQ-UX-007 — MUST** : un succès UI n'est confirmé qu'après confirmation de l'état appliqué ou d'un état job explicitement accepté.

## 53.12 Multilingue et traduction

- **REQ-I18N-001 — MUST** : une langue, un Translation Group et un Visibility Scope sont trois concepts distincts dans le domaine et dans le stockage.
- **REQ-I18N-002 — MUST** : toute famille de traduction possède un `translation_group_id` unique tenant-scopé.
- **REQ-I18N-003 — MUST** : deux Translation Groups utilisant les mêmes langues ne peuvent jamais partager leurs routes ou variantes implicitement.
- **REQ-I18N-004 — MUST** : les variantes de salon d'un même contenu logique utilisent un Translation Channel Group stable indépendant du nom du salon.
- **REQ-I18N-005 — MUST** : une catégorie peut définir une langue par défaut et un salon peut l'hériter ou la surcharger.
- **REQ-I18N-006 — MUST** : le système supporte les liaisons de salons situés dans des catégories différentes.
- **REQ-I18N-007 — MUST** : le système supporte au minimum les topologies `HUB_AND_SPOKE` et `CUSTOM`; `FULL_MESH` est conditionné aux capacités provider.
- **REQ-I18N-008 — MUST** : un clonage multilingue passe par Portable Snapshot → Language Expansion → Dependency Graph → Visibility Resolver → Translation Topology → Preflight → Destination Plan.
- **REQ-I18N-009 — MUST** : l'ajout d'une langue à un groupe existant ne reconstruit pas les variantes déjà valides.
- **REQ-I18N-010 — MUST** : retirer une langue ne supprime aucune ressource Discord sans choix destructif explicite.
- **REQ-I18N-011 — MUST** : une ressource peut être dissociée d'un groupe sans être supprimée de Discord.
- **REQ-I18N-012 — MUST** : toute liaison automatique proposée entre salons/catégories reste confirmable ; une correspondance ambiguë n'est jamais appliquée silencieusement.
- **REQ-I18N-013 — MUST** : un Right Drag peut proposer `CREATE_VARIANT`, `LINK_EXISTING_VARIANT`, `CLONE_UNLINKED`, `PREVIEW` selon contexte et permissions.
- **REQ-I18N-014 — MUST** : le fait de déclarer une langue n'active pas automatiquement une restriction de visibilité.
- **REQ-I18N-015 — MUST** : les politiques de visibilité linguistique supportent `OPEN_ALL`, `LANGUAGE_FILTERED`, `SCOPE_AND_LANGUAGE` et `CUSTOM`.
- **REQ-I18N-016 — MUST** : le moteur ne compile jamais `Scope role + Language role` comme un opérateur logique `AND` implicite.
- **REQ-I18N-017 — MUST** : lorsque l'accès requiert `Scope AND Language`, le système utilise un binding technique équivalent explicitement calculé, typiquement un rôle `Visibility Scope × Language`.
- **REQ-I18N-018 — MUST** : les rôles techniques `Scope × Language` sont réutilisés entre Translation Groups partageant la même audience et la même langue.
- **REQ-I18N-019 — MUST** : un rôle technique DID possède par défaut zéro permission Guild dangereuse, `hoist=false` et `mentionable=false`.
- **REQ-I18N-020 — MUST** : le Role Optimizer vérifie le budget de rôles avant tout plan de création.
- **REQ-I18N-021 — MUST** : le Permission/Capacity Engine vérifie le budget d'overwrites et signale le dépassement potentiel de 1000 overwrites par salon.
- **REQ-I18N-022 — SHOULD** : les member-specific overwrites ne sont pas utilisés comme stratégie normale de visibilité multilingue.
- **REQ-I18N-023 — MUST** : « voir plusieurs langues » attribue uniquement les bindings nécessaires dans les scopes que le membre peut réellement rejoindre.
- **REQ-I18N-024 — MUST** : aucun rôle universel `ALL_LANGUAGES` ne doit contourner la segmentation métier par défaut.
- **REQ-I18N-025 — MUST** : la plateforme de gestion ne dépend pas d'une implémentation unique de traduction ; elle consomme un `TranslationProvider` abstrait.
- **REQ-I18N-026 — MUST** : l'adapter expose au Capability Engine les capacités réellement connues/testées du provider ; le bot de traduction existant n'a pas à être modifié pour publier lui-même ces capacités.
- **REQ-I18N-026A — MUST** : l'intégration du bot de traduction existant est non invasive et ne requiert ni nouvelle API, ni changement de schéma, ni partage de token ; si aucune interface existante sûre d'automatisation n'existe, DID utilise `MANUAL_CONFIGURATION_REQUIRED`.
- **REQ-I18N-027 — MUST** : DID ne demande pas `MESSAGE_CONTENT` uniquement pour gérer la topologie multilingue.
- **REQ-I18N-028 — MUST** : si un provider séparé exige `MESSAGE_CONTENT`, cette exigence est portée et documentée par le provider.
- **REQ-I18N-029 — MUST** : une suppression externe d'une variante marque celle-ci `MISSING` sans supprimer les autres variantes.
- **REQ-I18N-030 — MUST** : le drift d'un Translation Group est visible et réparable sans propagation destructive automatique.
- **REQ-I18N-031 — MUST** : un clone inter-Guild d'un Translation Group crée un nouveau groupe indépendant sur la destination et ne crée aucune liaison live source/destination.
- **REQ-I18N-032 — MUST** : aucun secret ni token de Translation Provider n'est inclus dans un Portable Artifact.
- **REQ-I18N-033 — MUST** : l'échec de configuration provider après création Discord produit un état partiellement appliqué diagnostiquable, sans rollback destructif automatique.
- **REQ-I18N-034 — SHOULD** : la vue Traductions expose les groupes, variantes, langues, scopes, dérives et état provider dans une représentation arborescente explicite.
- **REQ-I18N-035 — MUST** : l'audit interne trace création, liaison, dissociation, changement de route, changement de langue et changement de binding de visibilité.
- **REQ-I18N-036 — MUST** : lorsqu’un Translation Provider est un bot Discord, le preflight vérifie sa présence et ses permissions effectives sur toutes les variantes concernées.
- **REQ-I18N-037 — MUST** : le système ne recommande pas `ADMINISTRATOR` au Translation Provider comme mécanisme normal d’accès aux salons.
- **REQ-I18N-038 — MUST** : les rôles d’audience humaine `LANG_*` / `Scope × Language` ne servent pas de mécanisme principal d’accès du bot provider.
- **REQ-I18N-039 — MUST** : un choix de langue utilisateur ne confère jamais un scope métier supplémentaire.
- **REQ-I18N-040 — SHOULD** : l’onboarding peut utiliser les Language Profiles et déclencher la réconciliation des rôles techniques dérivés.
- **REQ-I18N-041 — MUST** : un membre n'a aucune langue principale obligatoire ; son profil linguistique est un ensemble de zéro, une ou plusieurs langues visibles.
- **REQ-I18N-042 — MUST** : désactiver ou supprimer une langue ne sélectionne jamais automatiquement une autre langue comme fallback et ne modifie pas silencieusement les autres langues visibles du membre.

## 53.13 Cache, réconciliation et rate limits

- **REQ-CACHE-001 — MUST** : les lectures courantes du dashboard sont servies depuis le cache local et ne déclenchent pas automatiquement un appel Discord.
- **REQ-CACHE-002 — MUST** : PostgreSQL conserve le dernier état connu durable des ressources structurelles nécessaires au produit.
- **REQ-CACHE-003 — MUST** : les événements Gateway mettent à jour le cache incrémentalement.
- **REQ-CACHE-004 — MUST** : une mutation DID réussie effectue un write-through du cache à partir de la réponse Discord avant toute éventuelle vérification REST supplémentaire.
- **REQ-CACHE-005 — MUST** : toute ressource susceptible d'être obfusquée distingue état actuel observable et dernière métadonnée complète connue.
- **REQ-CACHE-006 — MUST** : une ressource précédemment visible puis obfusquée reste traçable comme `ACCESS_LOST/OBFUSCATED` jusqu'à reprise de visibilité ou suppression confirmée.
- **REQ-CACHE-007 — MUST** : la vue Structure masque par défaut `OBFUSCATED`, `ACCESS_LOST` et `DELETED_CONFIRMED`; les tombstones purgés n'appartiennent pas à l'arbre actif. Une option utilisateur explicite « Afficher les salons et catégories masqués ou supprimés » expose les ressources historiques encore présentes dans le cache.
- **REQ-CACHE-008 — MUST** : un utilisateur autorisé peut confirmer manuellement la suppression d'une ressource anciennement connue et la purger du cache individuellement ou en bulk.
- **REQ-CACHE-009 — MUST** : une purge cache ne déclenche jamais de suppression Discord et conserve un tombstone minimal auditable.
- **REQ-CACHE-010 — MUST** : toute observation Discord non ambiguë d'un `channel_id` précédemment purgé invalide le tombstone et recrée l'état cache approprié.
- **REQ-CACHE-011 — MUST** : les opérations bulk de purge sont planifiées/auditées et exposent le nombre et la liste des ressources ciblées avant exécution.
- **REQ-CACHE-012 — MUST** : le scheduler de réconciliation utilise jitter, déduplication, priorité et backpressure au lieu d'un polling synchronisé de toutes les Guilds.
- **REQ-CACHE-013 — MUST** : les refresh identiques concurrents sont coalescés/single-flight lorsque possible.
- **REQ-RATE-001 — MUST** : la logique ne hardcode pas les limites de route Discord et se base sur les headers/réponses de rate limit.
- **REQ-RATE-002 — MUST** : les requêtes bot-token REST passent par un mécanisme de gouvernance commun tenant compte des buckets et du budget global.
- **REQ-RATE-003 — MUST** : DID respecte `Retry-After` et ne retry pas aveuglément un `429`.
- **REQ-RATE-004 — MUST** : les `401/403/429` prévisibles sont minimisés par validation préalable et suivis comme budget d'invalid requests.
- **REQ-RATE-005 — SHOULD** : le Plan Compiler utilise les endpoints bulk Discord lorsqu'ils réduisent le nombre de requêtes sans modifier la sémantique demandée.
- **REQ-RATE-006 — MUST** : les métriques exposent au minimum 429, temps d'attente rate-limit, profondeur de queue, cache hit ratio et invalid requests sur fenêtre glissante.

## 53.14 Internationalisation complète du dashboard

- **REQ-UI18N-001 — MUST** : aucune chaîne système visible dans le dashboard ne doit être hardcodée hors du système i18n.
- **REQ-UI18N-002 — MUST** : menus, menus contextuels, toasts, tooltips, dialogues, erreurs, badges, placeholders, textes ARIA et états de jobs sont localisés.
- **REQ-UI18N-003 — MUST** : EN, FR, DE et ES sont livrés comme packs UI complets et activables immédiatement.
- **REQ-UI18N-004 — MUST** : une nouvelle locale UI peut être enregistrée/chargée à chaud depuis le backend sans recompilation du frontend.
- **REQ-UI18N-005 — MUST** : un pack UI ne peut être activé que s'il couvre 100 % du catalogue obligatoire courant.
- **REQ-UI18N-006 — MUST** : une locale active ne doit jamais afficher silencieusement une clé brute ou un fallback d'une autre langue pour une chaîne obligatoire.
- **REQ-UI18N-007 — MUST** : la langue UI est indépendante des Language Profiles et des langues visibles d'une Guild.
- **REQ-UI18N-008 — MUST** : les erreurs backend destinées à l'UX sont transportées comme code/message-key + paramètres localisables plutôt que comme phrases figées.
- **REQ-UI18N-009 — MUST** : dates, nombres, durées, pluriels et temps relatifs utilisent le locale UI.
- **REQ-UI18N-010 — MUST** : la CI vérifie les clés manquantes, interpolations invalides et chaînes UI hardcodées.
- **REQ-UI18N-011 — MUST** : les flows E2E critiques sont testés au minimum en EN/FR/DE/ES.
- **REQ-UI18N-012 — MUST** : la pile de rendu couvre Unicode/emoji et un composant de drapeau normalisé assure un rendu cohérent des sélecteurs de langue indépendamment des limitations de fonte/OS.
- **REQ-UI18N-013 — MUST** : en l'absence d'override utilisateur, la locale effective du dashboard est résolue depuis les préférences du navigateur (`navigator.languages`, avec `Accept-Language` pour le bootstrap) puis fallback `en` si aucune locale active ne correspond.
- **REQ-UI18N-014 — MUST** : le sélecteur de langue propose `Automatique (langue du navigateur)` et revenir à ce mode supprime l'override persistant.
- **REQ-UI18N-015 — MUST** : la locale Discord du profil OAuth2 n'écrase jamais la préférence navigateur demandée pour le dashboard.
- **REQ-UI18N-016 — MUST** : l'écran de connexion pré-authentification est localisé avec la même résolution navigateur.
- **REQ-UI18N-017 — MUST** : les packs complets EN/FR/DE/ES sont disponibles localement au frontend comme fallback de bootstrap afin qu'une panne de l'API de locales ne rende pas l'interface de base non traduite.
- **REQ-UI18N-018 — MUST** : un override utilisateur pointant vers une locale désactivée/incompatible n'est jamais rendu partiellement ; DID applique temporairement la résolution navigateur/fallback tout en pouvant conserver la préférence pour sa réactivation future.
- **REQ-UI18N-019 — MUST** : un fallback bootstrap complet est toujours garanti ; `en` est non désactivable tant qu'aucune autre locale complète n'a été explicitement désignée et validée pour ce rôle.
- **REQ-UI18N-020 — MUST** : un locale pack ne peut injecter aucun HTML/script arbitraire ; les textes riches passent par des composants/tokens autorisés et échappés.
- **REQ-UI18N-021 — MUST** : les Application Commands Discord exposées aux utilisateurs utilisent les localisations natives Discord pour leurs noms/descriptions/options dans les langues supportées, sans confondre locale Discord et UI Locale du dashboard.

## 53.15 Communication, campagnes et traduction sûre

- **REQ-MSG-001 — MUST** : DID fournit un Campaign Engine permettant publication immédiate, différée, récurrente et événementielle.
- **REQ-MSG-002 — MUST** : une campagne peut cibler plusieurs Guilds autorisées, plusieurs salons, groupes logiques, Translation Groups et langues lorsque ces sélecteurs sont résolubles vers des salons Discord réels.
- **REQ-MSG-003 — MUST** : toute cible cross-Guild est autorisée et revalidée indépendamment au moment de la livraison.
- **REQ-MSG-004 — MUST** : le moteur supporte message simple et embeds, avec validation des limites/capacités Discord avant publication.
- **REQ-MSG-005 — MUST** : les livraisons sont idempotentes et une redélivrance de job ne doit pas créer de doublon silencieux.
- **REQ-MSG-006 — MUST** : les mentions sont gérées via une politique explicite `allowed_mentions`; les pings massifs ne sont jamais activés implicitement par le contenu traduit.
- **REQ-MSG-007 — MUST** : lorsqu'un salon appartient à un Translation Channel Group, l'UI propose explicitement source seule, provider existant, fan-out traduit DID ou sélection de langues.
- **REQ-MSG-008 — MUST** : le bot de traduction existant n'a pas à être modifié pour utiliser le Campaign Engine.
- **REQ-MSG-009 — MUST** : DID utilise `googletrans` derrière un adapter interne pour les traductions directes de campagnes demandées, sans exposer la librairie au domaine.
- **REQ-MSG-010 — MUST** : le texte Discord brut n'est jamais envoyé aveuglément au moteur de traduction ; il passe par un parseur/protecteur Discord-safe qui masque les tokens techniques tout en conservant le maximum de contexte linguistique.
- **REQ-MSG-011 — MUST** : URL, mentions Discord, commandes, emojis custom, timestamps, code, variables et identifiants techniques protégés sont préservés exactement.
- **REQ-MSG-012 — MUST** : toute corruption d'un token protégé fait échouer la validation et bloque la publication de la variante concernée.
- **REQ-MSG-013 — MUST** : les champs techniques d'embed/composants ne sont jamais traduits ; seuls les champs textuels explicitement autorisés le sont.
- **REQ-MSG-014 — MUST** : le système supporte glossaires `DO_NOT_TRANSLATE` et traductions forcées par langue/scope/template avec une priorité déterministe du plus spécifique au plus général.
- **REQ-MSG-015 — MUST** : la conformité au glossaire et l'intégrité technique sont vérifiées après traduction.
- **REQ-MSG-016 — MUST** : la plateforme ne prétend jamais garantir la perfection sémantique d'une traduction automatique ; elle fournit preview, édition, politiques de revue et variantes approuvées.
- **REQ-MSG-017 — SHOULD** : les campagnes récurrentes réutilisent des variantes localisées approuvées plutôt que retraduire un texte statique à chaque occurrence.
- **REQ-MSG-018 — MUST** : les variables de template sont typées `TRANSLATABLE_TEXT`, `NON_TRANSLATABLE`, `LOCALIZED_VALUE` ou type protégé équivalent.
- **REQ-MSG-019 — MUST** : chaque livraison conserve son `discord_message_id`, son statut, son occurrence, sa langue et son snapshot de contenu DID selon la politique de rétention.
- **REQ-MSG-020 — MUST** : une campagne événementielle utilisant le contenu de messages Discord identifie explicitement la dépendance éventuelle à `MESSAGE_CONTENT`.
- **REQ-MSG-021 — MUST** : le scheduler et le moteur d'événements appliquent des conditions composables ; les récurrences temporelles sont stockées canoniquement en RRULE + timezone IANA.
- **REQ-MSG-022 — MUST** : une simulation de campagne permet de connaître les destinations, langues, erreurs de permission, état de traduction et volume de livraisons sans publier.
- **REQ-MSG-023 — MUST** : le moteur de traduction préserve autant que possible le contexte linguistique complet ; il ne découpe pas arbitrairement une phrase en fragments indépendants uniquement pour protéger les tokens Discord.
- **REQ-MSG-024 — MUST** : la stratégie de masquage/segmentation utilisée avec `googletrans` est sélectionnée et maintenue à partir de tests réels sur un corpus de régression FR/EN/DE/ES représentatif.
- **REQ-MSG-025 — MUST** : l'intégrité de tous les tokens techniques protégés doit être de 100 % sur le corpus de conformité ; toute corruption bloque la publication.
- **REQ-MSG-026 — SHOULD** : la stratégie peut être adaptée par classe de contenu si les benchmarks démontrent qu'une unité de contexte différente améliore réellement la qualité sans diminuer l'intégrité technique.
- **REQ-MSG-027 — MUST** : toute campagne événementielle déclare explicitement ses Guilds/scopes sources autorisés ; un `event_type` seul ne suffit jamais à déclencher une campagne cross-Guild.
- **REQ-MSG-028 — MUST** : la langue source d'un contenu de campagne est indépendante du `UI Locale` du dashboard.
- **REQ-MSG-029 — MUST** : les créations de messages de campagne utilisent le mécanisme Discord `nonce` + `enforce_nonce` lorsque disponible, en complément du ledger d'idempotence local.
- **REQ-MSG-030 — MUST** : les campagnes événementielles propagent correlation/causation et empêchent les boucles directes ou cycliques, y compris cross-Guild.
- **REQ-MSG-031 — MUST** : toute édition d'un message géré par DID renvoie explicitement `allowed_mentions` et la politique d'attachments à conserver afin d'éviter tout changement implicite dangereux.

## 53.16 Tests

- **REQ-TEST-001 — MUST** : chaque endpoint tenant-scopé possède un test cross-tenant.
- **REQ-TEST-002 — MUST** : le moteur de permissions possède des tests unitaires exhaustifs sur les règles critiques.
- **REQ-TEST-003 — MUST** : au moins deux Guild Discord sandbox indépendantes sont utilisées pour les tests d'intégration réels.
- **REQ-TEST-004 — MUST** : les opérations destructives sont testées avec leurs erreurs et échecs partiels.
- **REQ-TEST-005 — SHOULD** : les flows critiques dashboard sont couverts par E2E Playwright.
