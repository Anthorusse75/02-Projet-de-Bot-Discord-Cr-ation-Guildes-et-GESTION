# Règles persistantes Codex

Avant toute modification, lire intégralement `docs/10_implementation/00_GLOBAL_IMPLEMENTATION_CONTRACT.md`, `docs/10_implementation/00_CURRENT_STATE.md` et le fichier `STAGE_XX_*.md` demandé. Pour toute ambiguïté Discord ou fonctionnelle, consulter les deux sources de `docs/00_reference/` et vérifier la documentation Discord officielle ; ne jamais inventer une capacité Discord.

Respecter les invariants multi-tenant et RLS. Aucune mutation Discord structurelle directe depuis le frontend ou un router FastAPI. Les lectures normales sont cache-first et tout REST bot-token respecte le Discord REST Workload Governor. Ne jamais exposer, journaliser, documenter ni committer un secret.

Ne jamais contourner ou affaiblir un test pour terminer une étape. Ne pas commencer silencieusement l’étape suivante. Si un prérequis est absent ou incohérent, arrêter l’implémentation de l’étape et décrire précisément le blocage.

Chaque étape se termine par les tests, preuves, handoff `docs/90_handoffs/STAGE_XX_HANDOFF.md`, mise à jour de `00_CURRENT_STATE.md`, commit et publication prévus. Le dépôt est la seule mémoire persistante : ne dépendre d’aucun historique de chat.
