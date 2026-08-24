# Politique de tests d’isolation tenant

## Modèle

Fixtures minimales : Guild A, Guild B, User A (A seulement), User B (B seulement), User AB (droits explicitement différents), User None. Les mêmes IDs de ressources locales sont tentés dans query, path, body, batch, import et événement afin de détecter IDOR et confused deputy.

## Obligations par couche

| Couche | Assertion obligatoire |
|---|---|
| router/API | contexte tenant issu de session/route validée, jamais du body seul |
| application | capability et ownership cible vérifiés avant use case |
| repository | `guild_id` obligatoire ; aucune méthode tenant globale accidentelle |
| PostgreSQL | RLS refuse contexte absent ou B depuis A ; FK/unique composites empêchent liens croisés |
| Redis | clé/canal/lock/stream inclut Guild ; subscriber A ne reçoit pas B |
| worker | payload enfant contient Guild ; job parent Control Plane ne mute pas Discord |
| WebSocket | abonnement lié à une Guild autorisée, revalidation et déconnexion sûres |
| audit/log/metrics | aucune donnée métier de B dans réponse/preuve A |
| export/clone | export A et import B indépendants ; artifact ne confère aucun accès futur |

Toute nouvelle feature tenant-scopée ajoute ces cas. Un refus doit survenir avant accès repository lorsque cet accès pourrait révéler l’existence. Les tests instrumentent les repositories/adapters afin de prouver zéro appel interdit, pas seulement le statut HTTP.

## Extension STAGE 05

Les tables plan/snapshot/opération/dépendance/symbole/attempt/confirmation/progression/expected-mutation portent toutes `guild_id`, des clés étrangères composites et `ENABLE/FORCE ROW LEVEL SECURITY`. Les routes autorisent avant la lecture du plan et interdisent les IDs numériques JSON. Les jobs `APPLY_PLAN`, locks Redis, audit, progress et corrélations Gateway sont Guild-scopés. Le worker ne résout aucun symbole ni résultat depuis une autre Guild, et les tests A/B vérifient l'absence de divulgation via RLS.
