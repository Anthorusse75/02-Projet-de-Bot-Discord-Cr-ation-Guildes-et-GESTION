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

## IMP-010 — Modèle de permissions Discord versionné et fail-safe

- Date : 2026-08-17
- Statut : `RESOLVED_OFFICIAL_CONTRACT_CONFIRMED`
- Sources officielles relues : [Permissions](https://docs.discord.com/developers/topics/permissions), [Threads](https://docs.discord.com/developers/topics/threads), [Channel Resource](https://docs.discord.com/developers/resources/channel), [Guild Resource](https://docs.discord.com/developers/resources/guild), [Server and Channel Management](https://docs.discord.com/developers/platform/server-and-channel-management) et [Change Log](https://docs.discord.com/developers/change-log).
- Registry : version interne `discord-permissions-2026-08-17`, bits officiels 0 à 52 avec le bit 47 non assigné. Les bitfields restent des `int` Python et des chaînes décimales dans l’API. Les bits absents du registry sont conservés et diagnostiqués ; aucun masque 32/53/64 bits n’est appliqué.
- Résolution : owner puis `ADMINISTRATOR` court-circuitent les overwrites pour les flags connus ; sans bypass, base `@everyone OR rôles`, overwrite everyone deny/allow, agrégation de tous les role deny puis de tous les role allow, enfin member deny/allow. La hiérarchie des rôles n’intervient jamais dans ce calcul.
- Effectivité : `calculated_bits` conserve le calcul explicite ; `effective_bits` applique séparément les indisponibilités implicites liées à `VIEW_CHANNEL`, `SEND_MESSAGES`, `CONNECT` et aux threads. Les threads utilisent les overwrites réellement observés du parent, `SEND_MESSAGES_IN_THREADS`, la membership privée connue et `MANAGE_THREADS`.
- Couverture : toute donnée critique incomplète, stale, obfusquée, perdue ou d’un type de channel futur inconnu produit `INCOMPLETE`/`UNKNOWN`; elle ne peut jamais produire `ALLOWED`. Le dernier snapshot non courant est explicitement `LAST_KNOWN`.
- Category sync : `SYNCED` signifie uniquement que les overwrites complets observés du channel et de la catégorie sont canoniquement égaux. Il ne s’agit pas d’un héritage inventé.
- Hiérarchie : pour les opérations de gestion seulement, le rôle le plus haut du bot doit être strictement au-dessus de la cible. Une position égale n'est jamais gérable et l'ordre des Snowflakes ne transforme pas cette égalité en autorisation. Un rôle managed reste non gérable. Le rôle `@everyone` ne peut être ni supprimé ni réordonné. Les remédiations proposent les permissions minimales et jamais `ADMINISTRATOR` par défaut.

## IMP-011 — Projection des threads actifs et preuves d’adhésion privées

- Date : 2026-08-24
- Statut : `RESOLVED_OFFICIAL_CONTRACT_CONFIRMED`
- Sources officielles relues : [Gateway Events](https://docs.discord.com/developers/events/gateway-events), [Threads](https://docs.discord.com/developers/topics/threads), [Permissions](https://docs.discord.com/developers/topics/permissions) et [Channel Resource](https://docs.discord.com/developers/resources/channel).
- Synchronisation : `GUILD_CREATE` et `THREAD_LIST_SYNC` décrivent les threads actifs visibles par l’utilisateur Gateway. Une absence dans ce jeu signifie `NOT_IN_ACTIVE_SYNC`, jamais une suppression. Seul `THREAD_DELETE` constitue une preuve de suppression. Un sync sans `channel_ids` couvre toute la Guild ; un sync avec `channel_ids` ne couvre que les parents annoncés, y compris un parent sans thread actif afin de vider ce sous-ensemble.
- Couverture : `ACTIVE_VISIBLE_THREADS_FULL`, `PARTIAL`, `DEGRADED` et `UNKNOWN` sont distincts de la couverture générale. Une rupture de continuité Gateway dégrade explicitement la couverture threads. Un thread explicitement connu et courant peut être évalué sans exiger une prétendue liste complète des threads archivés, que Discord ne synchronise pas à l’avance.
- Membership : la présence de `member` dans un thread de `GUILD_CREATE`, les membres de `THREAD_LIST_SYNC`, `THREAD_MEMBER_UPDATE` et l’ajout/retrait de l’utilisateur bot dans `THREAD_MEMBERS_UPDATE` alimentent une preuve `MEMBER/NOT_MEMBER` par thread. Aucune adhésion humaine ou privée n’est inventée et aucun intent `GUILD_MEMBERS` n’est requis pour ces signaux de l’utilisateur courant.
- Permissions : le thread et son parent doivent chacun être visibles et frais ; les overwrites viennent uniquement du parent. Sans `MANAGE_THREADS`, un thread verrouillé retire `SEND_MESSAGES_IN_THREADS` et ses quatre dépendances documentées. Un thread archivé mais non verrouillé reste envoyable car l’envoi peut le désarchiver automatiquement ; son état archivé reste diagnostiqué.
- API locale : permission inconnue, rôle View As absent, ressource/cible capability absente et cible d’overwrite non résolue ont des erreurs stables. Les opérations capability exigent leur channel ou rôle cible. `VisibilityScope.scope_type` et `logical_group_id` sont couplés aux frontières API, domaine et PostgreSQL.

## IMP-012 — Plans immuables et vérité des mutations externes

- Date : 2026-08-24
- Statut : `RESOLVED_OFFICIAL_CONTRACT_CONFIRMED`
- Sources officielles relues : [Channel Resource](https://docs.discord.com/developers/resources/channel), [Guild Resource](https://docs.discord.com/developers/resources/guild), [Permissions](https://docs.discord.com/developers/topics/permissions), [Rate Limits](https://docs.discord.com/developers/topics/rate-limits), [Gateway Events](https://docs.discord.com/developers/events/gateway-events) et [HTTP Reference](https://docs.discord.com/developers/reference), consultation du 2026-08-24.
- Modèle : le DSG `did-dsg-v&#49;`, les snapshots, opérations, préconditions, dépendances et symboles sont canoniques et hashés en SHA-256. Le hash est recalculé depuis le bundle persistant avant validation. Les triggers rendent les snapshots append-only et interdisent INSERT/UPDATE/DELETE des composants immuables après validation. Les IDs d'opération déterministes sont plan-scoped et la confirmation est expirante, actor-bound et liée au hash complet.
- Crash : un appel pouvant avoir atteint Discord n'est jamais assimilé à un échec connu. L'opération devient `UNKNOWN_OUTCOME`, puis une preuve operation-specific conclut création/application/absence ou `INTERVENTION_REQUIRED`. Pour les channels, une omission de `Get Guild Channels` ne prouve ni absence après CREATE ni suppression après DELETE; pour les rôles, la liste complète peut fournir cette preuve. Aucun CREATE ambigu n'est répété. `PREPARED` et `IN_FLIGHT` ont des commits distincts et la perte de lease est fenced sur owner/token/generation exacts.
- Compensation : `REVERSIBLE`, `RECREATABLE_NOT_RESTORABLE` et `NON_COMPENSABLE` décrivent honnêtement ce qui est possible ; recréer ne restaure ni ID, ni historique, ni liens externes.
- Discord : une requête bulk de positions de salons contient au plus un changement de `parent_id`, conformément à la restriction officielle actuelle. Supprimer une catégorie ne supprime pas ses enfants, donc tout effet enfant doit être explicite. Pour `REORDER_ROLES`, le preflight global et la vérification juste-à-temps refusent chaque cible managed, `@everyone`, égale ou supérieure au plus haut rôle du bot, ainsi que toute destination qui sortirait de la zone gérable ; l'adapter interdit aussi suppression et réordonnancement de `@everyone`. Le payload REST ne contient que les rôles explicitement demandés. Le segment complet de positions attendu, y compris les décalages implicites, reste séparé pour préconditions, Gateway et vérification ; une montée d'un rôle explicite normalise la coordonnée REST afin d'obtenir la position finale demandée sans ajouter de cible artificielle. Le motif d'audit est stable, borné à 512 octets et ne contient aucun texte utilisateur.
- Rate limit : un 429 de scope `shared` est mesuré et honoré via `Retry-After`, mais n'est pas compté dans le budget Discord des invalid requests ; les autres 401/403/429 suivent la politique existante.
- Autorisation : les routes sensibles et le worker utilisent le moteur STAGE 02 avec `sensitive=True`. Le worker revalide le `requested_by` durable par targeted `Get Guild Member`, capability `PLANS_APPLY`, scope Guild et installation active avant tout side effect; aucune session OAuth ni liste de membres n'est requise dans ce processus.
- Gateway/impact : les expected mutations bulk sont itemisées. Pour les rôles, elles proviennent du `expected_position_segment` complet et non des seuls items REST explicites ; celles des overwrites portent channel, target et état complet. Les matchers sont stricts et `plan_resource_dependencies` limite le stale aux plans concernés. L'impact réutilise le Permission Evaluator STAGE 04 et conserve l'inconnu lorsque la couverture membres est incomplète.
- Live : après attribution de `MANAGE_CHANNELS` et `MANAGE_ROLES` sans `ADMINISTRATOR`, le runner a exécuté six plans réels avec Governor : crash-window CREATE_ROLE récupérée sans doublon, symbol binding durable, create/update/move/reorder/overwrite/delete, restauration d'ordre et cleanup. Statut `PASS`; aucune fixture préfixée ne subsiste et la preuve suivie ne contient ni secret ni identifiant Discord.

## IMP-013 — Capabilities et frontières de portabilité STAGE 06

- Date : 2026-08-24
- Statut : `RESOLVED`
- Constat : les sources normatives exigent une autorisation indépendante d’export A et d’import/plan B, mais ne définissent aucune capability nommée `EXPORT_STRUCTURE` ou `IMPORT_STRUCTURE`. Le registre existant contient déjà `STRUCTURE_READ`, `STRUCTURE_WRITE`, `PLANS_CREATE`, `PLANS_APPLY`, `TEMPLATES_READ` et `TEMPLATES_WRITE`.
- Décision source : l’export live exige `STRUCTURE_READ` avec revalidation sensible. Il construit un snapshot immutable dans une transaction A terminée avant toute lecture B. Un artifact déjà stocké appartient à l’utilisateur et ne réautorise jamais A.
- Décision destination : preview/compile exigent séparément `PLANS_CREATE` et `STRUCTURE_WRITE` sur B. L’apply reste exclusivement celui de STAGE 05 et revalide `PLANS_APPLY`; STAGE 06 ne possède aucun adapter mutable. Les templates exigent `TEMPLATES_READ`/`TEMPLATES_WRITE` en plus des capabilities destination lors de l’apply.
- User Control Plane : clipboard, bibliothèque et transfert sont owner-scopés par `UserContext`; templates, définitions de policy et plans restent tenant-scopés. Le transfert conserve A/B comme provenance d’orchestration, jamais comme fédération ni capability. Aucun lock A+B et aucune transaction tenant cross-Guild ne sont permis.
- Portabilité ACL : une définition peut être persistée sur B sans binding actif. Toute dépendance de principal doit être mappée vers une cible B compatible, explicitement confirmée et liée au hash immutable du transfert. Les capabilities, attributions utilisateur et bindings source restent interdits dans l’artifact.

## IMP-014 — Fidélité des canaux et ownership destructif de RECONCILE

- Date : 2026-08-25
- Statut : `RESOLVED_OFFICIAL_CONTRACT_CONFIRMED`
- Sources officielles relues : [Channel Resource](https://docs.discord.com/developers/resources/channel) et [Guild Resource](https://docs.discord.com/developers/resources/guild), consultation du 2026-08-25. Discord expose notamment slowmode, durée d'archivage par défaut, bitrate et limite d'utilisateurs selon le type ; forum/media ont des champs supplémentaires et media reste signalé comme en développement actif.
- Fidélité : le contrat `did-portable-attributes-v&#50;` refuse tout attribut inconnu. Text et announcement transportent `rate_limit_per_user` et `default_auto_archive_duration`; voice et stage transportent bitrate/user limit. Category est distinct. Directory, forum et media sont `UNSUPPORTED` tant que le read model et STAGE 05 ne peuvent pas préserver fidèlement leur contrat complet. Un flag observé non créable est rapporté `PARTIAL`, jamais présenté comme complet.
- MERGE : l'identité Discord vient exclusivement du mapping B confirmé ou d'un binding de relation DID unique ; les propriétés désirées viennent exclusivement de l'artifact immutable. Les propriétés non portables de B ne sont pas injectées dans le DSG et ne deviennent pas une fausse source de vérité.
- RECONCILE : `portable_clone_bindings` associe owner, B, relation opaque, logical ref, type, ID destination réellement créé ou explicitement mappé, transfert et hash. La finalisation après succès STAGE 05 écrit ces bindings sous FORCE RLS. Preview/compile n'acceptent aucun ID à supprimer ; ils dérivent le scope depuis cette relation, croisent avec le snapshot B courant et ignorent toute ressource étrangère ou non liée.
- Report-only et lifecycle : `MAXIMUM_COMPATIBLE` persiste un transfert `COMPILED` avec rapport et `destination_plan_id=NULL`. Les autres transferts passent par transitions CAS `CREATED` → `SOURCE_AUTHORIZED` (live) → `EXPORTED` → `MAPPING_REQUIRED`/`READY` → `COMPILED`; l'état `MAPPING_REQUIRED` conserve mappings, candidats, hash, B et acteur et se reprend avec la même idempotency key sans relire A.

## IMP-015 — Identité durable de clone et intention de transfert figée

- Date : 2026-08-26
- Statut : `RESOLVED`
- Relationship : une relation destructive est une entité owner-scoped `portable_clone_relationships` dont l'UUID est généré côté serveur. Elle vérifie owner, destination et état sous `FORCE RLS`; elle n'est dérivée ni du hash, ni de la provenance, ni des IDs sélectionnés. Sa durée de vie est indépendante des artifacts et transfers éphémères.
- Identité logique : le builder dérive une clé opaque déterministe depuis Guild source, type et Snowflake source. Cette dérivation stabilise la même ressource entre générations sans exposer le Snowflake comme destination ref, comparaison A/B ou capability. Une suppression ou insertion ne renumérote pas les survivants et une clé supprimée n'est pas recyclée.
- Bindings : les bindings référencent la relationship; leur dernier transfer est informatif, nullable et `ON DELETE SET NULL`. La finalisation d'une génération active les refs présentes et tombstone les absentes. Seuls les bindings actifs forment le scope RECONCILE courant.
- Reprise live : le transfer et la relationship sont créés après l'export autorisé A et avant l'autorisation B; `SOURCE_AUTHORIZED` puis `EXPORTED` sont des états durables. Un refus B ne divulgue ni mapping ni plan et le retry reprend l'artifact sans relecture A. Chaque état `CREATED`, `SOURCE_AUTHORIZED`, `EXPORTED`, `MAPPING_REQUIRED`, `READY` et `COMPILED` possède une branche de reprise explicite.
- Intention : l'idempotency de transfer identifie artifact/B/mode/caller key et permet de compléter le mapping jusqu'à READY. La transition vers READY fige mapping canonique et `mapping_hash`. COMPILED est un CAS depuis READY; plan, mapping et report deviennent immuables. Une reprise strictement identique retourne l'existant, toute divergence produit un conflit stable sans second plan.
