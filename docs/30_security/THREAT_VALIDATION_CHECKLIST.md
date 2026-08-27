# Checklist de validation des menaces

## Identité et session

- OAuth `state` aléatoire, one-shot, expirant ; callback lié à la tentative ; redirect URI allowlistée.
- Échange/refresh backend uniquement ; tokens chiffrés au repos ; version de clé et révocation testées.
- Cookie opaque `HttpOnly`, `Secure` en production, `SameSite` documenté, rotation après login ; logout invalide DID séparément de la révocation Discord.
- CSRF dédié sur mutations cookie-authenticated ; CORS/CSP restrictifs ; aucune donnée auth dans URL/log.

## Autorisation et isolation

- Autoriser l’utilisateur et le tenant avant toute lecture susceptible de révéler l’existence.
- IDs étrangers, mass assignment, pagination, recherche, export, WebSocket et erreurs couverts par tests A/B.
- RLS activée, policy deny-by-default, transaction avec contexte explicite ; pool nettoyé entre requêtes.
- Jobs, Redis, outbox, metrics/logs et caches portent `guild_id`; Control Plane owner-scopé.
- Cross-Guild : double autorisation, snapshot immuable, plan destination-only, aucune capability persistante source.

## Discord et mutations

- Bot sans `ADMINISTRATOR` par défaut ; permissions, intent et hiérarchie minimaux vérifiés.
- Préflight évite 403 ; 4xx non retry ; 429 respecte headers ; invalid request budget surveillé.
- Plans immuables, confirmation renforcée, stale detection, audit et idempotence.
- Crash après succès externe traité `UNKNOWN_OUTCOME`; destructive operations et compensations honnêtes.

## Entrées, contenu et supply chain

- Pydantic/schema stricts, limites taille/type, filenames et imports d’artifacts validés ; SSRF et path traversal testés.
- Locale packs sans HTML arbitraire ; interpolation échappée ; signatures/version/coverage contrôlées.
- Messages : allowed mentions fail-closed, AST/protected tokens/fingerprint, composants et URLs validés.
- Dépendances pinées, lockfiles, scanning vulnérabilités/licences, provenance des images et artefacts CI.

## Secrets et observabilité

- Secret scanning avant commit ; logs structurés avec redaction ; erreurs publiques sans détail sensible.
- Backups chiffrés, restore testé, rétention/purge tenant, données personnelles minimisées.
- Alertes auth failures, cross-tenant denies, 403/429, queue, drift, provider failure et intégrité traduction.

Chaque case cochée dans un handoff référence un test ou une décision, jamais une simple affirmation.
## Contrôles STAGE 06 — artifacts et cross-Guild

- [x] Artifact strict/versionné, champs inconnus et schémas futurs refusés.
- [x] Taille brute 2 000 000 octets, 1 000 ressources, 5 000 edges, profondeur 12 et strings 16 384 octets.
- [x] Compression et `Content-Encoding` refusés; aucune extraction, symlink, traversal ou archive imbriquée.
- [x] Parser pur sans `requests`, `aiohttp`, `httpx`, `urlopen` ni fetch URL implicite.
- [x] Tokens, URLs webhook secrètes, sessions, cookies, capacités, bindings et IDs opérationnels source interdits.
- [x] AES-256-GCM envelope, AAD owner/identity/schema/version/hash, tamper et mauvaise clé fail-closed.
- [x] Owner RLS U/V, tenant RLS A/B, FK composite cross-owner et non-disclosure.
- [x] Autorisation A/B indépendante; aucun artifact ou hash n’est une capability.
- [x] Même nom et même Snowflake source ne sont jamais une identité destination.
- [x] Rôles managed, bots, webhooks et principals sensibles exigent mapping explicite/confirmation ou restent impossibles.
- [x] RECONCILE ne supprime que les ressources du scope explicite et les rend visibles avant confirmation STAGE 05.
- [x] Quota, TTL, expiration, purge owner et cascade fail-safe des transferts testés.
