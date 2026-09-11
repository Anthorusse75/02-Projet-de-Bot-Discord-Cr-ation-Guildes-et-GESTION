# Stage 09 -- Pack de revue sémantique humaine (36 échantillons réels)

## Statut

**`PRODUCT_OWNER_ACCEPTED_PROJECT_LEVEL`** -- le Product Owner **ACCEPTE explicitement le pack de 36 échantillons au niveau du projet** Stage 09 (voir « Acceptation Product Owner » ci-dessous). **Ceci n'est PAS une revue linguistique individuelle échantillon par échantillon, ni une certification linguistique professionnelle par relecteur natif** : le tableau « Verdict humain » à la fin de chaque échantillon reste **intentionnellement vide** -- aucun score de fidélité/naturel/terminologie n'a été assigné ligne par ligne, ni par un humain ni par un outil automatique, ce qui inclut explicitement Claude/Codex/tout autre assistant IA ; ces champs ne doivent jamais être fabriqués a posteriori. L'acceptation ci-dessous est une décision de projet globale sur le pack, distincte de cette rubrique ligne-par-ligne.

Généré le `2026-09-11T12:42:42.192877+00:00` contre le SHA `6acfcc2460850e0507c71be74a51584f150ded18`, via le pipeline de production réel et inchangé (`did.campaigns.rendering.render_field_text`, `GoogleTranslateRpcCampaignTranslationProvider`, `FULL_MASKED_MESSAGE`, la même retry d'intégrité bornée que toute livraison réelle).

## Acceptation Product Owner (niveau projet, PAS une certification linguistique professionnelle)

**Décision : ACCEPTÉ.** Le Product Owner accepte les 36 traductions générées ci-dessous pour la clôture de Stage 09. Cette décision est une **acceptation de projet** (le contenu est jugé publiable en pratique), distincte d'une certification linguistique professionnelle par relecteur natif ligne par ligne -- cette dernière n'a pas eu lieu et le tableau « Verdict humain » de chaque échantillon reste vide par construction, comme documenté ci-dessus.

Évidence technique préservée telle quelle (jamais fabriquée, jamais réécrite) : **36/36 intégrité des placeholders protégés `PASS`**, **0 erreur provider/transport sur les 36 appels**, **36/36 en une seule tentative HTTP réelle**, **0 reprise d'intégrité** -- via le pipeline de production réel inchangé (`did.campaigns.rendering.render_field_text`, `GoogleTranslateRpcCampaignTranslationProvider`, `FULL_MASKED_MESSAGE`), généré contre le SHA `6acfcc2460850e0507c71be74a51584f150ded18` (le correctif Unicode de la Root cause 9 est donc inclus dans ce run -- tous les échantillons `mixed_technical_and_linguistic` montrent un espacement de frontière correct).

Une formulation occasionnellement moins idiomatique/moins naturelle qu'un texte rédigé nativement est acceptée comme **non bloquante** pour cette clôture de projet, tant que le sens reste compréhensible et qu'aucune mistraduction ne change le sens du message. Observation spécifique du Product Owner : pour la direction EN→FR, l'échantillon 16 (`negation_and_pronouns`) et l'échantillon 17 (`long_sentence`) sont compréhensibles mais moins naturels qu'une formulation française native ; l'échantillon 18 (`mixed_technical_and_linguistic`) est jugé satisfaisant. Aucun de ces trois échantillons n'a été jugé comme une mistraduction bloquante.

**Conséquence pour Stage 09** : la qualité de traduction Stage 09 est considérée acceptée et ne doit plus rester bloquée sur une revue linguistique supplémentaire. Ceci clôture l'écart d'évidence humaine documenté dans `docs/90_handoffs/STAGE_09_HANDOFF.md` (Root cause 8/9 et « Limitations honnêtement externes restantes ») -- voir ce document pour la mise à jour correspondante de l'état courant de Stage 09.

## Portée de l'échantillon

36 appels de traduction réels : les 4 langues source (EN/FR/DE/ES) x 3 classes de contenu identiques pour chaque langue (`negation_and_pronouns`, `long_sentence`, `mixed_technical_and_linguistic`) x 3 langues cible chacune = les 12 paires de langues dirigées complètes, avec les MÊMES trois classes partout, pour que les résultats restent comparables d'une direction à l'autre. Tout le texte source provient **verbatim** du corpus synthétique déjà committé (`backend/tests/fixtures/translation_corpus/stage09_corpus.json`) -- aucun contenu privé, aucun texte utilisateur réel.

## Rubrique (à remplir par un humain compétent dans la langue cible jugée)

**Fidélité sémantique** : 2 = sens préservé ; 1 = défaut sémantique mineur, le sens reste compréhensible ; 0 = sens erroné/inversé/absent sur un point important.
**Naturel / fluidité** : 2 = texte naturel/acceptable dans la langue cible ; 1 = compréhensible mais maladroit ; 0 = sérieusement malformé/inutilisable.
**Terminologie / contexte** : 1 = contexte technique/du domaine préservé de façon acceptable ; 0 = défaut matériel de terminologie/contexte.
**Mistraduction bloquante** : OUI si un humain ne publierait pas ce texte de campagne traduit tel quel ; NON sinon.
Ces scores ne doivent JAMAIS être déduits mécaniquement d'un score BLEU/de similarité/d'un LLM, ni de l'égalité avec le texte source -- un résumé mécanique ne peut calculer des totaux qu'APRÈS que les champs humains ont réellement été remplis.

## Échantillons

### 1. DE → EN -- `negation_and_pronouns` (`de-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `en` |
| ID corpus | `de-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Sie sagte, dass sie selbst nicht an der Veranstaltung teilnehmen werde, bat uns aber, alle daran zu erinnern, dass sie trotzdem ohne sie stattfindet. |
| Texte restauré complet | She said that she would not be attending the event herself, but asked us to remind everyone that it would still take place without her. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 2. DE → EN -- `long_sentence` (`de-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `en` |
| ID corpus | `de-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Obwohl das Winterupdate zahlreiche Balance-Änderungen für fast jede Klasse mit sich brachte, war die Reaktion der Community überwältigend positiv, da die meisten Spieler das neue Tempo als deutlich lohnender empfinden als zuvor. |
| Texte restauré complet | Although the Winter Update brought numerous balance changes to almost every class, the response from the community has been overwhelmingly positive, with most players finding the new pace significantly more rewarding than before. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 3. DE → EN -- `mixed_technical_and_linguistic` (`de-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `en` |
| ID corpus | `de-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Hallo <@123456789012345678>! Dein Event {{event_name}} beginnt <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- benutze `!rsvp` in <#234567890123456789>. |
| Texte restauré complet | Hello <@123456789012345678>! Your event {{event_name}} begins <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- use `!rsvp` in <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 4. DE → ES -- `negation_and_pronouns` (`de-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `es` |
| ID corpus | `de-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Sie sagte, dass sie selbst nicht an der Veranstaltung teilnehmen werde, bat uns aber, alle daran zu erinnern, dass sie trotzdem ohne sie stattfindet. |
| Texte restauré complet | Ella dijo que ella misma no asistiría al evento, pero nos pidió que recordáramos a todos que todavía se llevaría a cabo sin ella. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 5. DE → ES -- `long_sentence` (`de-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `es` |
| ID corpus | `de-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Obwohl das Winterupdate zahlreiche Balance-Änderungen für fast jede Klasse mit sich brachte, war die Reaktion der Community überwältigend positiv, da die meisten Spieler das neue Tempo als deutlich lohnender empfinden als zuvor. |
| Texte restauré complet | Aunque la Actualización de Invierno trajo numerosos cambios de equilibrio a casi todas las clases, la respuesta de la comunidad ha sido abrumadoramente positiva, y la mayoría de los jugadores encuentran el nuevo ritmo significativamente más gratificante que antes. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 6. DE → ES -- `mixed_technical_and_linguistic` (`de-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `es` |
| ID corpus | `de-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Hallo <@123456789012345678>! Dein Event {{event_name}} beginnt <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- benutze `!rsvp` in <#234567890123456789>. |
| Texte restauré complet | ¡Hola <@123456789012345678>! Su evento {{event_name}} comienza <t:1735689600:F>. Detalles: https://example.com/e/{{event_id}} - use `!rsvp` en <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 7. DE → FR -- `negation_and_pronouns` (`de-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `fr` |
| ID corpus | `de-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Sie sagte, dass sie selbst nicht an der Veranstaltung teilnehmen werde, bat uns aber, alle daran zu erinnern, dass sie trotzdem ohne sie stattfindet. |
| Texte restauré complet | Elle a déclaré qu'elle n'assisterait pas elle-même à l'événement, mais nous a demandé de rappeler à tous que l'événement aurait quand même lieu sans elle. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 8. DE → FR -- `long_sentence` (`de-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `fr` |
| ID corpus | `de-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Obwohl das Winterupdate zahlreiche Balance-Änderungen für fast jede Klasse mit sich brachte, war die Reaktion der Community überwältigend positiv, da die meisten Spieler das neue Tempo als deutlich lohnender empfinden als zuvor. |
| Texte restauré complet | Bien que la mise à jour d'hiver ait apporté de nombreux changements d'équilibrage à presque toutes les classes, la réponse de la communauté a été extrêmement positive, la plupart des joueurs trouvant le nouveau rythme beaucoup plus gratifiant qu'auparavant. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 9. DE → FR -- `mixed_technical_and_linguistic` (`de-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `de` |
| Langue cible | `fr` |
| ID corpus | `de-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Hallo <@123456789012345678>! Dein Event {{event_name}} beginnt <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- benutze `!rsvp` in <#234567890123456789>. |
| Texte restauré complet | Bonjour <@123456789012345678> ! Votre événement {{event_name}} commence par <t:1735689600:F>. Détails : https://example.com/e/{{event_id}} -- utilisez `!rsvp` dans <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 10. EN → DE -- `negation_and_pronouns` (`en-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `de` |
| ID corpus | `en-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | She said she would not be attending the event herself, but she asked us to remind everyone that it is still happening without her. |
| Texte restauré complet | Sie sagte, sie würde nicht selbst an der Veranstaltung teilnehmen, bat uns jedoch, alle daran zu erinnern, dass die Veranstaltung immer noch ohne sie stattfindet. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 11. EN → DE -- `long_sentence` (`en-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `de` |
| ID corpus | `en-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Even though the winter update introduced a large number of balance changes across nearly every class, the community response has been overwhelmingly positive, with most players agreeing that the new pacing feels far more rewarding than before. |
| Texte restauré complet | Auch wenn das Winter-Update eine große Anzahl an Balance-Änderungen in fast allen Klassen mit sich brachte, war die Reaktion der Community überwältigend positiv, und die meisten Spieler waren sich einig, dass sich das neue Tempo weitaus lohnender anfühlt als zuvor. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 12. EN → DE -- `mixed_technical_and_linguistic` (`en-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `de` |
| ID corpus | `en-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Hey <@123456789012345678>! Your event {{event_name}} starts <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- use `!rsvp` in <#234567890123456789>. |
| Texte restauré complet | Hallo <@123456789012345678>! Ihre Veranstaltung {{event_name}} beginnt mit <t:1735689600:F>. Details: https://example.com/e/{{event_id}} – verwenden Sie `!rsvp` in <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 13. EN → ES -- `negation_and_pronouns` (`en-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `es` |
| ID corpus | `en-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | She said she would not be attending the event herself, but she asked us to remind everyone that it is still happening without her. |
| Texte restauré complet | Ella dijo que ella misma no asistiría al evento, pero nos pidió que recordáramos a todos que esto todavía sucederá sin ella. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 14. EN → ES -- `long_sentence` (`en-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `es` |
| ID corpus | `en-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Even though the winter update introduced a large number of balance changes across nearly every class, the community response has been overwhelmingly positive, with most players agreeing that the new pacing feels far more rewarding than before. |
| Texte restauré complet | Aunque la actualización de invierno introdujo una gran cantidad de cambios de equilibrio en casi todas las clases, la respuesta de la comunidad ha sido abrumadoramente positiva, y la mayoría de los jugadores están de acuerdo en que el nuevo ritmo es mucho más gratificante que antes. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 15. EN → ES -- `mixed_technical_and_linguistic` (`en-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `es` |
| ID corpus | `en-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Hey <@123456789012345678>! Your event {{event_name}} starts <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- use `!rsvp` in <#234567890123456789>. |
| Texte restauré complet | Hola <@123456789012345678>! Su evento {{event_name}} inicia <t:1735689600:F>. Detalles: https://example.com/e/{{event_id}} - use `!rsvp` en <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 16. EN → FR -- `negation_and_pronouns` (`en-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `fr` |
| ID corpus | `en-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | She said she would not be attending the event herself, but she asked us to remind everyone that it is still happening without her. |
| Texte restauré complet | Elle a dit qu’elle n’assisterait pas elle-même à l’événement, mais elle nous a demandé de rappeler à tout le monde que cela se produit toujours sans elle. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 17. EN → FR -- `long_sentence` (`en-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `fr` |
| ID corpus | `en-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Even though the winter update introduced a large number of balance changes across nearly every class, the community response has been overwhelmingly positive, with most players agreeing that the new pacing feels far more rewarding than before. |
| Texte restauré complet | Même si la mise à jour hivernale a introduit un grand nombre de changements d'équilibrage dans presque toutes les classes, la réponse de la communauté a été extrêmement positive, la plupart des joueurs s'accordant à dire que le nouveau rythme semble bien plus gratifiant qu'auparavant. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 18. EN → FR -- `mixed_technical_and_linguistic` (`en-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `en` |
| Langue cible | `fr` |
| ID corpus | `en-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Hey <@123456789012345678>! Your event {{event_name}} starts <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- use `!rsvp` in <#234567890123456789>. |
| Texte restauré complet | Salut <@123456789012345678> ! Votre événement {{event_name}} démarre <t:1735689600:F>. Détails : https://example.com/e/{{event_id}} -- utilisez `!rsvp` dans <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 19. ES → DE -- `negation_and_pronouns` (`es-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `de` |
| ID corpus | `es-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Ella dijo que no asistiría personalmente al evento, pero nos pidió que le recordáramos a todos que de todos modos se llevará a cabo sin ella. |
| Texte restauré complet | Sie sagte, sie würde nicht persönlich an der Veranstaltung teilnehmen, bat uns aber, alle daran zu erinnern, dass die Veranstaltung ohne sie stattfinden würde. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 20. ES → DE -- `long_sentence` (`es-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `de` |
| ID corpus | `es-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Aunque la actualización de invierno introdujo una gran cantidad de cambios de equilibrio en casi todas las clases, la respuesta de la comunidad ha sido abrumadoramente positiva, y la mayoría de los jugadores coincide en que el nuevo ritmo resulta mucho más gratificante que antes. |
| Texte restauré complet | Obwohl das Winter-Update eine Reihe von Balanceänderungen für fast jede Klasse mit sich brachte, war die Reaktion der Community überwältigend positiv, und die meisten Spieler waren sich einig, dass das neue Tempo viel lohnender ist als zuvor. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 21. ES → DE -- `mixed_technical_and_linguistic` (`es-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `de` |
| ID corpus | `es-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | ¡Hola <@123456789012345678>! Tu evento {{event_name}} comienza <t:1735689600:F>. Detalles: https://example.com/e/{{event_id}} -- usa `!rsvp` en <#234567890123456789>. |
| Texte restauré complet | Hallo <@123456789012345678>! Ihre Veranstaltung {{event_name}} startet <t:1735689600:F>. Details: https://example.com/e/{{event_id}} – verwenden Sie `!rsvp` in <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 22. ES → EN -- `negation_and_pronouns` (`es-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `en` |
| ID corpus | `es-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Ella dijo que no asistiría personalmente al evento, pero nos pidió que le recordáramos a todos que de todos modos se llevará a cabo sin ella. |
| Texte restauré complet | She said she wouldn't be attending the event in person, but asked us to remind everyone that it will be taking place without her anyway. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 23. ES → EN -- `long_sentence` (`es-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `en` |
| ID corpus | `es-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Aunque la actualización de invierno introdujo una gran cantidad de cambios de equilibrio en casi todas las clases, la respuesta de la comunidad ha sido abrumadoramente positiva, y la mayoría de los jugadores coincide en que el nuevo ritmo resulta mucho más gratificante que antes. |
| Texte restauré complet | Although the Winter Update introduced a host of balance changes to almost every class, the community response has been overwhelmingly positive, with most players agreeing that the new pace is much more rewarding than before. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 24. ES → EN -- `mixed_technical_and_linguistic` (`es-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `en` |
| ID corpus | `es-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | ¡Hola <@123456789012345678>! Tu evento {{event_name}} comienza <t:1735689600:F>. Detalles: https://example.com/e/{{event_id}} -- usa `!rsvp` en <#234567890123456789>. |
| Texte restauré complet | Hello <@123456789012345678>! Your event {{event_name}} starts <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- use `!rsvp` in <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 25. ES → FR -- `negation_and_pronouns` (`es-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `fr` |
| ID corpus | `es-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Ella dijo que no asistiría personalmente al evento, pero nos pidió que le recordáramos a todos que de todos modos se llevará a cabo sin ella. |
| Texte restauré complet | Elle a dit qu'elle n'assisterait pas à l'événement en personne, mais nous a demandé de rappeler à tout le monde que l'événement aurait lieu sans elle de toute façon. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 26. ES → FR -- `long_sentence` (`es-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `fr` |
| ID corpus | `es-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Aunque la actualización de invierno introdujo una gran cantidad de cambios de equilibrio en casi todas las clases, la respuesta de la comunidad ha sido abrumadoramente positiva, y la mayoría de los jugadores coincide en que el nuevo ritmo resulta mucho más gratificante que antes. |
| Texte restauré complet | Bien que la mise à jour d'hiver ait introduit de nombreux changements d'équilibrage dans presque toutes les classes, la réponse de la communauté a été extrêmement positive, la plupart des joueurs s'accordant sur le fait que le nouveau rythme est beaucoup plus gratifiant qu'auparavant. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 27. ES → FR -- `mixed_technical_and_linguistic` (`es-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `es` |
| Langue cible | `fr` |
| ID corpus | `es-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | ¡Hola <@123456789012345678>! Tu evento {{event_name}} comienza <t:1735689600:F>. Detalles: https://example.com/e/{{event_id}} -- usa `!rsvp` en <#234567890123456789>. |
| Texte restauré complet | Bonjour <@123456789012345678> ! Votre événement {{event_name}} démarre <t:1735689600:F>. Détails : https://example.com/e/{{event_id}} -- utilisez `!rsvp` dans <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 28. FR → DE -- `negation_and_pronouns` (`fr-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `de` |
| ID corpus | `fr-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Elle a dit qu'elle n'assisterait pas elle-même à l'événement, mais elle nous a demandé de rappeler à tout le monde qu'il aura quand même lieu sans elle. |
| Texte restauré complet | Sie sagte, dass sie selbst nicht an der Veranstaltung teilnehmen würde, bat uns aber, alle daran zu erinnern, dass die Veranstaltung trotzdem ohne sie stattfinden wird. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 29. FR → DE -- `long_sentence` (`fr-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `de` |
| ID corpus | `fr-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Bien que la mise à jour d'hiver ait introduit un grand nombre de changements d'équilibrage pour presque toutes les classes, la réaction de la communauté a été extrêmement positive, la plupart des joueurs estimant que le nouveau rythme est bien plus gratifiant qu'auparavant. |
| Texte restauré complet | Obwohl das Winter-Update eine große Anzahl an Balanceänderungen für fast jede Klasse einführte, war die Reaktion der Community überwältigend positiv, und die meisten Spieler fanden den neuen Rhythmus viel lohnender als zuvor. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 30. FR → DE -- `mixed_technical_and_linguistic` (`fr-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `de` |
| ID corpus | `fr-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Salut <@123456789012345678> ! Votre événement {{event_name}} commence <t:1735689600:F>. Détails : https://example.com/e/{{event_id}} -- utilisez `!rsvp` dans <#234567890123456789>. |
| Texte restauré complet | Hallo <@123456789012345678>! Ihre Veranstaltung {{event_name}} beginnt mit <t:1735689600:F>. Details: https://example.com/e/{{event_id}} – verwenden Sie `!rsvp` in <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 31. FR → EN -- `negation_and_pronouns` (`fr-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `en` |
| ID corpus | `fr-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Elle a dit qu'elle n'assisterait pas elle-même à l'événement, mais elle nous a demandé de rappeler à tout le monde qu'il aura quand même lieu sans elle. |
| Texte restauré complet | She said she wouldn't be attending the event herself, but she asked us to remind everyone that it will still take place without her. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 32. FR → EN -- `long_sentence` (`fr-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `en` |
| ID corpus | `fr-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Bien que la mise à jour d'hiver ait introduit un grand nombre de changements d'équilibrage pour presque toutes les classes, la réaction de la communauté a été extrêmement positive, la plupart des joueurs estimant que le nouveau rythme est bien plus gratifiant qu'auparavant. |
| Texte restauré complet | Although the Winter Update introduced a large number of balance changes for almost every class, community reaction has been overwhelmingly positive, with most players finding the new rhythm to be much more rewarding than before. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 33. FR → EN -- `mixed_technical_and_linguistic` (`fr-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `en` |
| ID corpus | `fr-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Salut <@123456789012345678> ! Votre événement {{event_name}} commence <t:1735689600:F>. Détails : https://example.com/e/{{event_id}} -- utilisez `!rsvp` dans <#234567890123456789>. |
| Texte restauré complet | Hi <@123456789012345678>! Your event {{event_name}} begins <t:1735689600:F>. Details: https://example.com/e/{{event_id}} -- use `!rsvp` in <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 34. FR → ES -- `negation_and_pronouns` (`fr-negation-pronouns`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `es` |
| ID corpus | `fr-negation-pronouns` |
| Classe corpus | `negation_and_pronouns` |
| Texte source complet | Elle a dit qu'elle n'assisterait pas elle-même à l'événement, mais elle nous a demandé de rappeler à tout le monde qu'il aura quand même lieu sans elle. |
| Texte restauré complet | Ella dijo que ella misma no asistiría al evento, pero nos pidió que recordáramos a todos que todavía se llevará a cabo sin ella. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 35. FR → ES -- `long_sentence` (`fr-long-sentence`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `es` |
| ID corpus | `fr-long-sentence` |
| Classe corpus | `long_sentence` |
| Texte source complet | Bien que la mise à jour d'hiver ait introduit un grand nombre de changements d'équilibrage pour presque toutes les classes, la réaction de la communauté a été extrêmement positive, la plupart des joueurs estimant que le nouveau rythme est bien plus gratifiant qu'auparavant. |
| Texte restauré complet | Aunque la Actualización de Invierno introdujo una gran cantidad de cambios de equilibrio para casi todas las clases, la reacción de la comunidad ha sido abrumadoramente positiva, y la mayoría de los jugadores consideran que el nuevo ritmo es mucho más gratificante que antes. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

### 36. FR → ES -- `mixed_technical_and_linguistic` (`fr-mixed-everything`)

| Champ | Valeur |
|---|---|
| Langue source | `fr` |
| Langue cible | `es` |
| ID corpus | `fr-mixed-everything` |
| Classe corpus | `mixed_technical_and_linguistic` |
| Texte source complet | Salut <@123456789012345678> ! Votre événement {{event_name}} commence <t:1735689600:F>. Détails : https://example.com/e/{{event_id}} -- utilisez `!rsvp` dans <#234567890123456789>. |
| Texte restauré complet | Hola <@123456789012345678>! Su evento {{event_name}} comienza <t:1735689600:F>. Detalles: https://example.com/e/{{event_id}} - use `!rsvp` en <#234567890123456789>. |
| Intégrité des placeholders protégés | `PASS` |
| Erreur provider/transport | _(aucune)_ |
| Nombre de tentatives HTTP réelles | 1 |
| Nombre de reprises d'intégrité | 0 |

**Verdict humain** (à remplir -- vide par construction) :

| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | PASS/FAIL humain |
|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  |  |  |

