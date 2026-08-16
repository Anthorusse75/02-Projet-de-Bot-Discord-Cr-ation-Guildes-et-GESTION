# Contrat global d’implémentation

## 1. Autorité documentaire

Les deux fichiers de `docs/00_reference/` sont la source de vérité. En cas de divergence : (1) préserver les invariants de sécurité et tenant ; (2) vérifier la documentation officielle Discord ; (3) consigner l’interprétation dans `docs/40_decisions/IMPLEMENTATION_DECISIONS.md` ; (4) mettre à jour la traçabilité. Aucun chat antérieur ne fait autorité.

## 2. Architecture non négociable

- une Guild Discord est un tenant ; toute donnée tenant-scopée porte `guild_id`, avec contrôle applicatif et RLS lorsque pertinent ;
- le User Control Plane est séparé et autorisé par `owner_discord_user_id` ;
- frontend → API → service applicatif → ports ; aucun token ou appel Discord direct depuis le frontend ;
- un router FastAPI ne réalise aucune mutation Discord structurelle ; il persiste intention, plan et outbox ;
- les mutations passent par Desired State Graph → plan → preflight/impact → confirmation → worker → Discord → vérification/audit ;
- les lectures usuelles sont cache-first ; Gateway, réponses de mutation et reconcile rate-limit-aware alimentent le cache ;
- le Discord I/O Worker possède la majorité des appels REST bot-token et le Workload Governor ;
- un plan et un job enfant mutent une seule Guild ; les opérations multi-Guild fan-out après double autorisation ;
- les permissions Discord utilisent des entiers sans perte côté Python et des chaînes côté API/TypeScript ;
- aucun rollback ne promet de restaurer un ID ou un historique Discord supprimé ;
- une création `UNKNOWN_OUTCOME` est réconciliée avant tout retry ;
- les langues, Translation Groups et Visibility Scopes restent des concepts distincts ;
- toute traduction de message passe par AST Discord-safe, protection, empreinte et validation fail-closed ;
- toute chaîne système visible a une clé i18n couverte EN/FR/DE/ES.

## 3. Workflow Git

Branches obligatoires :

```text
main
stage/01-foundations
stage/02-auth-tenancy
stage/03-discord-runtime
stage/04-read-permissions
stage/05-plan-engine
stage/06-portability
stage/07-dashboard
stage/08-multilingual-topology
stage/09-campaigns
stage/10-acceptance
stage/11-final-deployment
```

Pour chaque étape : synchroniser `main`, créer la branche, exécuter le PRECHECK, implémenter uniquement le scope, valider, produire les preuves et le handoff, mettre à jour l’état et la traçabilité, committer, pousser, ouvrir une PR, revoir puis merger. Ne commencer l’étape suivante qu’après intégration à `main`.

## 4. Discipline de développement

- environnement cible : Windows 11, VS Code, Git Bash ; WSL n’est pas requis ;
- les commandes normatives sont compatibles Git Bash ; une variante PowerShell explicite peut compléter sans remplacer le workflow ;
- dépendances pinées et lockfiles versionnés ; migrations Alembic immuables après déploiement ;
- domaine sans import d’infrastructure ; use cases retournant des objets métier ; transactions DB jamais maintenues pendant de longues séries d’appels Discord ;
- clés Redis tenant-scopées sous `did:guild:{guild_id}:...`; locks inter-Guild interdits pour une feature standard ;
- toute feature tenant-scopée a un test A/B, et toute action critique un audit ;
- pas de TODO bloquant masqué, de test désactivé, de fake remplaçant une preuve Discord critique, ni de chaîne UI hardcodée ;
- tout comportement Discord incertain est vérifié contre les docs officielles et, lorsqu’il est critique, en sandbox.

## 5. Contrat de validation d’une étape

Une étape n’est terminée que si son orchestrateur `python scripts/validate_stage.py XX` existe (créé en STAGE 01 puis étendu), retourne zéro, et référence des preuves conservées sans secret. Les validations comprennent selon le scope : lint, format check, typecheck, tests unitaires, PostgreSQL/RLS, Redis, API, composants, Playwright, isolation A/B, failure injection, migration smoke et Discord sandbox.

Chaque exigence assignée passe de `PLANNED` à `IMPLEMENTED`, puis `VERIFIED` seulement avec test, commande, résultat et commit/artefact identifiables. Un test mocké seul ne vérifie pas une sémantique Discord critique.

## 6. Handoff et mémoire persistante

La clôture crée `docs/90_handoffs/STAGE_XX_HANDOFF.md` à partir du modèle, actualise `00_CURRENT_STATE.md`, la matrice et les décisions. Le handoff contient le SHA, la PR, migrations, modules, commandes/résultats, configurations externes, écarts, risques, état des containers et Guilds sandbox, ainsi que le PRECHECK attendu ensuite.

## 7. Secrets

Les secrets sont saisis uniquement au moment où un test ou une exécution les exige, via `.env.local`, environnement sécurisé ou GitHub Secrets. Ils ne sont jamais collés dans un prompt, commit, Markdown, fixture, capture, sortie de validation ou log. Toute preuve est expurgée. Les credentials temporaires sont révoqués ou tournés après usage.

## 8. Arrêt obligatoire

Arrêter l’étape et décrire le blocage si : branche/base incohérente, étape précédente non intégrée, migration attendue absente, test antérieur rouge, source normative contradictoire sans décision sûre, secret/action humaine indispensable manquant, ou comportement Discord critique non vérifiable. Ne pas réduire le scope ni passer à l’étape suivante pour contourner le blocage.
