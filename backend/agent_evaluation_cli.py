"""CLI for bounded synthetic evaluation or scoring complete prediction files."""

import argparse
import asyncio
from pathlib import Path

from backend.agent_evaluation import read_cases, read_predictions, report_json, run_cases
from backend.config import Settings
from backend.infrastructure.meta_provider import MetaModelProvider, MockMetaProvider


async def run(args):
    cases = read_cases(args.cases)
    if args.predictions:
        print(report_json(cases, read_predictions(args.predictions)))
        return
    # Refuse overwrites before any paid call. Stream rows so interrupted runs are inspectable.
    with args.output.open("x", encoding="utf-8") as output:
        provider = MetaModelProvider(Settings(mock_llm=False)) if args.live else MockMetaProvider()
        predictions = []
        try:
            async for row in run_cases(
                cases, provider, mode="live" if args.live else "mock", max_calls=args.max_calls or 0
            ):
                output.write(row.model_dump_json() + "\n")
                output.flush()
                predictions.append(row)
        finally:
            if args.live:
                await provider.close()
    print(report_json(cases, predictions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output", type=Path, help="new JSONL file; never overwritten")
    destination.add_argument(
        "--predictions", type=Path, help="score existing predictions without API calls"
    )
    parser.add_argument("--live", action="store_true", help="explicit opt-in to paid Meta calls")
    parser.add_argument("--max-calls", type=int, help="required for live mode; 0..100, no retries")
    args = parser.parse_args()
    if args.live and (args.max_calls is None or args.predictions):
        parser.error("--live requires --output and an explicit --max-calls")
    if args.max_calls is not None and (not args.live or not 0 <= args.max_calls <= 100):
        parser.error("--max-calls requires --live and a value between 0 and 100")
    try:
        asyncio.run(run(args))
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Evaluation failed ({type(exc).__name__}); check input and output paths.\n")


if __name__ == "__main__":
    main()
