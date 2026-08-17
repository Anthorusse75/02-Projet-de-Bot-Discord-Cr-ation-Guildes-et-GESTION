# Décisions d’implémentation

Les ADR-001 à ADR-035 restent normatifs dans la source d’architecture. Ce registre contient uniquement les décisions prises pendant l’exécution et les clarifications de cohérence ; il ne réécrit pas les sources.

## IMP-001 — Channel Obfuscation officiellement confirmée

- Date : 2026-08-17
- Statut : `RESOLVED_OFFICIAL_CONTRACT_CONFIRMED`
- Revalidation : documentation Discord officielle consultée le 2026-08-17. Sources et headings exacts : [Change Log — « Channel Obfuscation for Users and Bots », 12 août 2026](https://docs.discord.com/developers/change-log), [Channel Resource — « Obfuscated Channels »](https://docs.discord.com/developers/resources/channel) et [Gateway Events — « Gateway Capabilities »](https://docs.discord.com/developers/events/gateway-events). Ces pages officielles n’exposent pas de commit ou de révision stable ; les URL, headings et date de consultation constituent donc la provenance reproductible disponible.
- Contrat confirmé : le flag Channel `CHANNEL_OBFUSCATED` vaut `1 << 17`. Pendant la période de test, la capability Gateway `CHANNEL_OBFUSCATION` vaut `1 << 15`. Le rollout HTTP annoncé au 2026-11-16 omet de `Get Guild Channels` les salons inaccessibles ; il n’existe pas d’opt-in HTTP anticipé.
- Payload obfusqué : `id`, `type`, `position` et `parent_id` restent exploitables ; `name` devient `___hidden___`, les champs sensibles sont nuls/réduits, et les overwrites sont réduits à `@everyone` refusant `VIEW_CHANNEL`. Le Gateway continue d’émettre les événements channel usuels et renvoie un `CHANNEL_UPDATE` complet au retour de visibilité. Les payloads d’interaction ne suivent pas cette obfuscation.
- Décision : détection uniquement par le bit officiel, conservation du dernier payload complet et de ses overwrites, états explicites `VISIBLE`/`OBFUSCATED`/`ACCESS_LOST`, et omission HTTP jamais interprétée comme suppression. Le JSON versionné du 2026-08-12 est une **fixture contractuelle dérivée de la documentation officielle**, pas un payload officiel publié par Discord.
- Validation live : `CONTRACT_ONLY_NOT_LIVE_VERIFIED` pour la perte de visibilité, car aucun changement sûr de permissions sandbox n’a été imposé. La sync live A/B sans mutation est `PASS_WITH_APPROVED_LIMITATION`.

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

## IMP-005 — OAuth2 Discord confidentiel côté backend

- Date : 2026-08-16
- Statut : `RESOLVED`
- Sources officielles relues : [OAuth2 Discord](https://docs.discord.com/developers/topics/oauth2), [User resource](https://docs.discord.com/developers/resources/user) et [installation d’application](https://docs.discord.com/developers/resources/application).
- Décision : DID utilise uniquement l’Authorization Code Grant avec échange et refresh côté backend confidentiel, authentifié par `client_secret`. Les scopes initiaux forment exactement l’ensemble `identify guilds`; `guilds.members.read` n’est pas demandé. L’Implicit Grant et les tokens utilisateur non OAuth2 sont interdits.
- PKCE : non ajouté à ce client backend confidentiel, car le secret client et le code ne sont jamais traités par le navigateur applicatif. `state` reste CSPRNG, hashé dans Redis, expirant et à usage unique. Toute évolution vers un client public imposerait une nouvelle décision et PKCE.
- Écart aux sources : aucun écart Discord identifié lors de la relecture du 2026-08-16.

## IMP-006 — Session opaque et CSRF synchronizer token

- Date : 2026-08-16
- Statut : `RESOLVED`
- Décision : le cookie ne contient qu’un identifiant de session opaque ; son enregistrement Redis est indexé par HMAC, tourne après authentification, possède des durées idle/absolue et est révoqué au logout. En production, le cookie `__Host-did_session` est `Secure`, `HttpOnly`, `Path=/`, sans `Domain`, avec `SameSite=Lax`.
- CSRF : les mutations cookie-authenticated exigent un synchronizer token aléatoire conservé dans la session et fourni via `X-CSRF-Token`. Il est indépendant du `state` OAuth et tourne lors d’un changement de Guild active.

## IMP-007 — Lookup membre ciblé gouverné avant STAGE 03

- Date : 2026-08-16
- Statut : `RESOLVED_STAGE_02_SCOPE`
- Sources officielles relues : [Guild resource](https://docs.discord.com/developers/resources/guild), [permissions](https://docs.discord.com/developers/topics/permissions), [limites REST](https://docs.discord.com/developers/topics/rate-limits) et [référence HTTP](https://docs.discord.com/developers/reference).
- Décision : lorsqu’un binding de rôle est nécessaire, STAGE 02 appelle uniquement `GET /guilds/{guild.id}/members/{user.id}` pour l’acteur ; aucun endpoint de liste des membres n’est utilisé. Les décisions sensibles forcent cette relecture ciblée.
- Gouvernance REST : le transport bot-token STAGE 02 est sérialisé, fournit un User-Agent, mémorise `Retry-After`/`X-RateLimit-Reset-After` et diffère les appels suivants après 429. Le gouverneur distribué, les buckets partagés et la fairness multi-workload restent strictement STAGE 03.
- Écart aux sources : aucun écart Discord identifié lors de la relecture du 2026-08-16.

## IMP-008 — Routage opérationnel multi-tenant des runtimes STAGE 03

- Date : 2026-08-17
- Statut : `RESOLVED`
- Décision : le worker et le scheduler découvrent du travail global uniquement au moyen de trois fonctions PostgreSQL `SECURITY DEFINER` bornées et allowlistées qui retournent des `guild_id`, jamais des lignes métier. Les droits `PUBLIC` sont révoqués et seul `did_app` peut les exécuter. Toute lecture ou mutation qui suit rouvre une transaction avec `TenantContext` et reste soumise aux politiques RLS.
- Wakeup/recovery : Redis transporte des hints perdables contenant seulement les IDs de Guild. PostgreSQL reste la source durable ; un polling de récupération borné retrouve jobs et outbox si Redis est vidé ou indisponible. Le scheduler enqueue seulement, le worker exécute le REST Discord hors transaction, puis ack/retry durablement.
- Effets Redis : invalidation du hot cache, wakeup et Pub/Sub sont exécutés par l’outbox après commit PostgreSQL. Une panne Redis conserve la ligne `PENDING` avec backoff ; aucun chemin API/Gateway/reconcile ne transforme le cache Redis en vérité durable.

## IMP-009 — Coordination distribuée et fencing du runtime Discord

- Date : 2026-08-17
- Statut : `RESOLVED`
- Décision : plusieurs workers REST actifs sont supportés. Ils partagent dans Redis des permits globaux et par Guild sous forme de sorted sets à TTL et token unique. L’acquisition atomique nettoie les permits expirés et respecte les deux bornes ; renouvellement et libération exigent le token courant. `discord.py` reste seul propriétaire des buckets HTTP et de leur protocole.
- Lease job : le dispatcher n’admet qu’une vague immédiatement démarrable selon les slots locaux. Chaque lease PostgreSQL incrémente `lease_generation`, crée `lease_token`, puis est renouvelé pendant l’attente du permit distribué et pendant l’I/O. Ack/retry exigent owner, token et lease non expiré ; un ancien owner est donc fenced après recovery.
- État partagé : le budget glissant des invalid requests, la pénalité 429, la pression workload par reporter et le halt 401 sont Redis-coordonnés. La pression agrégée retarde les reconciles de fond mais ne supprime jamais une urgence `GAP_DETECTED`/`NON_RESUMED`.
- Outbox : les publications utilisent un lease PostgreSQL just-in-time, une ligne à la fois, avec `FOR UPDATE SKIP LOCKED`, owner/token/expiration et heartbeat. Le contrat reste at-least-once : un crash après publish et avant ack peut redélivrer après expiration, mais deux publishers vivants ne publient pas simultanément la même ligne.
- Single-flight : un script Lua unique réalise `ACQUIRE OR OBSERVE CURRENT GENERATION`. Un waiter reste lié à la génération observée même si l’owner publie puis libère avant le retour du script ; un appel strictement séquentiel crée une nouvelle génération.
