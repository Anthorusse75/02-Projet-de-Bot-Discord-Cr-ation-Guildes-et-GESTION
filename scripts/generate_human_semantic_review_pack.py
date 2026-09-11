"""Stage 09 -- generates the HUMAN semantic-review dataset.

Makes REAL network calls to the live PRODUCTION translation provider --
did.translation.google_translate_rpc_adapter
.GoogleTranslateRpcCampaignTranslationProvider, the exact same construction
did.runtime.py itself uses -- through the exact production rendering path,
did.campaigns.rendering.render_field_text (FULL_MASKED_MESSAGE, the same
bounded integrity retry every real delivery gets, the same
validate_full_pipeline() fail-closed gate). This is deliberately NOT the
same code path as scripts/run_translation_benchmark.py: that script's
MeasurementRecord.translated_preview is truncated to 80 characters (correct
for its own purpose -- statistical evidence over many measurements, not
full-text human review); this script exists specifically to hand a HUMAN
reviewer the COMPLETE source and COMPLETE restored translated text for a
small, targeted, comparable sample -- see the module docstring in
did.campaigns.rendering for the full two-layer rendering design this reuses
unmodified.

This script NEVER assigns a semantic/fluency/terminology score, and NEVER
computes a human PASS/FAIL verdict. Every human-only field in its output is
left genuinely blank -- an AI-generated judgment represented as human
evidence would defeat the entire purpose of this pack. A competent human
reviewer fills those fields by hand, in whichever of the four languages
they are actually competent to judge; the evidence stays
`PENDING_HUMAN_REVIEW` until they do.

Selection: exactly 3 corpus items per source language (one each from the
`negation_and_pronouns`, `long_sentence`, and
`mixed_technical_and_linguistic` classes -- the same three classes for
every language, so results are comparable across directions), each
translated to the other 3 languages -- 4 languages x 3 classes x 3 targets
= 36 real translation calls, covering all 12 directed EN/FR/DE/ES pairs.

Usage (product owner, real network -- NEVER run from the implementation
sandbox):
    uv run python scripts/generate_human_semantic_review_pack.py \
        --corpus backend/tests/fixtures/translation_corpus/stage09_corpus.json \
        --out docs/90_handoffs/evidence/stage09/HUMAN_SEMANTIC_REVIEW.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from did.campaigns.rendering import render_field_text
from did.infrastructure.logging import EventId
from did.messaging.protector import IntegrityViolation
from did.messaging.translation_policy import FieldPath, TranslatableFieldKind, TranslationUnit
from did.translation.google_translate_rpc_adapter import (
    GoogleTranslateRpcCampaignTranslationProvider,
    count_transport_attempts,
)

#: The three content families this pack samples -- the exact corpus class
#: names, present for every one of the four languages (verified by
#: `_select_review_items` below, which fails loudly rather than silently
#: sampling fewer/different items if the committed corpus ever changes
#: shape). Deliberately the SAME three classes for every source language,
#: so a human reviewer's judgment is comparable across all 12 directions,
#: per the mission's own requirement.
REVIEW_FAMILIES: tuple[str, ...] = (
    "negation_and_pronouns",
    "long_sentence",
    "mixed_technical_and_linguistic",
)

#: Inert placeholders: render_field_text's campaign_id/guild_id are only
#: ever used to filter glossary entries, and this pack always calls it with
#: glossary_entries=() (a human semantic-review sample is deliberately the
#: RAW production translation pipeline, not glossary-modified output) --
#: fixed, non-random constants keep this script's own output reproducible
#: run to run for the same translation results.
_REVIEW_CAMPAIGN_ID = UUID("00000000-0000-0000-0000-000000000009")
_REVIEW_GUILD_ID = 990000109

_RENDERING_LOGGER_NAME = "did.campaigns.rendering"


@dataclass(frozen=True, slots=True)
class ReviewRow:
    row_id: int
    source_language: str
    target_language: str
    item_id: str
    item_class: str
    source_text: str
    restored_text: str | None
    protected_integrity_result: str  # "PASS" | "FAIL" | "ERROR"
    provider_error: str | None
    http_attempt_count: int
    integrity_retry_count: int


class _IntegrityRetryCounter(logging.Handler):
    """Counts real `translation.integrity.retry` events emitted by
    did.campaigns.rendering during exactly one render_field_text call --
    the same structured event Root cause 2's remediation already emits on
    every bounded-integrity-retry attempt (see did.campaigns.rendering's
    own module docstring). Attached/detached around a single call, never
    left registered, so concurrent or later calls are never miscounted."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "event_id", None) is EventId.TRANSLATION_INTEGRITY_RETRY:
            self.count += 1


def _select_review_items(corpus: dict[str, object]) -> dict[str, dict[str, dict[str, str]]]:
    """Returns ``{language: {family: item}}`` -- exactly one item per
    language per family. Fails loudly (never silently samples fewer/
    different items) if the committed corpus does not have exactly one
    match for every language/family combination."""
    items_by_language = corpus["items_by_language"]
    assert isinstance(items_by_language, dict)
    selected: dict[str, dict[str, dict[str, str]]] = {}
    for language, items in sorted(items_by_language.items()):
        by_family: dict[str, dict[str, str]] = {}
        for family in REVIEW_FAMILIES:
            matches = [item for item in items if item["class"] == family]
            if len(matches) != 1:
                raise ValueError(
                    f"expected exactly 1 corpus item for language={language!r} "
                    f"class={family!r}, found {len(matches)}"
                )
            by_family[family] = matches[0]
        selected[language] = by_family
    return selected


def build_directions(languages: list[str]) -> list[tuple[str, str]]:
    """Every ordered (source, target) pair of distinct languages --
    deliberately never a same-language pair (there is nothing to review
    about a translation into the same language)."""
    return [(src, dst) for src in languages for dst in languages if src != dst]


TranslateOne = Callable[[str, str, str], Awaitable[str]]
"""``(masked_text, source_language, target_language) -> translated_text`` --
the exact same contract ``did.campaigns.rendering``'s own
``TranslateMaskedText`` type expects (minus the two language kwargs, which
this pack always has fixed per row), injectable so deterministic tests can
supply a fake translator without ever touching the real adapter/network."""


async def translate_one_for_review(
    translate_one: TranslateOne,
    *,
    row_id: int,
    source_language: str,
    target_language: str,
    item: dict[str, str],
) -> ReviewRow:
    """Runs ONE real (or, in tests, injected-fake) translation through the
    exact production rendering path -- ``did.campaigns.rendering
    .render_field_text``, unmodified, with the SAME bounded integrity
    retry and the SAME ``validate_full_pipeline()`` fail-closed gate every
    real delivery gets. Returns the COMPLETE restored text (never
    truncated), plus the technical integrity metadata a human reviewer
    needs to interpret the result honestly (a `FAIL`/`ERROR` row is not
    something for a human to semantically score at all)."""
    content = item["content"]
    unit = TranslationUnit(FieldPath(TranslatableFieldKind.CONTENT), content)

    async def translate_masked_text(masked_text: str) -> str:
        return await translate_one(masked_text, source_language, target_language)

    retry_counter = _IntegrityRetryCounter()
    rendering_logger = logging.getLogger(_RENDERING_LOGGER_NAME)
    rendering_logger.addHandler(retry_counter)
    try:
        with count_transport_attempts() as get_transport_attempts:
            try:
                restored = await render_field_text(
                    unit,
                    target_language=target_language,
                    campaign_id=_REVIEW_CAMPAIGN_ID,
                    guild_id=_REVIEW_GUILD_ID,
                    template_variable_definitions={},
                    glossary_entries=(),
                    translate_masked_text=translate_masked_text,
                )
            except IntegrityViolation:
                return ReviewRow(
                    row_id=row_id,
                    source_language=source_language,
                    target_language=target_language,
                    item_id=item["id"],
                    item_class=item["class"],
                    source_text=content,
                    restored_text=None,
                    protected_integrity_result="FAIL",
                    provider_error=None,
                    http_attempt_count=get_transport_attempts(),
                    integrity_retry_count=retry_counter.count,
                )
            except Exception as exc:  # real provider/transport failure
                return ReviewRow(
                    row_id=row_id,
                    source_language=source_language,
                    target_language=target_language,
                    item_id=item["id"],
                    item_class=item["class"],
                    source_text=content,
                    restored_text=None,
                    protected_integrity_result="ERROR",
                    provider_error=str(exc),
                    http_attempt_count=get_transport_attempts(),
                    integrity_retry_count=retry_counter.count,
                )
            return ReviewRow(
                row_id=row_id,
                source_language=source_language,
                target_language=target_language,
                item_id=item["id"],
                item_class=item["class"],
                source_text=content,
                restored_text=restored,
                protected_integrity_result="PASS",
                provider_error=None,
                http_attempt_count=get_transport_attempts(),
                integrity_retry_count=retry_counter.count,
            )
    finally:
        rendering_logger.removeHandler(retry_counter)


async def build_review_rows(
    translate_one: TranslateOne, corpus: dict[str, object]
) -> list[ReviewRow]:
    """36 rows: every directed language pair x its source language's 3
    review-family items, translated sequentially (never concurrently --
    matches scripts/run_translation_benchmark.py's own approach; keeps a
    real run reproducible/debuggable and never risks cross-row circuit-
    breaker/rate-limit interaction)."""
    languages: list[str] = corpus["languages"]  # type: ignore[assignment]
    selected = _select_review_items(corpus)
    directions = build_directions(sorted(languages))

    rows: list[ReviewRow] = []
    row_id = 1
    for source_language, target_language in directions:
        for family in REVIEW_FAMILIES:
            item = selected[source_language][family]
            row = await translate_one_for_review(
                translate_one,
                row_id=row_id,
                source_language=source_language,
                target_language=target_language,
                item=item,
            )
            rows.append(row)
            row_id += 1
    return rows


def _escape_markdown_cell(text: str) -> str:
    """Markdown table cells cannot contain a literal newline or an
    unescaped pipe -- both appear in real corpus content (multi-paragraph
    items use `<br><br>`, never a raw newline, but this stays defensive)."""
    return text.replace("|", "\\|").replace("\n", "<br>")


def render_markdown(rows: list[ReviewRow], *, generated_at: str, sha: str) -> str:
    lines: list[str] = []
    lines.append("# Stage 09 -- Pack de revue sémantique humaine (36 échantillons réels)")
    lines.append("")
    lines.append("## Statut")
    lines.append("")
    lines.append(
        "**`PENDING_HUMAN_REVIEW`** -- aucune évaluation humaine n'a encore eu lieu sur ce pack. "
        "Tous les champs marqués « Verdict humain » ci-dessous sont **intentionnellement vides** : "
        "aucun score, aucune case n'a été pré-remplie par un outil automatique ou par l'agent "
        "d'implémentation, ce qui inclut explicitement Claude/Codex/tout autre assistant IA. Un "
        "relecteur humain compétent dans la langue cible jugée remplit directement ces champs -- "
        "voir la rubrique ci-dessous."
    )
    lines.append("")
    lines.append(
        f"Généré le `{generated_at}` contre le SHA `{sha}`, via le pipeline de production réel et "
        "inchangé (`did.campaigns.rendering.render_field_text`, "
        "`GoogleTranslateRpcCampaignTranslationProvider`, `FULL_MASKED_MESSAGE`, la même retry "
        "d'intégrité bornée que toute livraison réelle)."
    )
    lines.append("")
    lines.append("## Portée de l'échantillon")
    lines.append("")
    lines.append(
        "36 appels de traduction réels : les 4 langues source (EN/FR/DE/ES) x 3 classes de contenu "
        "identiques pour chaque langue (`negation_and_pronouns`, `long_sentence`, "
        "`mixed_technical_and_linguistic`) x 3 langues cible chacune = les 12 paires de langues "
        "dirigées complètes, avec les MÊMES trois classes partout, pour que les résultats restent "
        "comparables d'une direction à l'autre. Tout le texte source provient **verbatim** du "
        "corpus synthétique déjà committé "
        "(`backend/tests/fixtures/translation_corpus/stage09_corpus.json`) -- aucun contenu privé, "
        "aucun texte utilisateur réel."
    )
    lines.append("")
    lines.append("## Rubrique (à remplir par un humain compétent dans la langue cible jugée)")
    lines.append("")
    lines.append(
        "**Fidélité sémantique** : 2 = sens préservé ; 1 = défaut sémantique mineur, le sens reste "
        "compréhensible ; 0 = sens erroné/inversé/absent sur un point important."
    )
    lines.append(
        "**Naturel / fluidité** : 2 = texte naturel/acceptable dans la langue cible ; 1 = "
        "compréhensible mais maladroit ; 0 = sérieusement malformé/inutilisable."
    )
    lines.append(
        "**Terminologie / contexte** : 1 = contexte technique/du domaine préservé de façon "
        "acceptable ; 0 = défaut matériel de terminologie/contexte."
    )
    lines.append(
        "**Mistraduction bloquante** : OUI si un humain ne publierait pas ce texte de campagne "
        "traduit tel quel ; NON sinon."
    )
    lines.append(
        "Ces scores ne doivent JAMAIS être déduits mécaniquement d'un score BLEU/de similarité/"
        "d'un LLM, ni de l'égalité avec le texte source -- un résumé mécanique ne peut calculer "
        "des totaux qu'APRÈS que les champs humains ont réellement été remplis."
    )
    lines.append("")
    lines.append("## Échantillons")
    lines.append("")
    for row in rows:
        lines.append(
            f"### {row.row_id}. {row.source_language.upper()} → {row.target_language.upper()} "
            f"-- `{row.item_class}` (`{row.item_id}`)"
        )
        lines.append("")
        lines.append("| Champ | Valeur |")
        lines.append("|---|---|")
        lines.append(f"| Langue source | `{row.source_language}` |")
        lines.append(f"| Langue cible | `{row.target_language}` |")
        lines.append(f"| ID corpus | `{row.item_id}` |")
        lines.append(f"| Classe corpus | `{row.item_class}` |")
        lines.append(f"| Texte source complet | {_escape_markdown_cell(row.source_text)} |")
        restored_cell = (
            _escape_markdown_cell(row.restored_text)
            if row.restored_text is not None
            else "_(aucun -- voir intégrité/erreur ci-dessous)_"
        )
        lines.append(f"| Texte restauré complet | {restored_cell} |")
        lines.append(
            f"| Intégrité des placeholders protégés | `{row.protected_integrity_result}` |"
        )
        lines.append(f"| Erreur provider/transport | {row.provider_error or '_(aucune)_'} |")
        lines.append(f"| Nombre de tentatives HTTP réelles | {row.http_attempt_count} |")
        lines.append(f"| Nombre de reprises d'intégrité | {row.integrity_retry_count} |")
        lines.append("")
        lines.append("**Verdict humain** (à remplir -- vide par construction) :")
        lines.append("")
        lines.append(
            "| Fidélité sémantique (0-2) | Naturel (0-2) | Terminologie/contexte (0-1) | "
            "Mistraduction bloquante (OUI/NON) | Commentaires | Relecteur | Date | "
            "PASS/FAIL humain |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        lines.append("|  |  |  |  |  |  |  |  |")
        lines.append("")
    return "\n".join(lines) + "\n"


async def _default_translate_one(
    provider: GoogleTranslateRpcCampaignTranslationProvider,
    masked_text: str,
    source_language: str,
    target_language: str,
) -> str:
    result = await provider.translate(
        masked_text, source_language=source_language, target_language=target_language
    )
    return result.translated_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("backend/tests/fixtures/translation_corpus/stage09_corpus.json"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/90_handoffs/evidence/stage09/HUMAN_SEMANTIC_REVIEW.md"),
    )
    parser.add_argument(
        "--sha",
        type=str,
        default="unknown",
        help="Commit SHA to record in the generated pack's header.",
    )
    args = parser.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    provider = GoogleTranslateRpcCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=3)

    async def translate_one(masked_text: str, source_language: str, target_language: str) -> str:
        return await _default_translate_one(provider, masked_text, source_language, target_language)

    rows = asyncio.run(build_review_rows(translate_one, corpus))
    markdown = render_markdown(rows, generated_at=datetime.now(UTC).isoformat(), sha=args.sha)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(markdown, encoding="utf-8")

    total = len(rows)
    passed = sum(1 for r in rows if r.protected_integrity_result == "PASS")
    print(f"wrote {args.out} -- {total} rows, {passed}/{total} protected-integrity PASS")
    print(
        "Human review fields are intentionally blank -- status remains PENDING_HUMAN_REVIEW "
        "until a competent human reviewer fills them in."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
