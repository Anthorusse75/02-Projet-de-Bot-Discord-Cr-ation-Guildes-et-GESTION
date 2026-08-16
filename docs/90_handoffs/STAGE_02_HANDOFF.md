# Handoff STAGE 02 — OAuth2, sessions, tenancy, RBAC et installation

| Champ | Valeur |
|---|---|
| Date | `2026-08-16` |
| Base `main` | `f2d422d68a8f33661b37f17df1b013bffcba132d` |
| Commit d’implémentation | `ccf44308dbef1124718cf1f841ef06b8b3cf8c47` |
| Branche / PR | `stage/02-auth-tenancy` / [draft PR #2](https://github.com/Anthorusse75/02-Projet-de-Bot-Discord-Cr-ation-Guildes-et-GESTION/pull/2) |
| Statut | `COMPLETE_WITH_APPROVED_LIVE_LIMITATION` ; branche publiée et draft PR ouverte |
| Migration | `0002_stage_02` après `0001_stage_01` |

## Livré

- flux OAuth2 Discord Authorization Code entièrement backend, `state` aléatoire à usage unique stocké sous forme de hash dans Redis, expiration 300 secondes et validation stricte du callback ;
- scopes OAuth exactement `identify guilds`, échange et rafraîchissement en formulaire URL-encodé, révocation locale et distante des grants ;
- jetons d’accès et de rafraîchissement chiffrés au repos en AES-256-GCM avec nonce distinct, données associées, version de clé et mise à jour optimiste par `row_version` ;
- sessions Redis opaques : identifiant aléatoire signé par HMAC, rotation à l’authentification, révocation unitaire et globale, expiration inactive de 3 600 secondes et durée absolue de 604 800 secondes ;
- cookie `did_session` en développement et `__Host-did_session` en production, `HttpOnly`, `SameSite=Lax`, `Secure` en production, chemin `/` ; jeton CSRF lié à la session et exigé via `X-CSRF-Token` pour les mutations ;
- découverte des guildes cache-first (TTL 300 secondes), sélection explicite du tenant et Snowflakes transportés comme strings dans l’API et le frontend ;
- lecture live d’autorisation bornée à `Get Guild Member` pour l’acteur courant, cache de fraîcheur de 120 secondes et aucun appel à la liste complète des membres ;
- contrôle RBAC par capacités, rôles plateforme `OWNER`, `TENANT_ADMIN`, `READ_ONLY`, statuts d’accès `ACTIVE`/`REVOKED` et portées `GUILD`, `LOGICAL_GROUP`, `VISIBILITY_SCOPE` ;
- bootstrap autorisé uniquement au propriétaire Discord ou à un utilisateur portant le bit `ADMINISTRATOR`, idempotent, créant l’accès `OWNER` et activant l’installation ;
- cycle d’installation explicite `DISCOVERED`, `INSTALLED`, `PENDING_SETUP`, `ACTIVE`, `DEGRADED`, `REVOKED`, `UNINSTALLED` ;
- endpoints de contrôle et frontend minimal avec connexion, sélection de guilde et clés i18n ; aucune mutation structurelle Discord n’est exécutée depuis le frontend ou un router FastAPI ;
- garde conservatrice des requêtes bot-token STAGE 02 : User-Agent valide, sérialisation locale, prise en compte de `Retry-After` et des en-têtes de reset. Le gouverneur distribué complet reste réservé à STAGE 03.

## Modèle de données et RLS

La migration `0002_stage_02` crée les tables suivantes :

| Table | Isolation |
|---|---|
| `users` | contexte `app.current_user_id()` |
| `discord_oauth_grants` | contexte `app.current_user_id()` |
| `user_ui_preferences` | contexte `app.current_user_id()` |
| `guild_installations` | contexte `app.current_guild_id()` |
| `guild_user_access` | contexte `app.current_guild_id()` |
| `guild_role_bindings` | contexte `app.current_guild_id()` |

Toutes activent et forcent RLS avec `USING` et `WITH CHECK`. Les repositories ouvrent des transactions courtes avec le contexte utilisateur ou guilde adapté ; les tests couvrent l’isolation A/B, l’absence de contexte, les écritures croisées et la réutilisation du pool.

## Contrat des endpoints

Dans le tableau ci-dessous, `{api-version}` vaut actuellement `1`.

| Méthode et route | Fonction |
|---|---|
| `GET /auth/discord/login` | démarre OAuth2 et crée le `state` |
| `GET /auth/discord/callback` | échange le code, persiste le grant chiffré et crée la session |
| `POST /auth/logout` | révoque la session et supprime le cookie |
| `POST /api/v{api-version}/me/oauth/discord/revoke` | révoque le grant OAuth et toutes les sessions utilisateur |
| `GET /api/v{api-version}/me` | retourne l’utilisateur, le tenant sélectionné et le jeton CSRF |
| `GET/PATCH /api/v{api-version}/me/preferences` | lit ou modifie les préférences UI |
| `GET /api/v{api-version}/guilds` | découvre les guildes visibles et leur statut d’installation |
| `POST /api/v{api-version}/guilds/{guild_id}/select` | sélectionne le tenant après autorisation |
| `GET /api/v{api-version}/guilds/{guild_id}/installation` | lit l’état d’installation |
| `POST /api/v{api-version}/guilds/{guild_id}/bootstrap` | initialise le tenant de manière idempotente |
| `DELETE /api/v{api-version}/guilds/{guild_id}/installation` | marque l’installation comme désinstallée |
| `PUT /api/v{api-version}/guilds/{guild_id}/rbac/users` | délègue ou révoque un accès utilisateur |
| `PUT /api/v{api-version}/guilds/{guild_id}/rbac/roles` | associe un rôle Discord à un rôle plateforme |

## Configuration et secrets

Seuls les noms de variables sont consignés :

- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `DISCORD_BOT_TOKEN`
- `DISCORD_REDIRECT_URI`
- `SESSION_SECRET`
- `OAUTH_TOKEN_ENCRYPTION_KEY`
- `DID_OAUTH_TOKEN_KEY_VERSION`

Le script `scripts/configure_local_stage02_secrets.py` génère les deux secrets applicatifs de développement avec le CSPRNG système et met à jour atomiquement `.env.local` sans afficher leurs valeurs. `.env.local` est ignoré par Git. Les secrets devront être régénérés et gérés par un coffre avant la production.

## Validation automatisée

| Commande ou scénario | Résultat | Preuve locale ignorée |
|---|---|---|
| `python scripts/validate_stage.py 02` | PASS, 23/23 gates | `artifacts/test-evidence/stage-02/stage02-local-final-precommit/summary.json` |
| backend unit | 47 PASS | JUnit du même run |
| PostgreSQL/Redis integration | 13 PASS | JUnit du même run |
| frontend lint/typecheck/tests/build | PASS, 4 tests | résumé du même run |
| migrations `base -> head` et `0001_stage_01 -> head` | PASS | gates du même run |
| `python scripts/validate_stage.py 01` | PASS, 19/19 gates de régression | `artifacts/test-evidence/stage-01/stage01-regression-stage02-precommit/summary.json` |
| `python scripts/check_secrets.py` | PASS, 140 fichiers | sortie locale et gate STAGE 02 |
| `python scripts/validate_documentation.py` | PASS, 11 stages, 246/246 REQ, 35 ADR | gate STAGE 02 |
| `git diff --check` | PASS | contrôle local avant commit |

Les runs locaux et leurs JUnit restent ignorés. La CI publie des artefacts nommés avec stage, SHA, run ID et tentative. Pour le HEAD courant, les checks de la PR #2 sont la source de vérité.

## Validation Discord live et nettoyage

Résultat enregistré : `PASS_WITH_APPROVED_LIMITATION`. La preuve expurgée suivie se trouve dans [`STAGE_02_LIVE_EVIDENCE.json`](STAGE_02_LIVE_EVIDENCE.json).

Exécuté réellement avec un compte Discord propriétaire :

- identité du bot conforme à l’application ;
- OAuth avec les scopes exacts `identify guilds` ;
- installation minimale observée sur Guild A et Guild B ;
- désinstallation puis réinstallation observées sur Guild A et Guild B ;
- `Get Guild Member` ciblé pour l’acteur live ;
- grants OAuth temporaires révoqués.

Non exécuté et explicitement `SKIPPED_NOT_VERIFIED` à la demande de l’utilisateur de ne pas créer trois comptes :

- profil live administrateur non propriétaire ;
- profil live non-administrateur.

Les branches d’autorisation correspondantes sont couvertes par les tests automatisés, sans être présentées comme une preuve live. Après le scénario, le bot a été réinstallé sur les deux guildes sandbox et les grants temporaires ont été révoqués. Aucun serveur n’a été supprimé.

## Vérification de la documentation Discord officielle

Consultation effectuée le `2026-08-16` :

- [OAuth2](https://docs.discord.com/developers/topics/oauth2) : Authorization Code, `state`, scopes, échange, rafraîchissement et révocation ;
- [User resource](https://docs.discord.com/developers/resources/user) : contrat de l’utilisateur et des guildes courantes ;
- [Guild resource](https://docs.discord.com/developers/resources/guild) : `Get Guild Member` ciblé ;
- [Permissions](https://docs.discord.com/developers/topics/permissions) : bit `ADMINISTRATOR` ;
- [Rate limits](https://docs.discord.com/developers/topics/rate-limits) et [API reference](https://docs.discord.com/developers/reference) : en-têtes, `Retry-After` et User-Agent ;
- [Application resource](https://docs.discord.com/developers/resources/application) : identité application/bot.

PKCE n’est pas ajouté : le backend est un client confidentiel qui authentifie l’échange avec le secret client. Aucun scope `email` ou `guilds.members.read` n’est demandé. Aucun écart constaté entre l’implémentation STAGE 02 et les contrats Discord utilisés.

## Écarts, risques et limites connus

- les deux profils live non propriétaires restent non vérifiés en conditions réelles à cause de la contrainte explicite d’un compte unique ;
- le gouverneur REST distribué complet, les buckets partagés entre processus et les métriques de quota appartiennent à STAGE 03 ;
- la détection durable installation/désinstallation par événements Gateway appartient à STAGE 03 ; le runner live STAGE 02 observe directement les deux guildes sandbox ;
- la rotation opérationnelle des clés de production et la migration des ciphertexts vers une nouvelle version doivent être réalisées avant mise en production ;
- le mapping de capacités est prêt pour les modules futurs, mais aucun évaluateur complet des permissions Discord structurelles n’est anticipé ici ;
- aucune fonctionnalité de STAGE 03, aucun moteur de snapshot/plan/apply et aucune mutation Discord structurelle n’ont été commencés ;
- aucun bug bloquant, test affaibli, secret tracké ou TODO silencieux n’est connu.

## Prérequis exacts de STAGE 03

- merger normalement la PR #2 sur `main`, puis repartir de son SHA final ;
- vérifier `alembic heads` = `0002_stage_02` et les validateurs STAGE 01/02 verts sur le commit intégré ;
- renouveler les credentials sandbox si nécessaire sans jamais les committer ;
- conserver les frontières RLS, sessions et control plane de STAGE 02 ;
- lire le contrat global, l’état courant et le fichier STAGE 03 avant toute modification ;
- ne pas considérer les deux profils live sautés comme vérifiés sans une future exécution avec des acteurs distincts.
