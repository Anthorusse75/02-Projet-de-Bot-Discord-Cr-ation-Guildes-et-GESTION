# Handoffs d’étape

Chaque étape crée exactement `STAGE_XX_HANDOFF.md` depuis le modèle voisin. Le handoff est une photographie factuelle du code mergé, pas un plan ni un journal de chat. Il doit permettre au PRECHECK suivant de prouver la base de départ.

Un handoff n’est final qu’après mise à jour du SHA/PR, résultats de tests, migrations, écarts, état des services/sandboxes et configuration externe. Ne jamais y placer de secret ou de sortie non expurgée.
