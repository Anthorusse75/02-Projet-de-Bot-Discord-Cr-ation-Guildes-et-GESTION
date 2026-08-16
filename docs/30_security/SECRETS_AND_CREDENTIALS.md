# Secrets et credentials

## Règles absolues

Aucun secret réel dans Git, Markdown, prompt, fixture, capture ou log. `.env.local` est gitignored. Le code charge les secrets depuis l’environnement ou un secret manager, valide leur présence sans afficher leur valeur et redacted toute erreur. GitHub utilise des environments protégés et secrets dédiés. Les credentials de test sont temporaires et rotatables.

| Nom | Obligatoire | Étape d’introduction | Secret ? | Provenance | Stockage local | Stockage CI | Rotation |
|---|---|---:|---:|---|---|---|---|
| `DATABASE_URL` | oui pour intégration | 01 | oui | PostgreSQL local/CI | `.env.local` | secret/service CI | à changement d’environnement |
| `REDIS_URL` | oui pour intégration | 01 | potentiellement | Redis local/CI | `.env.local` | secret/service CI | à changement d’environnement |
| `SESSION_SECRET` | oui | 02 | oui | généré CSPRNG | `.env.local` | GitHub environment | périodique + incident |
| `OAUTH_TOKEN_ENCRYPTION_KEY` | oui | 02 | oui | KMS/CSPRNG | `.env.local` | GitHub environment | versionnée, procédure rewrap |
| `DISCORD_CLIENT_ID` | oui live | 02 | non sensible mais config | Developer Portal | `.env.local` | variable | à remplacement app |
| `DISCORD_CLIENT_SECRET` | oui live | 02 | oui | Developer Portal | `.env.local` | GitHub environment | après exposition/usage temporaire |
| `DISCORD_BOT_TOKEN` | oui live | 02–03 | oui critique | Developer Portal | `.env.local` | environment protégé | après exposition, tests temporaires ou incident |
| `DISCORD_TEST_GUILD_A_ID` | oui sandbox | 02 | non secret, sensible | Guild sandbox A | `.env.local` | variable protégée | à recréation Guild |
| `DISCORD_TEST_GUILD_B_ID` | oui cross-Guild | 02/06 | non secret, sensible | Guild sandbox B | `.env.local` | variable protégée | à recréation Guild |
| `DISCORD_OAUTH_REDIRECT_URI` | oui OAuth | 02 | non | environnement/app portal | `.env.local` | variable | à changement domaine |
| `ARTIFACT_ENCRYPTION_KEY` | oui | 06 | oui | KMS/CSPRNG | `.env.local` | GitHub environment | versionnée + re-encryption |
| credentials Translation Provider | si adapter le requiert | 08 | oui | provider externe | `.env.local`/secret store | environment protégé | politique provider |
| accès `googletrans` | selon adapter réel | 09 | à confirmer | service retenu | secret store si requis | environment protégé | à confirmer |
| TLS/DNS/cloud/registry | production | 11 | oui selon type | fournisseurs réels | secret store, jamais fichier repo | GitHub environment prod | runbook STAGE 11 |

Ne demander à l’utilisateur que le sous-ensemble indispensable au moment exact du premier test live. Avant ce point, utiliser ports/fakes contractuels sans valeur réelle. Après chaque test live, vérifier redaction, inventaire et besoin de révocation.
