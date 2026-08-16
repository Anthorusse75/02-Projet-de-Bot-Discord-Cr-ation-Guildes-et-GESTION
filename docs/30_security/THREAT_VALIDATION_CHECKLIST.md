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
