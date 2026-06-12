# AI Roadmap

This project should use AI as a reasoning layer over locally collected evidence, not as the source of truth for prices.

## Priority Order

1. **AI Repricing Copilot** - explain one-card repricing decisions from local price evidence, source observations, trends, suggested prices, and counterpart candidates.
2. **AI Search-Term Optimizer** - suggest better competitor search terms when sources return weak, noisy, or missing results.
3. **AI Opportunity Scoring** - rank buy-list opportunities using observed buy price, inventory state, latest market averages, and historical sales.
4. **AI Source Health Debugger** - convert source failures into practical next actions such as broaden query, retry later, inspect parser, or ignore source.
5. **AI Weekly Store Review** - summarize repricing actions, stale inventory, sold-card performance, and opportunity priorities.
6. **AI Listing Description Assistant** - generate Tokopedia listing title/description/tag drafts from card identity and store style.

## Current V1 Direction

The first implementation is Card Detail focused:

- `AI Repricing Copilot` is generated on demand.
- Advice is cached by input hash to avoid repeated API cost for unchanged evidence.
- `POST /api/cards/<slug>/ai-repricing-advice?force=1` regenerates advice for unchanged evidence when prompt/model behavior changes.
- Advice uses only supplied evidence and must return structured JSON.
- Missing API key or AI failure is non-fatal and should be saved as an error record for UI visibility.
- `pokemon_price_scheduler/infrastructure/ai.py` owns prompt construction, response parsing, `.env` loading, and evidence hashing.
- `pokemon_price_scheduler/infrastructure/history.py` owns durable `ai_repricing_advice` records.

## Counterpart Map Direction

International counterpart matching starts as a Card Detail panel, not a standalone page.

V1 stores and displays counterpart candidates with:

- source and source URL
- candidate title
- language/version
- raw price and currency
- converted IDR price
- FX rate used
- match confidence
- match reason

`pokemon_price_scheduler/infrastructure/counterparts.py` owns V1 counterpart preparation. It currently builds candidates from stored source observations and converts USD/JPY/IDR with fixed application FX rates. Treat those conversions as comparable decision support, not accounting-grade exchange-rate history.

`pokemon_price_scheduler/infrastructure/history.py` owns durable `counterpart_candidates` rows. Refreshing candidates replaces the stored rows for the card slug, so future source connectors should pass all current candidates for that card in one refresh.

Manual verification:

- Run the scheduler or refresh competitors for a card so observations exist.
- Open `/cards/<slug>`.
- Click `Refresh Counterparts` and confirm rows show source, raw price, converted IDR, confidence, and reason.
- Click `Generate AI Advice` with `MINIMAX_API_KEY` configured and confirm the second click reuses cached advice unless `?force=1` is used.

Future `/counterparts` page should be added only after enough counterpart data exists to support bulk review of unmapped cards, low-confidence mappings, and Indonesia vs US/Japan price gaps.

## Data Quality Rule

Do not ask the AI to search the web and provide prices as authoritative data. Source connectors, APIs, or scrapers should fetch prices deterministically. AI can then explain, rank, and summarize that evidence.
