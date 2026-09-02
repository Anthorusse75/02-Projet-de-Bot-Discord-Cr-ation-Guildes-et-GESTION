# Stage 09 — Pack de revue sémantique humaine (`PENDING_HUMAN_REVIEW`)

## Statut

**`PENDING_HUMAN_REVIEW`.** Aucune évaluation humaine n'a eu lieu à ce jour. Aucun score n'est
fabriqué dans ce document ou ailleurs dans la documentation Stage09 — la colonne « Verdict humain »
de chaque tableau ci-dessous reste vide jusqu'à ce qu'un relecteur humain la remplisse réellement.
C'est une clause `EXTERNAL_ACCEPTANCE_ITEM` de la Definition of Done : distincte de l'intégrité
technique (mesurée machine, 100 % sur `FULL_MASKED_MESSAGE`, voir
`docs/90_handoffs/evidence/stage09/translation-benchmark.json`), qui ne peut, par nature, pas
attester de la qualité *linguistique* perçue par un locuteur natif.

## Portée

Ce pack sélectionne 10 échantillons représentatifs, extraits **verbatim** du corpus de benchmark
réel et déjà committé (`backend/tests/fixtures/translation_corpus/stage09_corpus.json`, version 3,
26 classes/104 items par langue) — aucun texte n'est inventé pour ce pack. Chaque échantillon est
présenté dans ses quatre versions nativement rédigées (EN/FR/DE/ES ; le corpus n'est pas une seule
version traduite dans les trois autres, chaque langue a son propre texte rédigé nativement) plutôt
qu'une seule direction de traduction, pour que le relecteur puisse juger n'importe laquelle des
douze directions FR↔EN↔DE↔ES pertinentes pour sa langue de compétence.

Catégories couvertes (mission de clôture, section 10) :

| Catégorie demandée | Classe(s) de corpus utilisée(s) |
|---|---|
| Prose normale | `plain_prose`, `negation_and_pronouns` |
| Prose longue / contextuelle | `long_sentence`, `multi_paragraph` |
| Texte dense en tokens techniques | `mixed_technical_and_linguistic`, `multiple_placeholders_dense` |
| Terminologie Hero Wars | `terminology_names_acronyms` |
| Style embed / bouton | `embed_title_style`, `embed_description_style`, `button_label_style` |

## Rubrique (à remplir par un relecteur humain — jamais par un outil automatique)

Pour chaque échantillon et chaque paire de langues jugée, répondre **oui/non** à chacune des cinq
questions ci-dessous. Pas d'échelle numérique, pas de score composite calculé automatiquement — la
mission demande explicitement « no scores unless a human actually supplies them ».

1. **Sens préservé** : le sens du texte source est-il fidèlement rendu, sans perte ni ajout
   d'information ?
2. **Naturel** : le texte cible se lit-il comme une phrase naturellement rédigée dans cette langue,
   pas comme une traduction mot-à-mot ?
3. **Terminologie** : les noms propres, acronymes et termes de jeu (Hero Wars, DPS, MVP, NA...)
   sont-ils traités de façon cohérente et appropriée (préservés tels quels quand c'est l'usage
   attendu, jamais traduits de façon absurde) ?
4. **Contexte / pronoms** : les pronoms, temps verbaux et références contextuelles restent-ils
   cohérents avec le paragraphe environnant (pertinent surtout pour `negation_and_pronouns` et
   `multi_paragraph`) ?
5. **Acceptable globalement (oui/non)** : verdict de synthèse du relecteur — pas une moyenne
   calculée des quatre réponses précédentes, un jugement humain direct.

## Échantillons

### 1. Prose normale — courte (`plain_prose`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | Welcome to the server! We are excited to have you here. |
| FR | Bienvenue sur le serveur ! Nous sommes ravis de vous compter parmi nous. |
| DE | Willkommen auf dem Server! Wir freuen uns sehr, dich hier zu haben. |
| ES | ¡Bienvenido al servidor! Estamos muy contentos de tenerte aquí. |

Verdict humain (1-5 ci-dessus, par paire de langues jugée) : _(à remplir)_

### 2. Prose normale — négation et pronoms (`negation_and_pronouns`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | She said she would not be attending the event herself, but she asked us to remind everyone that it is still happening without her. |
| FR | Elle a dit qu'elle n'assisterait pas elle-même à l'événement, mais elle nous a demandé de rappeler à tout le monde qu'il aura quand même lieu sans elle. |
| DE | Sie sagte, dass sie selbst nicht an der Veranstaltung teilnehmen werde, bat uns aber, alle daran zu erinnern, dass sie trotzdem ohne sie stattfindet. |
| ES | Ella dijo que no asistiría personalmente al evento, pero nos pidió que le recordáramos a todos que de todos modos se llevará a cabo sin ella. |

Verdict humain : _(à remplir)_

### 3. Prose longue / contextuelle — phrase longue (`long_sentence`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | Even though the winter update introduced a large number of balance changes across nearly every class, the community response has been overwhelmingly positive, with most players agreeing that the new pacing feels far more rewarding than before. |
| FR | Bien que la mise à jour d'hiver ait introduit un grand nombre de changements d'équilibrage pour presque toutes les classes, la réaction de la communauté a été extrêmement positive, la plupart des joueurs estimant que le nouveau rythme est bien plus gratifiant qu'auparavant. |
| DE | Obwohl das Winterupdate zahlreiche Balance-Änderungen für fast jede Klasse mit sich brachte, war die Reaktion der Community überwältigend positiv, da die meisten Spieler das neue Tempo als deutlich lohnender empfinden als zuvor. |
| ES | Aunque la actualización de invierno introdujo una gran cantidad de cambios de equilibrio en casi todas las clases, la respuesta de la comunidad ha sido abrumadoramente positiva, y la mayoría de los jugadores coincide en que el nuevo ritmo resulta mucho más gratificante que antes. |

Verdict humain : _(à remplir)_

### 4. Prose longue / contextuelle — multi-paragraphe (`multi_paragraph`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | Season three is finally here, bringing a fresh set of challenges and rewards for everyone to enjoy.<br><br>We have also rebalanced several older items that had fallen out of use, so it might be worth revisiting your old builds.<br><br>As always, thank you for being part of this community and for your continued feedback. |
| FR | La saison trois est enfin arrivée, apportant un nouveau lot de défis et de récompenses pour tout le monde.<br><br>Nous avons également rééquilibré plusieurs objets plus anciens tombés en désuétude, il pourrait donc être utile de revoir vos anciennes configurations.<br><br>Comme toujours, merci de faire partie de cette communauté et pour vos retours continus. |
| DE | Staffel drei ist endlich da und bringt neue Herausforderungen und Belohnungen für alle mit sich.<br><br>Außerdem haben wir mehrere ältere Gegenstände neu ausbalanciert, die kaum noch genutzt wurden, es könnte sich also lohnen, eure alten Builds erneut anzuschauen.<br><br>Wie immer, danke, dass ihr Teil dieser Community seid und für euer anhaltendes Feedback. |
| ES | La temporada tres por fin ha llegado, trayendo nuevos desafíos y recompensas para que todos disfruten.<br><br>También hemos reequilibrado varios objetos antiguos que habían caído en desuso, así que podría valer la pena revisar tus antiguas construcciones.<br><br>Como siempre, gracias por formar parte de esta comunidad y por vuestros comentarios continuos. |

Verdict humain : _(à remplir)_

### 5. Dense en tokens techniques — mentions/URL/variables/emoji (`mixed_technical_and_linguistic`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | Hey \<@123456789012345678>! Your event {{event_name}} starts \<t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- use `!rsvp` in \<#234567890123456789>. |
| FR | Salut \<@123456789012345678> ! Votre événement {{event_name}} commence \<t:1735689600:F>. Détails : https://example.com/e/{{event_id}} -- utilisez `!rsvp` dans \<#234567890123456789>. |
| DE | Hallo \<@123456789012345678>! Dein Event {{event_name}} beginnt \<t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- benutze `!rsvp` in \<#234567890123456789>. |
| ES | ¡Hola \<@123456789012345678>! Tu evento {{event_name}} comienza \<t:1735689600:F>. Detalles: https://example.com/e/{{event_id}} -- usa `!rsvp` en \<#234567890123456789>. |

Point d'attention spécifique pour le relecteur : les tokens techniques (mentions Discord `<@...>`,
horodatage `<t:...>`, URL, variable `{{event_name}}`, commande `!rsvp`, salon `<#...>`) doivent
apparaître **identiques** dans la version cible — ce n'est pas un jugement de qualité de traduction
mais une vérification d'intégrité déjà couverte à 100 % côté machine (parseur/protecteur, REQ-MSG-
011/012/023) ; le relecteur humain juge uniquement la qualité linguistique du texte autour de ces
tokens.

Verdict humain : _(à remplir)_

### 6. Dense en tokens techniques — placeholders multiples (`multiple_placeholders_dense`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | Hey \<@123456789012345678> and \<@!234567890123456789>, your team {{team_name}} placed in \<#345678901234567890>! Ceremony \<t:1735689600:F>, details at https://example.com/results/{{season_id}}, react with \<a:party:456789012345678901> and run \</rsvp:789012345678901234>. |
| FR | Salut \<@123456789012345678> et \<@!234567890123456789>, votre équipe {{team_name}} s'est classée dans \<#345678901234567890> ! Cérémonie \<t:1735689600:F>, détails sur https://example.com/results/{{season_id}}, réagissez avec \<a:party:456789012345678901> et exécutez \</rsvp:789012345678901234>. |
| DE | Hallo \<@123456789012345678> und \<@!234567890123456789>, euer Team {{team_name}} hat sich in \<#345678901234567890> platziert! Zeremonie \<t:1735689600:F>, Details unter https://example.com/results/{{season_id}}, reagiert mit \<a:party:456789012345678901> und führt \</rsvp:789012345678901234> aus. |
| ES | Hola \<@123456789012345678> y \<@!234567890123456789>, ¡tu equipo {{team_name}} se clasificó en \<#345678901234567890>! Ceremonia \<t:1735689600:F>, detalles en https://example.com/results/{{season_id}}, reacciona con \<a:party:456789012345678901> y ejecuta \</rsvp:789012345678901234>. |

Verdict humain : _(à remplir)_

### 7. Terminologie Hero Wars — noms propres / acronymes (`terminology_names_acronyms`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | Congratulations to Hero Wars champion Alexandra Petrova (AKA "Lexi") for winning the NA regional finals -- her signature build, the DPS/support hybrid, was the MVP of the entire tournament. |
| FR | Félicitations à Alexandra Petrova, championne de Hero Wars (alias « Lexi »), pour sa victoire en finale régionale NA -- sa configuration signature, l'hybride DPS/support, a été le MVP de tout le tournoi. |
| DE | Herzlichen Glückwunsch an Hero-Wars-Champion Alexandra Petrova (alias „Lexi") zum Sieg im NA-Regionalfinale -- ihr Signature-Build, der DPS/Support-Hybrid, war der MVP des gesamten Turniers. |
| ES | Felicidades a la campeona de Hero Wars Alexandra Petrova (alias «Lexi») por ganar la final regional de NA -- su build característica, el híbrido DPS/soporte, fue el MVP de todo el torneo. |

Point d'attention spécifique : le relecteur juge si « Hero Wars », « DPS », « MVP », « NA » et le nom
propre « Alexandra Petrova » / surnom « Lexi » sont traités de façon appropriée pour un contexte de
communauté de jeu (généralement non traduits), sans jugement automatique — c'est exactement le rôle
prévu du glossaire (REQ-MSG-014/015) pour les termes dont la communauté attend une forme figée.

Verdict humain : _(à remplir)_

### 8. Style embed — titre (`embed_title_style`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | Season Three Championship Results |
| FR | Résultats du championnat de la saison trois |
| DE | Ergebnisse der Meisterschaft der dritten Staffel |
| ES | Resultados del campeonato de la tercera temporada |

Verdict humain : _(à remplir)_

### 9. Style embed — description (`embed_description_style`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | After three intense weeks of competition, sixteen teams battled down to a single champion. Below you will find the final standings, the most valuable players, and a link to the full match replays. |
| FR | Après trois semaines de compétition intense, seize équipes se sont affrontées jusqu'à un unique champion. Vous trouverez ci-dessous le classement final, les joueurs les plus précieux et un lien vers les rediffusions complètes des matchs. |
| DE | Nach drei intensiven Wochen des Wettbewerbs kämpften sich sechzehn Teams bis zu einem einzigen Champion durch. Unten findest du die Endtabelle, die wertvollsten Spieler und einen Link zu den vollständigen Match-Wiederholungen. |
| ES | Tras tres intensas semanas de competición, dieciséis equipos lucharon hasta dejar un único campeón. A continuación encontrarás la clasificación final, los jugadores más valiosos y un enlace a las repeticiones completas de las partidas. |

Verdict humain : _(à remplir)_

### 10. Style bouton — label court (`button_label_style`)

| Langue | Texte source (nativement rédigé) |
|---|---|
| EN | View Full Standings |
| FR | Voir le classement complet |
| DE | Vollständige Rangliste ansehen |
| ES | Ver clasificación completa |

Point d'attention spécifique : un label de bouton doit rester court et impératif/nominal dans la
langue cible, pas une phrase complète — le relecteur juge si la forme reste idiomatique pour un
composant UI, pas seulement grammaticalement correcte.

Verdict humain : _(à remplir)_

## Limitation connexe, honnêtement documentée

Une exécution en direct du provider `googletrans` réel dans le sandbox de cette passe a montré
qu'il renvoie actuellement un texte identique à l'entrée (écho) plutôt qu'une traduction, pour
toutes les directions testées — voir `docs/90_handoffs/STAGE_09_HANDOFF.md` § « État actuel » et
`docs/90_handoffs/evidence/stage09/discord-live-stage09-full-chain.json` (`notes`). Ce pack présente
donc les textes **source, nativement rédigés dans chaque langue** (issus du corpus de benchmark, qui
lui a mesuré une intégrité technique de 100 % lors de sa dernière exécution réseau réelle — voir
`translation-benchmark.json`), plutôt que des sorties `googletrans` fraîches captées dans ce sandbox
spécifique, pour que la revue humaine porte sur la qualité linguistique attendue du pipeline et ne
soit pas invalidée par cette fragilité externe ponctuelle du tiers.

## Prochaine étape

Quand un relecteur humain compétent dans une ou plusieurs des quatre langues est disponible, il
remplit directement les champs « Verdict humain » ci-dessus (oui/non par question, par paire de
langues jugée) et le statut de ce document passe de `PENDING_HUMAN_REVIEW` à son résultat réel —
jamais l'inverse, jamais un score inventé en attendant.
