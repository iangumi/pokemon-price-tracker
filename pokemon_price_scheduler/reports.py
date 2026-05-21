from __future__ import annotations

import csv
import html
from pathlib import Path

from .history import history_for_slug
from .models import ProductAnalysis


REPORT_DIR = Path("reports")
CHART_DIR = REPORT_DIR / "charts"


def idr(value: int | None) -> str:
    if value is None:
        return "-"
    return f"Rp {value:,.0f}".replace(",", ".")


def write_reports(analyses: list[ProductAnalysis], run_id: int) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    write_markdown(analyses, run_id, REPORT_DIR / "latest.md")
    write_csv(analyses, REPORT_DIR / "latest.csv")
    for analysis in analyses:
        write_chart(analysis.product.slug, CHART_DIR / f"{analysis.product.slug}.svg")
    write_dashboard(analyses, run_id)
    write_opportunities(analyses, REPORT_DIR / "opportunities.html")


def write_markdown(analyses: list[ProductAnalysis], run_id: int, path: Path) -> None:
    lines = [f"# Pokemon Price Report - Run {run_id}", ""]
    if analyses:
        lines.append(f"Generated: {analyses[0].run_at.isoformat()}")
        lines.append("")

    underpriced = [a for a in analyses if a.underpriced_by_idr]
    lines.append("## Priority Changes")
    lines.append("")
    if not underpriced:
        lines.append("No clearly underpriced cards found from parsed sources.")
    else:
        for analysis in sorted(underpriced, key=lambda item: item.underpriced_by_idr or 0, reverse=True):
            lines.extend(
                [
                    f"### {analysis.product.title}",
                    f"- Language: {analysis.product.language}",
                    f"- Your price: {idr(analysis.product.own_price_idr)}",
                    f"- Market median: {idr(analysis.market_median_idr)}",
                    f"- Underpriced by: {idr(analysis.underpriced_by_idr)} ({analysis.underpriced_by_percent}%)",
                    f"- Recommendation: {analysis.recommendation}",
                    *([f"- AI note: {analysis.ai_summary}"] if analysis.ai_summary else []),
                    f"- Chart: charts/{analysis.product.slug}.svg",
                    "",
                ]
            )

    lines.extend(["", "## All Products", ""])
    for analysis in analyses:
        lines.extend(
            [
                f"### {analysis.product.title}",
                f"- Language: {analysis.product.language}",
                f"- Your price: {idr(analysis.product.own_price_idr)}",
                f"- Market minimum: {idr(analysis.market_min_idr)}",
                f"- Market median: {idr(analysis.market_median_idr)}",
                f"- Recommendation: {analysis.recommendation}",
                *([f"- AI note: {analysis.ai_summary}"] if analysis.ai_summary else []),
            ]
        )
        warnings = [warning for result in analysis.source_results for warning in result.warnings]
        if warnings:
            lines.append("- Warnings:")
            for warning in warnings:
                lines.append(f"  - {warning}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(analyses: list[ProductAnalysis], path: Path) -> None:
    fieldnames = [
        "run_at",
        "title",
        "language",
        "own_price_idr",
        "market_min_idr",
        "market_median_idr",
        "global_average_idr",
        "price_delta_percent",
        "alert_level",
        "underpriced_by_idr",
        "underpriced_by_percent",
        "recommendation",
        "ai_summary",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for analysis in analyses:
            writer.writerow(analysis.to_row())


def write_chart(slug: str, path: Path) -> None:
    history = history_for_slug(slug)
    width = 760
    height = 240
    pad = 36
    values = [value for _, own, market in history for value in (own, market) if value is not None]
    if not values:
        path.write_text(blank_chart(width, height, "No history yet"), encoding="utf-8")
        return
    low = min(values)
    high = max(values)
    if low == high:
        low = int(low * 0.9)
        high = int(high * 1.1) or 1

    def point(index: int, value: int) -> tuple[float, float]:
        x = pad if len(history) == 1 else pad + (index / (len(history) - 1)) * (width - pad * 2)
        y = height - pad - ((value - low) / (high - low)) * (height - pad * 2)
        return x, y

    own_points = " ".join(f"{x:.1f},{y:.1f}" for i, (_, own, _) in enumerate(history) for x, y in [point(i, own)])
    market_points = " ".join(
        f"{x:.1f},{y:.1f}"
        for i, (_, _, market) in enumerate(history)
        if market is not None
        for x, y in [point(i, market)]
    )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#242428"/>
  <line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#3a3a42"/>
  <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="#3a3a42"/>
  <text x="{pad}" y="22" font-family="monospace" font-size="14" fill="#8b8b96">Price history</text>
  <text x="{width-pad-170}" y="22" font-family="monospace" font-size="12" fill="#4ade80">Market median</text>
  <text x="{width-pad-170}" y="40" font-family="monospace" font-size="12" fill="#818cf8">Your price</text>
  <polyline points="{market_points}" fill="none" stroke="#4ade80" stroke-width="3"/>
  <polyline points="{own_points}" fill="none" stroke="#818cf8" stroke-width="3"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def blank_chart(width: int, height: int, message: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#0a1628"/>
  <text x="32" y="42" font-family="monospace" font-size="14" fill="#4a7aaa">{message}</text>
</svg>
"""


def h(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:+.1f}%"


def write_dashboard(analyses: list[ProductAnalysis], run_id: int) -> None:
    detail_dir = REPORT_DIR / "cards"
    detail_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for analysis in sorted(analyses, key=lambda item: abs(item.price_delta_percent or 0), reverse=True):
        identity = analysis.product.card_identity
        rows.append(
            f"""
            <tr class="alert-{h(analysis.alert_level)}">
              <td><a href="cards/{h(analysis.product.slug)}.html">{h(identity.name or analysis.product.title)}</a></td>
              <td>{h(identity.set_symbol)}</td>
              <td>{h(identity.rarity)}</td>
              <td>{h(identity.language)}</td>
              <td>{h(identity.condition)}</td>
              <td>{idr(analysis.product.own_price_idr)}</td>
              <td>{idr(analysis.global_average_idr)}</td>
              <td>{pct(analysis.price_delta_percent)}</td>
              <td>{h(analysis.alert_level)}</td>
            </tr>
            """
        )
        write_card_detail(analysis, detail_dir / f"{analysis.product.slug}.html")

    generated = analyses[0].run_at.isoformat() if analyses else ""
    html_doc = page_shell(
        "Pokemon Price Dashboard",
        f"""
          <table>
            <thead>
              <tr>
                <th>Card</th><th>Set</th><th>Rarity</th><th>Language</th><th>Condition</th>
                <th>Your Price</th><th>Global Avg</th><th>Delta</th><th>Alert</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        """,
        topbar=f"Run {run_id} generated {h(generated)}. Red means your Tokopedia price is at least the configured alert threshold away from the global average.",
        current_page="dash",
    )
    (REPORT_DIR / "dashboard.html").write_text(html_doc, encoding="utf-8")


def write_card_detail(analysis: ProductAnalysis, path: Path) -> None:
    identity = analysis.product.card_identity

    # Build observation lookup by source name
    observations_by_source = {}
    for result in analysis.source_results:
        observations_by_source[result.source.name] = result.observations

    source_sections = []
    for src in analysis.product.sources:
        obs_list = observations_by_source.get(src.name, [])
        rows = []
        for obs in obs_list[:10]:
            legit = "yes" if obs.is_legit else "filtered"
            rows.append(
                f"""
                <tr>
                  <td><a href="{h(obs.url)}">{h(obs.title or src.name)}</a></td>
                  <td>{idr(obs.price_idr)}</td>
                  <td>{h(obs.source_kind)}</td>
                  <td>{h(getattr(obs, 'relevance_score', 0))}</td>
                  <td>{legit}</td>
                </tr>
                """
            )
        source_sections.append(
            f"""
            <section>
              <h2>{h(src.name)}</h2>
              <p><a href="{h(src.url)}">Open source search</a></p>
              <table>
                <thead><tr><th>Listing</th><th>Price</th><th>Source</th><th>Match</th><th>Used</th></tr></thead>
                <tbody>{''.join(rows) if rows else '<tr><td colspan="5">No comparable listings parsed.</td></tr>'}</tbody>
              </table>
            </section>
            """
        )
    content = f"""
      <section class="metrics">
        <div><span>Your Price</span><strong>{idr(analysis.product.own_price_idr)}</strong></div>
        <div><span>Global Avg</span><strong>{idr(analysis.global_average_idr)}</strong></div>
        <div><span>Delta</span><strong>{pct(analysis.price_delta_percent)}</strong></div>
        <div><span>Alert</span><strong>{h(analysis.alert_level)}</strong></div>
      </section>
      <section class="identity">
        <h2>Card Identity</h2>
        <dl>
          <dt>Name</dt><dd>{h(identity.name)}</dd>
          <dt>Set</dt><dd>{h(identity.set_symbol)}</dd>
          <dt>Card Number</dt><dd>{h(identity.card_number)}</dd>
          <dt>Rarity</dt><dd>{h(identity.rarity)}</dd>
          <dt>Language</dt><dd>{h(identity.language)}</dd>
          <dt>Condition</dt><dd>{h(identity.condition)}</dd>
        </dl>
      </section>
      {f'<section><h2>AI Seller Note</h2><p>{h(analysis.ai_summary)}</p></section>' if analysis.ai_summary else ''}
      <section>
        <h2>Price Change</h2>
        <img src="../charts/{h(analysis.product.slug)}.svg" alt="Price chart for {h(identity.name)}">
      </section>
      {''.join(source_sections)}
    """
    path.write_text(page_shell(identity.name or analysis.product.title, content,
        topbar=h(analysis.product.title),
        current_page="cards"), encoding="utf-8")


def write_opportunities(analyses: list[ProductAnalysis], path: Path) -> None:
    candidates = []
    for analysis in analyses:
        global_count = sum(len(result.observations) for result in analysis.source_results if result.source.kind != "tokopedia_find")
        local_count = sum(len([obs for obs in result.observations if obs.is_legit]) for result in analysis.source_results if result.source.kind == "tokopedia_find")
        if not analysis.global_average_idr:
            continue
        scarcity_score = max(0, 10 - local_count)
        demand_score = min(10, global_count)
        delta_bonus = 2 if (analysis.price_delta_percent or 0) < -10 else 0
        score = scarcity_score + demand_score + delta_bonus
        candidates.append((score, global_count, local_count, analysis))

    rows = []
    for score, global_count, local_count, analysis in sorted(candidates, key=lambda item: item[0], reverse=True)[:50]:
        identity = analysis.product.card_identity
        rows.append(
            f"""
            <tr>
              <td><a href="cards/{h(analysis.product.slug)}.html">{h(identity.name or analysis.product.title)}</a></td>
              <td>{h(identity.set_symbol)}</td>
              <td>{h(identity.rarity)}</td>
              <td>{idr(analysis.global_average_idr)}</td>
              <td>{global_count}</td>
              <td>{local_count}</td>
              <td>{score}</td>
              <td>Review as potential import if global listings are liquid and local listings are thin.</td>
            </tr>
            """
        )
    path.write_text(
        page_shell(
            "Buying Opportunities",
            f"""
              <table>
                <thead><tr><th>Card</th><th>Set</th><th>Rarity</th><th>Global Avg</th><th>Global Items</th><th>Local Items</th><th>Score</th><th>Note</th></tr></thead>
                <tbody>{''.join(rows) if rows else '<tr><td colspan="8">No opportunity candidates yet.</td></tr>'}</tbody>
              </table>
            """,
            topbar="First-pass candidates from high global evidence plus low Tokopedia local supply. Treat this as a shortlist, not an auto-buy signal.",
            current_page="ops",
        ),
        encoding="utf-8",
    )


def page_shell(title: str, body: str, topbar: str = "", current_page: str = "") -> str:
    def nav_class(page: str) -> str:
        return " active" if page == current_page else ""

    sidebar = f"""
    <aside class="sidebar">
      <div class="sidebar-brand">
        <h1>Pokemon Price</h1>
        <span>Tracker</span>
      </div>
      <div class="sidebar-section-label">Navigation</div>
      <nav>
        <a href="/" class="{nav_class('dash')}">Dashboard</a>
        <a href="/cards" class="{nav_class('cards')}">My Cards</a>
        <a href="latest.md" class="{nav_class('reports')}">Reports</a>
        <a href="opportunities.html" class="{nav_class('ops')}">Opportunities</a>
      </nav>
      <div class="spacer"></div>
      <div class="sidebar-footer">
        <button id="run-btn" class="btn" onclick="runScheduler()">Run Scheduler</button>
      </div>
    </aside>"""

    topbar_html = f"""
    <div class="topbar">
      <h1>{h(title)}</h1>
      <div class="topbar-meta">{topbar}</div>
    </div>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{h(title)}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    /* ── Design Tokens ─────────────────────────────── */
    :root {{
      --bg:        #1a1a1e;
      --surface:   #242428;
      --surface-2: #2e2e34;
      --border:    #3a3a42;
      --text:      #e8e8ed;
      --muted:     #8b8b96;
      --accent:    #818cf8;
      --accent-h:  #a5b4fc;
      --green:     #4ade80;
      --amber:     #fbbf24;
      --red:       #f87171;
      --font-display: 'Outfit', sans-serif;
      --font-body:    'Inter', sans-serif;
      --sp-1: 8px;
      --sp-2: 16px;
      --sp-3: 24px;
      --sp-4: 32px;
      --sp-5: 40px;
      --sp-6: 48px;
      --radius-sm: 4px;
      --radius-md: 6px;
      --motion-fast: 120ms ease;
      --sidebar-w: 220px;
    }}

    /* ── Reset & Base ─────────────────────────────── */
    *, *::before, *::after {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; }}
    body {{
      font-family: var(--font-body);
      color: var(--text);
      background: var(--bg);
      -webkit-font-smoothing: antialiased;
      display: flex;
      flex-direction: column;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ color: var(--accent-h); }}
    a:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 2px; }}

    /* ── Scrollbar ─────────────────────────────────── */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: var(--surface); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--muted); }}

    /* ── Sidebar ─────────────────────────────────────── */
    .sidebar {{
      width: var(--sidebar-w);
      min-width: var(--sidebar-w);
      background: var(--surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      height: 100vh;
      position: sticky;
      top: 0;
      overflow-y: auto;
    }}
    .sidebar-brand {{
      padding: var(--sp-3) var(--sp-3);
      border-bottom: 1px solid var(--border);
    }}
    .sidebar-brand h1 {{
      font-family: var(--font-display);
      font-size: 16px;
      font-weight: 700;
      color: var(--text);
      margin: 0;
      letter-spacing: 0.02em;
    }}
    .sidebar-brand span {{
      font-size: 10px;
      color: var(--muted);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }}
    .sidebar-section-label {{
      padding: var(--sp-3) var(--sp-3) var(--sp-1);
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .sidebar nav {{
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 0 var(--sp-2) var(--sp-2);
    }}
    .sidebar nav a {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 8px 10px;
      border-radius: var(--radius-sm);
      font-size: 13px;
      font-weight: 500;
      color: var(--muted);
      transition: all var(--motion-fast);
    }}
    .sidebar nav a:hover {{
      color: var(--text);
      background: var(--surface-2);
    }}
    .sidebar nav a.active {{
      color: var(--accent);
      background: #818cf812;
    }}
    .sidebar nav a .nav-icon {{
      font-size: 16px;
      width: 20px;
      text-align: center;
      flex-shrink: 0;
    }}
    .sidebar .spacer {{ flex: 1; }}
    .sidebar-footer {{
      padding: var(--sp-2) var(--sp-3);
      border-top: 1px solid var(--border);
    }}
    .sidebar-footer .btn {{
      width: 100%;
      text-align: center;
    }}

    /* ── Layout ─────────────────────────────────────── */
    .app {{
      display: flex;
      flex: 1;
      min-height: 100vh;
    }}
    .content {{
      flex: 1;
      display: flex;
      flex-direction: column;
      min-width: 0;
    }}
    .topbar {{
      padding: var(--sp-2) var(--sp-4);
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: var(--sp-2);
    }}
    .topbar h1 {{
      font-family: var(--font-display);
      font-size: 16px;
      font-weight: 600;
      color: var(--text);
      margin: 0;
      letter-spacing: -0.01em;
      flex: 1;
    }}
    .topbar-meta {{
      font-size: 12px;
      color: var(--muted);
    }}
    .topbar-actions {{
      display: flex;
      align-items: center;
      gap: var(--sp-1);
    }}
    .main {{ padding: var(--sp-4); flex: 1; }}

    /* ── Buttons ───────────────────────────────────── */
    .btn {{
      font-family: var(--font-body);
      font-size: 13px;
      font-weight: 500;
      color: var(--bg);
      background: var(--accent);
      border: none;
      padding: 7px 14px;
      border-radius: var(--radius-sm);
      cursor: pointer;
      transition: background var(--motion-fast), transform var(--motion-fast);
      white-space: nowrap;
    }}
    .btn:hover {{ background: var(--accent-h); }}
    .btn:active {{ transform: scale(0.98); }}
    .btn:disabled {{ background: var(--border); color: var(--muted); cursor: not-allowed; transform: none; }}
    .btn.running {{ background: var(--amber); }}

    /* ── Table ─────────────────────────────────────── */
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      overflow: hidden;
    }}
    thead {{ background: var(--surface-2); }}
    th {{
      font-family: var(--font-display);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      padding: 10px var(--sp-2);
      text-align: left;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }}
    td {{
      padding: 10px var(--sp-2);
      font-size: 13px;
      border-bottom: 1px solid var(--border);
      color: var(--text);
      vertical-align: middle;
    }}
    tr:last-child td {{ border-bottom: none; }}
    tr:hover td {{ background: var(--surface-2); }}
    tr.alert-red td {{ background: #f8717115; }}
    tr.alert-amber td {{ background: #fbbf2415; }}

    /* Status dot */
    .status-dot {{
      display: inline-block;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      margin-right: 6px;
      vertical-align: middle;
    }}
    .status-dot.ok     {{ background: var(--green); }}
    .status-dot.warn   {{ background: var(--amber); }}
    .status-dot.danger {{ background: var(--red); }}
    .status-dot.none   {{ background: var(--muted); }}

    /* ── Warning ───────────────────────────────────── */
    .warning {{
      color: var(--amber);
      font-size: 12px;
      margin: var(--sp-1) 0;
    }}

    /* ── Metrics Grid ──────────────────────────────── */
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: var(--sp-2);
      margin-bottom: var(--sp-3);
    }}
    .metrics > div {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: var(--sp-2) var(--sp-3);
    }}
    .metrics span {{
      display: block;
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .metrics strong {{
      display: block;
      font-size: 22px;
      font-weight: 700;
      color: var(--text);
      letter-spacing: -0.01em;
    }}
    .metrics strong.negative {{ color: var(--red); }}
    .metrics strong.positive {{ color: var(--green); }}
    .metrics strong.neutral  {{ color: var(--amber); }}

    /* ── Definition List ───────────────────────────── */
    dl {{
      display: grid;
      grid-template-columns: 140px 1fr;
      gap: 0 var(--sp-2);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: var(--sp-2) var(--sp-3);
    }}
    dt {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 500;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
    }}
    dd {{
      margin: 0;
      font-size: 13px;
      color: var(--text);
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
    }}
    dl > :last-child {{ border-bottom: none; }}

    /* ── Images ───────────────────────────────────── */
    img {{
      max-width: 100%;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
    }}

    /* ── Section Headings ─────────────────────────── */
    h2 {{
      font-family: var(--font-display);
      font-size: 14px;
      font-weight: 600;
      letter-spacing: 0.05em;
      color: var(--text);
      margin: var(--sp-4) 0 var(--sp-2);
      padding-bottom: 8px;
      border-bottom: 1px solid var(--border);
    }}
  </style>
</head>
<body>
<div class="app">
  {sidebar}
  <div class="content">
    {topbar_html}
    <main class="main">
{body}
    </main>
  </div>
</div>
</body>
<script>
async function checkTokopedia() {{
  const btn = document.getElementById('tokopedia-btn');
  const url = btn.dataset.url;
  if (!url) {{
    alert('No Tokopedia URL configured for this card.');
    return;
  }}
  const popup = window.open(url, '_blank', 'width=800,height=600,scrollbars=yes,resizable=yes');
  if (popup) popup.focus();
}}
async function runScheduler() {{
  const btn = document.getElementById("run-btn");
  if (!btn) return;
  btn.disabled = true;
  btn.classList.add("running");
  btn.textContent = "Running...";
  try {{
    const res = await fetch("/run", {{ method: "POST" }});
    const data = await res.json();
    if (data.ok) {{
      btn.textContent = "Done! Refreshing...";
      location.reload();
    }} else {{
      btn.textContent = "Error: " + (data.error || "unknown");
      btn.disabled = false;
      btn.classList.remove("running");
    }}
  }} catch(e) {{
    btn.textContent = "Failed: " + e.message;
    btn.disabled = false;
    btn.classList.remove("running");
  }}
}}
</script>
</html>
"""
