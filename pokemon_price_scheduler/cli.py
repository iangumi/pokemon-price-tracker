from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path
from urllib.parse import quote, quote_plus

from .ai import attach_ai_summaries
from .analyze import analyze_product
from .card_parser import parse_card_identity
from .config import DEFAULT_CONFIG, load_config, save_config
from .history import save_run
from .http import fetch_text
from .models import Product, utc_now
from .reports import write_reports
from .scrapers import MarketplaceScraper, extract_store_products
from .store_sync import get_active_store_product_urls


def search_term_from_title(title: str) -> str:
    return parse_card_identity(title).tokopedia_query() or title


def cmd_run(args: argparse.Namespace) -> int:
    settings, products = load_config(Path(args.config))

    # ── Sold detection: check which products are still on store page ──
    active_urls = get_active_store_product_urls(settings)
    if active_urls:
        updated_products = []
        for product in products:
            import dataclasses as dc
            if product.status != "sold" and product.tokopedia_url and product.tokopedia_url not in active_urls:
                sold_product = dc.replace(product, status="sold", sold_at=utc_now().isoformat())
                updated_products.append(sold_product)
                print(f"  SOLD: {product.title}")
            else:
                updated_products.append(product)
        products = updated_products
        save_config(Path(args.config), settings, products)

    min_price = int(settings.get("min_own_price_idr", 500000))
    products = [product for product in products if product.own_price_idr >= min_price]
    if args.limit:
        products = products[: args.limit]
    scraper = MarketplaceScraper(settings)
    run_at = utc_now()
    analyses = []
    for product in products:
        source_results = [scraper.scrape(source) for source in product.sources]
        analyses.append(analyze_product(product, source_results, run_at, settings))
    if args.ai_summary:
        analyses, ai_warnings = attach_ai_summaries(analyses)
        for warning in ai_warnings:
            print(warning)
    run_id = save_run(analyses)
    write_reports(analyses, run_id)
    print(f"Run {run_id} complete. Report: reports/latest.md")
    return 0


def cmd_sync_store(args: argparse.Namespace) -> int:
    settings, _ = load_config(Path(args.config))
    min_price = int(args.min_price or settings.get("min_own_price_idr", 500000))
    html_text = fetch_text(args.url)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
