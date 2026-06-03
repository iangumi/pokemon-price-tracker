from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote, quote_plus

from .card_parser import parse_card_identity
from .config import DEFAULT_CONFIG, load_config, save_config
from .http import fetch_text
from .models import Product, utc_now
from .scrapers import extract_store_products
from .infrastructure.scrapers import snkrdunk_search_url
from .v2.config import load_validated_config
from .v2.models import ConfigError
from .v2.pipeline import PipelineOptions, RunPipeline
from .v2.storage import TraceStore


def search_term_from_title(title: str) -> str:
    return parse_card_identity(title).tokopedia_query() or title


def cmd_run(args: argparse.Namespace) -> int:
    options = PipelineOptions(
        config_path=Path(args.config),
        limit=args.limit,
        min_price_idr=args.min_price_idr,
        ai_summary=args.ai_summary,
        debug=args.debug,
        detect_sold=not args.no_sold_detection,
        fetch_backend=args.fetch_backend,
    )
    result = RunPipeline(options).run()
    print(f"Run {result.run_id} complete. Report: reports/latest.md")
    print(f"Trace: python3 -m pokemon_price_scheduler inspect-run {result.run_id}")
    return 0


def cmd_validate_config(args: argparse.Namespace) -> int:
    try:
        settings, products = load_validated_config(Path(args.config))
    except ConfigError as exc:
        print(f"Invalid config: {exc}")
        return 1
    print(f"Config OK: {len(products)} product(s), {len(settings)} setting(s).")
    return 0


def cmd_inspect_run(args: argparse.Namespace) -> int:
    store = TraceStore(Path(args.db))
    run_id = args.run_id or store.latest_run_id()
    if run_id is None:
        print("No runs found.")
        return 1
    payload = store.inspect_run(run_id)
    if not payload:
        print(f"Run not found: {run_id}")
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_migrate_snkrdunk_urls(args: argparse.Namespace) -> int:
    path = Path(args.config)
    payload = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for product in payload.get("products", []):
        title = str(product.get("title", ""))
        keyword = parse_card_identity(title).snkrdunk_query() or title
        for source in product.get("sources", []):
            if source.get("kind") != "snkrdunk_search":
                continue
            old_url = str(source.get("url", ""))
            new_url = snkrdunk_search_url(keyword)
            if old_url != new_url:
                source["url"] = new_url
                changed += 1
    if changed and not args.dry_run:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    action = "Would update" if args.dry_run else "Updated"
    print(f"{action} {changed} SnkrDunk source URL(s) in {path}")
    return 0


def cmd_sync_store(args: argparse.Namespace) -> int:
    settings, _ = load_config(Path(args.config))
    min_price = int(args.min_price or settings.get("min_own_price_idr", 500000))
    try:
        html_text = fetch_text(args.url)
    except RuntimeError as exc:
        print(f"Sync failed: {exc}")
        return 1
    products = extract_store_products(html_text, min_price)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"products": products}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(products)} product(s) to {output}")
    return 0


def cmd_seed_config(args: argparse.Namespace) -> int:
    store_path = Path(args.store_file)
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    products = []
    for item in payload.get("products", []):
        title = str(item.get("title", ""))
        if args.pokemon_only and "pokemon" not in title.lower():
            continue
        term = search_term_from_title(title)
        snkrdunk_term = parse_card_identity(title).snkrdunk_query() or term
        products.append(
            {
                "title": title,
                "own_price_idr": int(item["own_price_idr"]),
                "tokopedia_url": str(item.get("tokopedia_url", "")),
                "search_terms": [term],
                "card_identity": parse_card_identity(title).as_dict(),
                "sources": [
                    {
                        "name": "tokopedia competitors",
                        "kind": "tokopedia_find",
                        "url": f"https://www.tokopedia.com/find/{quote(term.replace(' ', '-').lower())}?ob=4",
                    },
                    {
                        "name": "ebay sold",
                        "kind": "ebay_sold",
                        "url": f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(term)}&LH_Sold=1&LH_Complete=1",
                    },
                    {
                        "name": "snkrdunk search",
                        "kind": "snkrdunk_search",
                        "url": f"https://snkrdunk.com/v3/search?func=all&refId=search&keyword={quote_plus(snkrdunk_term)}&sortKey=default&cardVersion=2&categoryIds=6&perPage=30&page=1",
                    },
                ],
            }
        )

    settings = {
        "min_own_price_idr": 500000,
        "cheap_threshold_percent": 8,
        "alert_threshold_percent": 12,
        "comparable_min_ratio_to_own": 0.35,
        "comparable_max_ratio_to_own": 8,
        "tokopedia_scam_floor_ratio": 0.55,
        "tokopedia_min_legit_results": 3,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"settings": settings, "products": products}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(products)} product config(s) to {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pokemon card marketplace price checker.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run price checks and generate reports.")
    run.add_argument("--config", default=str(DEFAULT_CONFIG))
    run.add_argument("--limit", type=int, default=None, help="Only run the first N products from config.")
    run.add_argument("--ai-summary", action="store_true", help="Use MiniMax to add concise seller notes to reports.")
    run.add_argument("--min-price-idr", type=int, default=None)
    run.add_argument("--debug", action="store_true", help="Persist bounded raw source snapshots under data/runs/<run_id>.")
    run.add_argument("--no-sold-detection", action="store_true", help="Skip Tokopedia store active/sold detection.")
    run.add_argument(
        "--fetch-backend",
        choices=("auto", "stdlib", "scrapling", "scrapling_dynamic"),
        default="auto",
        help="Fetch backend. auto uses Scrapling for eBay when available and stdlib elsewhere.",
    )
    run.set_defaults(func=cmd_run)

    sync = sub.add_parser("sync-store", help="Try to extract store products from a Tokopedia store URL.")
    sync.add_argument("--url", required=True)
    sync.add_argument("--config", default=str(DEFAULT_CONFIG))
    sync.add_argument("--output", default="data/store_products.json")
    sync.add_argument("--min-price", type=int, default=None)
    sync.set_defaults(func=cmd_sync_store)

    seed = sub.add_parser("seed-config", help="Create product config from data/store_products.json.")
    seed.add_argument("--store-file", default="data/store_products.json")
    seed.add_argument("--output", default="config/products.generated.json")
    seed.add_argument("--pokemon-only", action="store_true")
    seed.set_defaults(func=cmd_seed_config)

    validate = sub.add_parser("validate-config", help="Validate product config without running scrapers.")
    validate.add_argument("--config", default=str(DEFAULT_CONFIG))
    validate.set_defaults(func=cmd_validate_config)

    inspect = sub.add_parser("inspect-run", help="Print structured run trace data.")
    inspect.add_argument("run_id", nargs="?", type=int, default=None)
    inspect.add_argument("--db", default="data/price_history.sqlite3")
    inspect.set_defaults(func=cmd_inspect_run)

    migrate_snkrdunk = sub.add_parser(
        "migrate-snkrdunk-urls",
        help="Rewrite SnkrDunk sources to the v3 search endpoint used by the parser.",
    )
    migrate_snkrdunk.add_argument("--config", default=str(DEFAULT_CONFIG))
    migrate_snkrdunk.add_argument("--dry-run", action="store_true")
    migrate_snkrdunk.set_defaults(func=cmd_migrate_snkrdunk_urls)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
