"""Stage 09 WP10: real googletrans benchmark over the committed corpus.

Makes REAL network calls to the live googletrans endpoint. Never substitutes
mocked/fixture translations for the measurements below -- if the network or
provider is unavailable, this script records an honest BLOCKED/UNVERIFIED
result rather than fabricating numbers.

Usage:
    uv run python scripts/run_translation_benchmark.py \
        --corpus backend/tests/fixtures/translation_corpus/stage09_corpus.json \
        --out artifacts/test-evidence/stage-09/translation-benchmark/report.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from did.messaging.parser import TextNode, parse
from did.messaging.protector import IntegrityViolation, protect, validate_and_restore
from did.translation.googletrans_adapter import GoogletransCampaignTranslationProvider
from did.translation.segmentation import (
    SegmentationStrategy,
    count_text_nodes,
    segment_count,
    translate_masked_text,
    translate_nodes_naively,
)

try:
    import googletrans

    GOOGLETRANS_VERSION = googletrans.__version__
except Exception:  # pragma: no cover - defensive, version reporting only
    GOOGLETRANS_VERSION = "unknown"


@dataclass
class MeasurementRecord:
    item_id: str
    item_class: str
    strategy: str
    source_language: str
    target_language: str
    segment_count: int
    latency_seconds: float | None
    protected_integrity_ok: bool | None
    error: str | None
    translated_preview: str | None  # first 80 chars only, for manual spot-check


async def _run_one(
    provider: GoogletransCampaignTranslationProvider,
    item: dict[str, str],
    strategy: SegmentationStrategy,
    source_language: str,
    target_language: str,
) -> MeasurementRecord:
    content = item["content"]
    nodes = parse(content)
    protection = protect(nodes)

    async def translate_segment(segment: str) -> str:
        result = await provider.translate(
            segment, source_language=source_language, target_language=target_language
        )
        return result.translated_text

    started = time.perf_counter()
    try:
        if strategy is SegmentationStrategy.NAIVE_PER_TEXT_NODE:
            protected_positions = [i for i, n in enumerate(nodes) if not isinstance(n, TextNode)]
            placeholders = dict(
                zip(
                    protected_positions,
                    [fp.placeholder for fp in protection.fingerprints],
                    strict=True,
                )
            )
            translated_masked = await translate_nodes_naively(
                nodes, placeholders, translate_segment
            )
            n_segments = count_text_nodes(nodes)
        else:
            translated_masked = await translate_masked_text(
                protection.masked_text, strategy, translate_segment
            )
            n_segments = segment_count(protection.masked_text, strategy)
        latency = time.perf_counter() - started

        try:
            restored = validate_and_restore(translated_masked, protection)
            integrity_ok = True
        except IntegrityViolation as exc:
            restored = f"<INTEGRITY_VIOLATION: {exc}>"
            integrity_ok = False

        return MeasurementRecord(
            item_id=item["id"],
            item_class=item["class"],
            strategy=strategy.value,
            source_language=source_language,
            target_language=target_language,
            segment_count=n_segments,
            latency_seconds=round(latency, 3),
            protected_integrity_ok=integrity_ok,
            error=None,
            translated_preview=restored[:80],
        )
    except Exception as exc:
        latency = time.perf_counter() - started
        return MeasurementRecord(
            item_id=item["id"],
            item_class=item["class"],
            strategy=strategy.value,
            source_language=source_language,
            target_language=target_language,
            segment_count=0,
            latency_seconds=round(latency, 3),
            protected_integrity_ok=None,
            error=str(exc),
            translated_preview=None,
        )


async def run_benchmark(corpus: dict[str, Any]) -> dict[str, object]:
    source_language = corpus["source_language"]
    target_languages = corpus["target_languages"]
    items = corpus["items"]
    strategies = [
        SegmentationStrategy.FULL_MASKED_MESSAGE,
        SegmentationStrategy.PARAGRAPH_GROUPING,
        SegmentationStrategy.SENTENCE_GROUPING,
        SegmentationStrategy.NAIVE_PER_TEXT_NODE,
    ]
    provider = GoogletransCampaignTranslationProvider(timeout_seconds=15.0, max_attempts=3)

    records: list[MeasurementRecord] = []
    for target_language in target_languages:
        for strategy in strategies:
            for item in items:
                record = await _run_one(provider, item, strategy, source_language, target_language)
                records.append(record)

    return {
        "meta": {
            "generated_at": datetime.now(UTC).isoformat(),
            "googletrans_version": GOOGLETRANS_VERSION,
            "corpus_version": corpus.get("version"),
            "source_language": source_language,
            "target_languages": target_languages,
            "strategies": [s.value for s in strategies],
            "item_count": len(items),
        },
        "records": [asdict(r) for r in records],
        "summary": _summarize(records),
    }


def _summarize(records: list[MeasurementRecord]) -> dict[str, object]:
    by_strategy: dict[str, dict[str, Any]] = {}
    for record in records:
        bucket = by_strategy.setdefault(
            record.strategy,
            {
                "total": 0,
                "errors": 0,
                "integrity_ok": 0,
                "integrity_checked": 0,
                "latency_sum": 0.0,
                "latency_count": 0,
            },
        )
        bucket["total"] = int(bucket["total"]) + 1
        if record.error is not None:
            bucket["errors"] = int(bucket["errors"]) + 1
            continue
        if record.protected_integrity_ok is not None:
            bucket["integrity_checked"] = int(bucket["integrity_checked"]) + 1
            if record.protected_integrity_ok:
                bucket["integrity_ok"] = int(bucket["integrity_ok"]) + 1
        if record.latency_seconds is not None:
            bucket["latency_sum"] = float(bucket["latency_sum"]) + record.latency_seconds
            bucket["latency_count"] = int(bucket["latency_count"]) + 1

    summary: dict[str, Any] = {}
    for strategy, bucket in by_strategy.items():
        checked = int(bucket["integrity_checked"])
        integrity_rate = (int(bucket["integrity_ok"]) / checked) if checked else None
        latency_count = int(bucket["latency_count"])
        avg_latency = float(bucket["latency_sum"]) / latency_count if latency_count else None
        summary[strategy] = {
            "total_calls": bucket["total"],
            "errors": bucket["errors"],
            "protected_integrity_rate": integrity_rate,
            "average_latency_seconds": round(avg_latency, 3) if avg_latency else None,
        }
    return summary


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
        default=Path("artifacts/test-evidence/stage-09/translation-benchmark/report.json"),
    )
    args = parser.parse_args()

    import asyncio

    try:
        corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
        report = asyncio.run(run_benchmark(corpus))
    except Exception as exc:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": str(exc),
                    "generated_at": datetime.now(UTC).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.out}")
    print(json.dumps(report["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
