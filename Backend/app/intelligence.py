from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MARKET_FILE = "market_data.json"
HISTORICAL_FILE = "historical_data.json"
NEWS_FILE = "news_data.json"
PORTFOLIOS_FILE = "portfolios.json"
MUTUAL_FUNDS_FILE = "mutual_funds.json"
SECTOR_MAPPING_FILE = "sector_mapping.json"

SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "banking": ("bank", "banks", "banking", "rbi", "rate", "liquidity", "credit", "deposit"),
    "financials": ("bank", "banks", "nbfc", "financial", "rbi", "credit", "liquidity"),
    "it": ("it", "software", "technology", "exporter", "deal", "us demand"),
    "technology": ("technology", "software", "it services", "ai", "cloud"),
    "energy": ("energy", "oil", "gas", "crude", "refining", "reliance"),
    "auto": ("auto", "vehicle", "ev", "two-wheeler", "car"),
    "pharma": ("pharma", "drug", "healthcare", "usfda"),
    "metal": ("metal", "steel", "aluminium", "commodity"),
    "fmcg": ("fmcg", "consumer", "rural demand", "staples"),
}

MARKET_KEYWORDS = (
    "market",
    "index",
    "indices",
    "nifty",
    "sensex",
    "macro",
    "inflation",
    "fed",
    "global",
)

POSITIVE_WORDS = (
    "gain",
    "gains",
    "rise",
    "rises",
    "up",
    "positive",
    "strong",
    "supports",
    "supportive",
    "boost",
    "improves",
    "stable",
    "eases",
)
NEGATIVE_WORDS = (
    "fall",
    "falls",
    "down",
    "negative",
    "weak",
    "pressure",
    "risk",
    "cuts",
    "concern",
    "worries",
    "volatile",
    "tightens",
)


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _as_mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_sequence(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _coerce_named_rows(value: object, default_name_key: str = "name") -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [_as_row(item) for item in value]
    if isinstance(value, Mapping):
        rows = []
        for name, item in value.items():
            row = _as_row(item)
            row.setdefault(default_name_key, name)
            rows.append(row)
        return rows
    return []


def _as_row(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_present(row: Mapping[str, Any], names: Sequence[str], default: object = None) -> object:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _row_name(row: Mapping[str, Any], fallback: str = "unknown") -> str:
    return _text(_first_present(row, ("name", "symbol", "ticker", "index", "sector"), fallback))


def _normalize_sector(value: object) -> str:
    sector = _text(value, "UNKNOWN").strip().upper()
    return sector if sector else "UNKNOWN"


def _change_pct(row: Mapping[str, Any]) -> float:
    explicit = _first_present(
        row,
        (
            "change_pct",
            "changePct",
            "percentChange",
            "pct_change",
            "change_percent",
            "dayChangePct",
            "change",
        ),
    )
    if explicit is not None:
        return _safe_float(explicit)

    current = _first_present(row, ("current", "last", "lastPrice", "close", "price"))
    previous = _first_present(row, ("previous", "previousClose", "prev_close", "open"))
    current_value = _safe_float(current)
    previous_value = _safe_float(previous)
    if previous_value:
        return (current_value - previous_value) / previous_value * 100
    return 0.0


def _extract_indices(market_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("indices", "market_indices", "index_data", "markets"):
        rows = _coerce_named_rows(market_data.get(key))
        if rows:
            return rows
    if "name" in market_data or "symbol" in market_data:
        return [dict(market_data)]
    return []


def _extract_sectors(market_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("sectors", "sector_data", "sectorData", "sector_performance"):
        rows = _coerce_named_rows(market_data.get(key))
        if rows:
            return rows
    return []


def _extract_stocks(market_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("stocks", "stock_data", "stockData", "equities", "constituents"):
        rows = _coerce_named_rows(market_data.get(key), default_name_key="symbol")
        if rows:
            return rows
    return []


def _history_rows(historical_data: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    value = historical_data.get(key)
    if isinstance(value, Mapping):
        return _coerce_named_rows(value, default_name_key="symbol")
    return _coerce_named_rows(value)


def _history_return(value: object) -> float:
    if isinstance(value, Mapping):
        explicit = _first_present(
            value,
            (
                "cumulative_change_percent",
                "weekly_change_percent",
                "change_percent",
                "change_pct",
                "changePct",
            ),
        )
        if explicit is not None:
            return _safe_float(explicit)
        if "data" in value:
            return _history_return(value["data"])
        row_change = _change_pct(value)
        if row_change:
            return row_change

    rows = _as_sequence(value)
    prices = [
        _safe_float(
            _first_present(row, ("close", "price", "lastPrice", "value", "index_value")),
            default=0.0,
        )
        for row in rows
        if isinstance(row, Mapping)
    ]
    prices = [price for price in prices if price > 0]
    if len(prices) < 2:
        return 0.0
    return (prices[-1] - prices[0]) / prices[0] * 100


def _historical_lookup(historical_data: Mapping[str, Any], keys: Sequence[str]) -> dict[str, float]:
    lookup: dict[str, float] = {}
    for key in keys:
        value = historical_data.get(key)
        if isinstance(value, Mapping):
            for name, rows in value.items():
                lookup[str(name).lower()] = _history_return(rows)
        elif isinstance(value, list):
            grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
            for item in value:
                row = _as_mapping(item)
                name = _row_name(row)
                grouped[name.lower()].append(row)
            for name, rows in grouped.items():
                lookup[name] = _history_return(rows)
    return lookup


def _sentiment_label(score: float) -> str:
    if score >= 0.2:
        return "bullish"
    if score <= -0.2:
        return "bearish"
    return "neutral"


def _trend_label(score: float) -> str:
    if score >= 0.18:
        return "positive"
    if score <= -0.18:
        return "negative"
    return "neutral"


def _impact_label(score: float) -> str:
    if score >= 0.12:
        return "positive"
    if score <= -0.12:
        return "negative"
    return "neutral"


def _sign_label(value: float) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"


def _market_summary(market_data: Mapping[str, Any]) -> dict[str, Any]:
    indices = _extract_indices(market_data)
    index_rows = [
        {
            "name": _row_name(row),
            "changePct": round(_change_pct(row), 3),
            "lastPrice": _safe_float(
                _first_present(row, ("lastPrice", "price", "close", "current", "current_value"))
            ),
        }
        for row in indices
    ]
    average_change = (
        sum(row["changePct"] for row in index_rows) / max(len(index_rows), 1)
        if index_rows
        else 0.0
    )
    score = round(_clamp(average_change / 2.0, -1.0, 1.0), 3)
    sorted_indices = sorted(index_rows, key=lambda row: abs(float(row["changePct"])), reverse=True)
    drivers = [
        f"{row['name']} moved {row['changePct']:+.2f}%"
        for row in sorted_indices[:3]
        if abs(float(row["changePct"])) > 0
    ]
    return {
        "sentiment": _sentiment_label(score),
        "score": score,
        "averageIndexChangePct": round(average_change, 3),
        "indices": index_rows,
        "drivers": drivers,
    }


def _sector_name(value: object) -> str:
    raw = _text(value, "Unknown").strip()
    return raw if raw else "Unknown"


def _sector_trends(
    market_data: Mapping[str, Any],
    historical_data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sector_rows = _extract_sectors(market_data)
    stock_rows = _extract_stocks(market_data)
    sector_history = _historical_lookup(
        historical_data,
        (
            "sectors",
            "sector_history",
            "sectorData",
            "historical_sectors",
            "sector_weekly_performance",
        ),
    )
    stock_history = _historical_lookup(
        historical_data,
        ("stocks", "stock_history", "stockData", "historical_stocks"),
    )

    sector_changes = {
        _sector_name(_first_present(row, ("name", "sector", "symbol"))): _change_pct(row)
        for row in sector_rows
    }
    stocks_by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for stock in stock_rows:
        sector = _sector_name(
            _first_present(stock, ("sector", "sectorName", "industry"), "Unknown")
        )
        stocks_by_sector[sector].append(stock)

    sectors = sorted({*sector_changes, *stocks_by_sector})
    trends: list[dict[str, Any]] = []
    for sector in sectors:
        stocks = stocks_by_sector.get(sector, [])
        stock_change = (
            sum(_change_pct(stock) for stock in stocks) / max(len(stocks), 1)
            if stocks
            else 0.0
        )
        stock_momentum_values = [
            stock_history.get(_row_name(stock).lower(), 0.0)
            for stock in stocks
            if _row_name(stock).lower() in stock_history
        ]
        stock_momentum = (
            sum(stock_momentum_values) / max(len(stock_momentum_values), 1)
            if stock_momentum_values
            else 0.0
        )
        sector_momentum = sector_history.get(sector.lower(), 0.0)
        market_sector_change = sector_changes.get(sector, 0.0)
        composite_pct = (
            market_sector_change * 0.4
            + stock_change * 0.35
            + sector_momentum * 0.15
            + stock_momentum * 0.1
        )
        score = round(_clamp(composite_pct / 3.0, -1.0, 1.0), 3)
        drivers = []
        if market_sector_change:
            drivers.append(f"sector move {market_sector_change:+.2f}%")
        if stock_change:
            drivers.append(f"stock basket {stock_change:+.2f}%")
        if sector_momentum or stock_momentum:
            drivers.append(
                f"history momentum {(sector_momentum or stock_momentum):+.2f}%"
            )
        trends.append(
            {
                "sector": sector,
                "trend": _trend_label(score),
                "score": score,
                "sectorChangePct": round(market_sector_change, 3),
                "stockAverageChangePct": round(stock_change, 3),
                "historicalMomentumPct": round(sector_momentum or stock_momentum, 3),
                "stockCount": len(stocks),
                "drivers": drivers,
            }
        )
    return sorted(trends, key=lambda row: abs(float(row["score"])), reverse=True)


def _known_symbols_and_names(market_data: Mapping[str, Any]) -> dict[str, str]:
    known: dict[str, str] = {}
    for stock in _extract_stocks(market_data):
        symbol = _text(_first_present(stock, ("symbol", "ticker", "name"))).strip()
        name = _text(_first_present(stock, ("name", "company", "companyName"), symbol)).strip()
        if symbol:
            known[symbol] = name
    return known


def _known_sectors(market_data: Mapping[str, Any]) -> list[str]:
    sectors = {
        _sector_name(_first_present(row, ("name", "sector", "symbol")))
        for row in _extract_sectors(market_data)
    }
    for stock in _extract_stocks(market_data):
        sectors.add(_sector_name(_first_present(stock, ("sector", "sectorName", "industry"))))
    return sorted(sector for sector in sectors if sector != "Unknown")


def _heuristic_news_sentiment(text: str, explicit: object = None) -> float:
    if explicit is not None:
        return _clamp(_safe_float(explicit), -1.0, 1.0)
    normalized = text.lower()
    positive_hits = sum(normalized.count(word) for word in POSITIVE_WORDS)
    negative_hits = sum(normalized.count(word) for word in NEGATIVE_WORDS)
    if positive_hits == negative_hits:
        return 0.0
    return _clamp((positive_hits - negative_hits) / max(positive_hits + negative_hits, 1), -1, 1)


def _linked_stocks(text: str, known_stocks: Mapping[str, str]) -> list[str]:
    normalized = text.lower()
    linked = []
    for symbol, name in known_stocks.items():
        symbol_hit = (
            symbol.lower() in normalized
            or symbol.removesuffix(".NS").lower() in normalized
        )
        name_hit = bool(name and name.lower() in normalized)
        if symbol_hit or name_hit:
            linked.append(symbol)
    return sorted(set(linked))


def _linked_sectors(text: str, known_sectors: Sequence[str]) -> list[str]:
    normalized = text.lower()
    linked: set[str] = set()
    for sector in known_sectors:
        sector_key = sector.lower()
        keywords = SECTOR_KEYWORDS.get(sector_key, (sector_key,))
        if sector_key in normalized or any(keyword in normalized for keyword in keywords):
            linked.add(sector)

    if "rbi" in normalized and any(
        word in normalized for word in ("rate", "liquidity", "credit", "bank", "deposit")
    ):
        banking_sector = next(
            (
                sector
                for sector in known_sectors
                if sector.lower() in {"banking", "financials", "financial services"}
            ),
            "Banking",
        )
        linked.add(banking_sector)
    return sorted(linked)


def _entity_links(item: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    entities = _as_mapping(item.get("entities"))
    sectors = [_text(value) for value in _as_sequence(entities.get("sectors")) if _text(value)]
    stocks = [_text(value) for value in _as_sequence(entities.get("stocks")) if _text(value)]
    indices = [_text(value) for value in _as_sequence(entities.get("indices")) if _text(value)]
    return sorted(set(sectors)), sorted(set(stocks)), sorted(set(indices))


def _news_classification(
    item: Mapping[str, Any],
    known_stocks: Mapping[str, str],
    known_sectors: Sequence[str],
) -> dict[str, Any]:
    headline = _text(_first_present(item, ("headline", "title", "name"), "Untitled news"))
    summary = _text(_first_present(item, ("summary", "description", "body"), ""))
    text = f"{headline} {summary}".strip()
    entity_sectors, entity_stocks, entity_indices = _entity_links(item)
    linked_stocks = sorted(set(entity_stocks) | set(_linked_stocks(text, known_stocks)))
    text_sectors = set(_linked_sectors(text, known_sectors)) if not entity_sectors else set()
    linked_sectors = sorted(set(entity_sectors) | text_sectors)
    score = _heuristic_news_sentiment(
        text,
        _first_present(item, ("sentiment_score", "sentimentScore", "score")),
    )
    scope = _text(_first_present(item, ("scope", "classification", "type"))).upper()

    classification = "market"
    if scope.startswith("STOCK"):
        classification = "stock"
    elif scope.startswith("SECTOR"):
        classification = "sector"
    elif scope.startswith("MARKET"):
        classification = "market"
    elif linked_stocks:
        classification = "stock"
    elif linked_sectors:
        classification = "sector"
    elif any(keyword in text.lower() for keyword in MARKET_KEYWORDS):
        classification = "market"

    reason = "Broad market keyword match"
    if scope:
        reason = f"Provided scope {scope}"
        if linked_sectors:
            reason = f"{reason}; affected sectors: {', '.join(linked_sectors)}"
        if linked_stocks:
            reason = f"{reason}; affected stocks: {', '.join(linked_stocks)}"
    elif classification == "stock":
        reason = f"Matched stock symbols or names: {', '.join(linked_stocks)}"
    elif classification == "sector":
        reason = f"Matched sector context: {', '.join(linked_sectors)}"
    return {
        "headline": headline,
        "summary": summary,
        "classification": classification,
        "impact": _impact_label(score),
        "sentimentScore": round(score, 3),
        "affectedSectors": linked_sectors,
        "affectedStocks": linked_stocks,
        "affectedIndices": entity_indices,
        "impactLevel": _text(_first_present(item, ("impact_level", "impactLevel"), "UNKNOWN")),
        "causalFactors": [
            _text(value)
            for value in _as_sequence(_first_present(item, ("causal_factors", "causalFactors"), []))
        ],
        "reason": reason,
    }


def _news_items(news_data: object) -> list[dict[str, Any]]:
    if isinstance(news_data, Mapping):
        for key in ("news", "items", "articles", "headlines"):
            rows = _coerce_named_rows(news_data.get(key))
            if rows:
                return rows
        if "headline" in news_data or "title" in news_data:
            return [dict(news_data)]
        return []
    return _coerce_named_rows(news_data)


def _key_news_drivers(
    market_data: Mapping[str, Any],
    news_data: object,
) -> list[dict[str, Any]]:
    known_stocks = _known_symbols_and_names(market_data)
    known_sectors = _known_sectors(market_data)
    drivers = [
        _news_classification(item, known_stocks, known_sectors)
        for item in _news_items(news_data)
    ]
    return sorted(
        drivers,
        key=lambda row: (
            1 if row["classification"] == "sector" else 0,
            abs(float(row["sentimentScore"])),
        ),
        reverse=True,
    )


def build_assignment_intelligence(
    market_data: Mapping[str, Any] | None,
    historical_data: Mapping[str, Any] | None,
    news_data: object | None,
) -> dict[str, Any]:
    market_payload = _as_mapping(market_data)
    historical_payload = _as_mapping(historical_data)
    news_payload = news_data if news_data is not None else []
    return {
        "market_summary": _market_summary(market_payload),
        "sector_trends": _sector_trends(market_payload, historical_payload),
        "key_news_drivers": _key_news_drivers(market_payload, news_payload),
    }


def _read_json(path: Path) -> object:
    if not path.exists():
        return {} if path.name != NEWS_FILE else []
    return json.loads(path.read_text(encoding="utf-8"))


def build_assignment_intelligence_from_files(
    base_path: str | Path = ".",
    market_file: str = MARKET_FILE,
    historical_file: str = HISTORICAL_FILE,
    news_file: str = NEWS_FILE,
) -> dict[str, Any]:
    base = Path(base_path)
    market_data = _read_json(base / market_file)
    historical_data = _read_json(base / historical_file)
    news_data = _read_json(base / news_file)
    return build_assignment_intelligence(
        _as_mapping(market_data),
        _as_mapping(historical_data),
        news_data,
    )


def _sector_mapping_lookup(
    sector_mapping_data: Mapping[str, Any] | None,
    market_data: Mapping[str, Any] | None = None,
) -> dict[str, list[str]]:
    sectors = _as_mapping((sector_mapping_data or {}).get("sectors"))
    lookup: dict[str, set[str]] = defaultdict(set)
    for sector, payload in sectors.items():
        normalized_sector = _normalize_sector(sector)
        for symbol in _as_sequence(_as_mapping(payload).get("stocks")):
            if _text(symbol):
                lookup[normalized_sector].add(_text(symbol).upper())

    for stock in _extract_stocks(_as_mapping(market_data)):
        symbol = _text(_first_present(stock, ("symbol", "stock", "ticker"))).upper()
        sector = _normalize_sector(_first_present(stock, ("sector", "sectorName", "industry")))
        if symbol and sector != "UNKNOWN":
            lookup[sector].add(symbol)
    return {sector: sorted(symbols) for sector, symbols in lookup.items()}


def _news_priority(row: Mapping[str, Any]) -> tuple[int, float]:
    impact_level = _text(_first_present(row, ("impact_level", "impactLevel"), "")).upper()
    rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(impact_level, 0)
    sentiment_score = abs(
        _safe_float(_first_present(row, ("sentiment_score", "sentimentScore", "score")))
    )
    return rank, sentiment_score


def _high_impact_news(news_data: object) -> list[dict[str, Any]]:
    news_items = _news_items(news_data)
    high_impact = [
        item
        for item in news_items
        if _text(_first_present(item, ("impact_level", "impactLevel"), "")).upper() == "HIGH"
    ]
    prioritized = high_impact or news_items
    return sorted(prioritized, key=_news_priority, reverse=True)


def _portfolio_stock_holdings(portfolio: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(_first_present(holding, ("symbol", "stock"), "UNKNOWN")).upper(): holding
        for holding in _portfolio_holdings(portfolio, "stocks")
        if _text(_first_present(holding, ("symbol", "stock"), "")).strip()
    }


def _stock_market_lookup(market_data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _text(_first_present(stock, ("symbol", "stock", "ticker"), _row_name(stock))).upper(): stock
        for stock in _extract_stocks(market_data)
    }


def _sectors_for_news(
    news_item: Mapping[str, Any],
    market_data: Mapping[str, Any],
    sector_mapping_data: Mapping[str, Any] | None,
) -> list[str]:
    known_sectors = sorted(
        {
            *_known_sectors(market_data),
            *[
                _normalize_sector(sector)
                for sector in _as_mapping((sector_mapping_data or {}).get("sectors"))
            ],
        }
    )
    entity_sectors, entity_stocks, _ = _entity_links(news_item)
    sectors = {_normalize_sector(sector) for sector in entity_sectors}
    stock_to_sector = _stock_sector_lookup(sector_mapping_data)
    stock_market = _stock_market_lookup(market_data)
    for symbol in entity_stocks:
        normalized_symbol = _text(symbol).upper()
        sector = stock_to_sector.get(normalized_symbol)
        if sector is None and normalized_symbol in stock_market:
            sector = _normalize_sector(
                _first_present(
                    stock_market[normalized_symbol],
                    ("sector", "sectorName", "industry"),
                )
            )
        if sector:
            sectors.add(_normalize_sector(sector))

    headline = _text(_first_present(news_item, ("headline", "title"), ""))
    summary = _text(_first_present(news_item, ("summary", "description", "body"), ""))
    if not sectors:
        sectors.update(
            _normalize_sector(sector)
            for sector in _linked_sectors(f"{headline} {summary}", known_sectors)
        )
    sectors.discard("UNKNOWN")
    return sorted(sectors)


def _stocks_for_sectors(
    sectors: Sequence[str],
    explicit_stocks: Sequence[str],
    market_data: Mapping[str, Any],
    sector_mapping_data: Mapping[str, Any] | None,
) -> list[str]:
    sector_lookup = _sector_mapping_lookup(sector_mapping_data, market_data)
    stocks = {_text(symbol).upper() for symbol in explicit_stocks if _text(symbol).strip()}
    for sector in sectors:
        stocks.update(sector_lookup.get(_normalize_sector(sector), []))
    return sorted(stocks)


def _sector_change(market_data: Mapping[str, Any], sector: str) -> float:
    sector_key = _normalize_sector(sector)
    for row in _extract_sectors(market_data):
        if _normalize_sector(_first_present(row, ("name", "sector", "symbol"))) == sector_key:
            return _change_pct(row)
    stocks = [
        stock
        for stock in _extract_stocks(market_data)
        if _normalize_sector(
            _first_present(stock, ("sector", "sectorName", "industry"))
        )
        == sector_key
    ]
    if not stocks:
        return 0.0
    return sum(_change_pct(stock) for stock in stocks) / len(stocks)


def _evidence_quality(
    news_item: Mapping[str, Any],
    sectors: Sequence[str],
    impacted_holdings: Sequence[Mapping[str, Any]],
    causal_factors: Sequence[str],
) -> str:
    if (
        _text(_first_present(news_item, ("impact_level", "impactLevel"), "")).upper() == "HIGH"
        and sectors
        and impacted_holdings
        and causal_factors
    ):
        return "strong"
    if sectors and impacted_holdings:
        return "moderate"
    return "weak"


def _confidence_score(
    news_item: Mapping[str, Any],
    sectors: Sequence[str],
    impacted_holdings: Sequence[Mapping[str, Any]],
    causal_factors: Sequence[str],
    conflicts: Sequence[str],
    market_data: Mapping[str, Any],
) -> dict[str, Any]:
    sentiment_score = _safe_float(
        _first_present(news_item, ("sentiment_score", "sentimentScore", "score"))
    )
    impact_level = _text(_first_present(news_item, ("impact_level", "impactLevel"), "")).upper()
    impact_strength = {
        "HIGH": 0.95,
        "MEDIUM": 0.65,
        "LOW": 0.4,
    }.get(impact_level, 0.25)
    news_signal_strength = _clamp(abs(sentiment_score) * 0.55 + impact_strength * 0.45, 0, 1)
    sector_alignment = _alignment_score(
        _sign_label(sentiment_score),
        [_sign_label(_sector_change(market_data, sector)) for sector in sectors],
    )
    stock_alignment = _alignment_score(
        _sign_label(sentiment_score),
        [_sign_label(_holding_day_change(holding)) for holding in impacted_holdings],
    )
    exposure_pct = sum(_holding_weight(holding, 0.0) for holding in impacted_holdings)
    portfolio_exposure = _clamp(exposure_pct / 40.0, 0, 1)
    data_completeness = _data_completeness_score(
        news_item,
        sectors,
        impacted_holdings,
        causal_factors,
    )
    raw_score = (
        news_signal_strength * 25
        + sector_alignment * 20
        + stock_alignment * 20
        + portfolio_exposure * 20
        + data_completeness * 15
    )
    if conflicts:
        raw_score -= min(25, 10 + len(conflicts) * 5)
        raw_score = min(raw_score, 65)
    if data_completeness < 0.6:
        raw_score = min(raw_score, 55)
    if not causal_factors:
        raw_score = min(raw_score, 70)
    if not impacted_holdings:
        raw_score = min(raw_score, 45)

    score = _bucketed_percent_score(raw_score)
    return {
        "confidence_score": score,
        "confidence_label": _confidence_label(score),
        "confidence_factors": {
            "news_signal_strength": _bucketed_percent_score(news_signal_strength * 100),
            "sector_alignment": _bucketed_percent_score(sector_alignment * 100),
            "stock_alignment": _bucketed_percent_score(stock_alignment * 100),
            "portfolio_exposure": _bucketed_percent_score(portfolio_exposure * 100),
            "data_completeness": _bucketed_percent_score(data_completeness * 100),
        },
    }


def _alignment_score(news_sign: str, observed_signs: Sequence[str]) -> float:
    if news_sign == "neutral":
        return 0.55
    if not observed_signs:
        return 0.35
    scores = []
    for observed in observed_signs:
        if observed == "neutral":
            scores.append(0.55)
        elif observed == news_sign:
            scores.append(1.0)
        else:
            scores.append(0.0)
    return sum(scores) / len(scores)


def _data_completeness_score(
    news_item: Mapping[str, Any],
    sectors: Sequence[str],
    impacted_holdings: Sequence[Mapping[str, Any]],
    causal_factors: Sequence[str],
) -> float:
    impact_level = _text(_first_present(news_item, ("impact_level", "impactLevel"), "")).upper()
    sentiment_present = _first_present(
        news_item,
        ("sentiment_score", "sentimentScore", "score", "sentiment"),
    ) is not None
    checks = [
        bool(_text(_first_present(news_item, ("headline", "title"), ""))),
        impact_level in {"HIGH", "MEDIUM", "LOW"},
        sentiment_present,
        bool(sectors),
        bool(impacted_holdings),
        bool(causal_factors),
    ]
    return sum(1 for passed in checks if passed) / len(checks)


def _bucketed_percent_score(value: float) -> int:
    return int(round(_clamp(value, 0, 100) / 5) * 5)


def _confidence_label(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _evaluate_reasoning_quality(
    macro_event: Mapping[str, Any],
    sector_impact: Sequence[Mapping[str, Any]],
    stock_impact: Sequence[Mapping[str, Any]],
    portfolio_effect: Mapping[str, Any],
    evidence_quality: str,
    conflicts: Sequence[str],
    explanation_text: str,
    confidence_score: int,
) -> dict[str, Any]:
    causal_factors = _as_sequence(macro_event.get("causalFactors"))
    notes: list[str] = []
    score = 0
    if _text(macro_event.get("headline")) and causal_factors:
        score += 30
        notes.append("Causal completeness: macro event and provided causal factors are present.")
    else:
        score += 10 if _text(macro_event.get("headline")) else 0
        notes.append("Causal completeness: missing either the headline or causal factors.")
    if sector_impact and stock_impact and portfolio_effect.get("impactedStocks"):
        score += 40
        notes.append(
            "Correctness of links: event is mapped through sector, stock, "
            "and portfolio exposure."
        )
    else:
        score += 15 if sector_impact else 0
        score += 10 if stock_impact else 0
        score += 5 if portfolio_effect.get("impactedStocks") else 0
        notes.append(
            "Correctness of links: at least one sector, stock, or portfolio "
            "link is incomplete."
        )
    score += 10 if evidence_quality == "strong" else 5 if evidence_quality == "moderate" else 0
    if evidence_quality == "strong":
        notes.append("Causal completeness: evidence quality is strong for this fixture.")
    elif evidence_quality == "moderate":
        notes.append(
            "Causal completeness: evidence quality is moderate, so the chain remains qualified."
        )
    else:
        notes.append("Causal completeness: evidence is weak and should be treated as tentative.")
    clarity_terms = (
        "primarily because",
        "portfolio exposure",
        "Confidence score:",
    )
    if all(term in explanation_text for term in clarity_terms):
        score += 10
        notes.append(
            "Clarity: explanation states the move, causal driver, exposure, and confidence."
        )
    else:
        notes.append(
            "Clarity: explanation is missing one or more required human-readable elements."
        )
    if conflicts:
        score -= min(25, 12 + len(conflicts) * 6)
        notes.append("Confidence alignment: score is downgraded because signals conflict.")
    elif confidence_score >= 75 and evidence_quality == "strong":
        notes.append(
            "Confidence alignment: high confidence is supported by strong aligned evidence."
        )
    elif confidence_score < 50:
        notes.append(
            "Confidence alignment: low confidence matches incomplete or conflicting evidence."
        )
    else:
        notes.append(
            "Confidence alignment: confidence is moderate because evidence is usable "
            "but not decisive."
        )
    if evidence_quality == "weak":
        score = min(score, 45)
    return {
        "reasoning_quality_score": _bucketed_percent_score(score),
        "evaluation_notes": notes,
    }


def _conflicts_for_chain(
    sentiment_score: float,
    sectors: Sequence[str],
    impacted_holdings: Sequence[Mapping[str, Any]],
    market_data: Mapping[str, Any],
) -> list[str]:
    conflicts: list[str] = []
    news_sign = _sign_label(sentiment_score)
    for sector in sectors:
        sector_sign = _sign_label(_sector_change(market_data, sector))
        if news_sign != "neutral" and sector_sign != "neutral" and news_sign != sector_sign:
            conflicts.append(
                f"News sentiment is {news_sign}, but {sector} price action is {sector_sign}."
            )
    for holding in impacted_holdings:
        symbol = _text(holding.get("symbol"), "UNKNOWN").upper()
        holding_sign = _sign_label(_holding_day_change(holding))
        if news_sign != "neutral" and holding_sign != "neutral" and news_sign != holding_sign:
            conflicts.append(
                f"News sentiment is {news_sign}, but {symbol} contributed {holding_sign} PnL."
            )
    return conflicts


def _macro_event_payload(news_item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _text(news_item.get("id"), ""),
        "headline": _text(_first_present(news_item, ("headline", "title"), "Untitled news")),
        "sentiment": _text(
            news_item.get("sentiment"),
            _impact_label(_safe_float(news_item.get("sentiment_score"))),
        ),
        "sentimentScore": round(
            _safe_float(_first_present(news_item, ("sentiment_score", "sentimentScore", "score"))),
            3,
        ),
        "impactLevel": _text(_first_present(news_item, ("impact_level", "impactLevel"), "UNKNOWN")),
        "scope": _text(_first_present(news_item, ("scope",), "UNKNOWN")),
        "causalFactors": [
            _text(value)
            for value in _as_sequence(
                _first_present(news_item, ("causal_factors", "causalFactors"), [])
            )
            if _text(value)
        ],
    }


def _explanation_text(
    macro_event: Mapping[str, Any],
    sector_impact: Sequence[Mapping[str, Any]],
    stock_impact: Sequence[Mapping[str, Any]],
    portfolio_effect: Mapping[str, Any],
    evidence_quality: str,
    conflicts: Sequence[str],
    confidence_score: int,
    confidence_label: str,
) -> str:
    headline = _text(macro_event.get("headline"), "The event")
    direction = "fell" if _safe_float(portfolio_effect.get("contributionPct")) < 0 else "rose"
    primary_sector = _text(sector_impact[0].get("sector")) if sector_impact else "mapped sectors"
    sector_move = _safe_float(sector_impact[0].get("changePct")) if sector_impact else 0.0
    stocks = ", ".join(_text(row.get("symbol")) for row in stock_impact[:4]) or "mapped holdings"
    exposure = sum(_safe_float(row.get("portfolioWeightPct")) for row in stock_impact)
    contribution = _safe_float(portfolio_effect.get("contributionPct"))
    causal_factors = [*_as_sequence(macro_event.get("causalFactors"))]
    factor_text = f" The stated driver was: {causal_factors[0]}" if causal_factors else ""
    conflict_text = f" Uncertainty: {conflicts[0]}" if conflicts else ""
    weak_text = (
        " Evidence is weak, so treat this as a possible link rather than a firm cause."
        if evidence_quality == "weak"
        else ""
    )
    return (
        f"Your portfolio {direction} {abs(contribution):.3f}% primarily because "
        f"{headline} affected {primary_sector}, where the sector moved {sector_move:+.2f}%. "
        f"The key affected holdings were {stocks}, representing {exposure:.2f}% portfolio exposure."
        f"{factor_text} Confidence score: {confidence_score}/100 ({confidence_label})."
        f"{conflict_text}{weak_text}"
    )


def build_assignment_causal_reasoning(
    news_data: object | None,
    sector_mapping_data: Mapping[str, Any] | None,
    market_data: Mapping[str, Any] | None,
    portfolios_data: Mapping[str, Any] | None,
    portfolio_id: str,
    max_events: int = 5,
) -> dict[str, Any]:
    market_payload = _as_mapping(market_data)
    portfolios = _extract_portfolios(_as_mapping(portfolios_data))
    portfolio = portfolios.get(portfolio_id)
    if portfolio is None:
        return {
            "portfolioId": portfolio_id,
            "causal_reasoning": [],
            "risk_flags": [
                {
                    "type": "missing_portfolio",
                    "severity": "high",
                    "message": "Portfolio was not found in the provided mock data.",
                }
            ],
        }

    portfolio_value = _safe_float(_first_present(portfolio, ("current_value", "currentValue")))
    portfolio_holdings = _portfolio_stock_holdings(portfolio)
    market_stocks = _stock_market_lookup(market_payload)
    chains: list[dict[str, Any]] = []

    for news_item in _high_impact_news(news_data or []):
        macro_event = _macro_event_payload(news_item)
        entity_sectors, entity_stocks, _ = _entity_links(news_item)
        sectors = _sectors_for_news(news_item, market_payload, sector_mapping_data)
        stocks = _stocks_for_sectors(sectors, entity_stocks, market_payload, sector_mapping_data)
        impacted_symbols = [symbol for symbol in stocks if symbol in portfolio_holdings]
        impacted_holdings = [portfolio_holdings[symbol] for symbol in impacted_symbols]
        if not impacted_holdings:
            continue

        sector_impact = [
            {
                "sector": sector,
                "changePct": round(_sector_change(market_payload, sector), 3),
                "sentimentAlignment": _impact_label(_safe_float(macro_event["sentimentScore"])),
                "mappedStocks": [
                    symbol
                    for symbol in _stocks_for_sectors(
                        [sector],
                        [],
                        market_payload,
                        sector_mapping_data,
                    )
                    if symbol in stocks
                ],
            }
            for sector in sectors
        ]
        stock_impact = []
        contribution_abs = 0.0
        for symbol in impacted_symbols:
            holding = portfolio_holdings[symbol]
            market_stock = market_stocks.get(symbol, {})
            contribution = _holding_day_change(holding)
            contribution_abs += contribution
            stock_impact.append(
                {
                    "symbol": symbol,
                    "sector": _normalize_sector(
                        _first_present(
                            holding,
                            ("sector",),
                            _first_present(
                                market_stock,
                                ("sector", "sectorName", "industry"),
                                "UNKNOWN",
                            ),
                        )
                    ),
                    "portfolioWeightPct": round(_holding_weight(holding, portfolio_value), 3),
                    "stockChangePct": round(
                        _safe_float(
                            _first_present(
                                market_stock,
                                ("change_percent", "changePct", "day_change_percent"),
                                _first_present(
                                    holding,
                                    ("day_change_percent", "change_percent", "dayChangePercent"),
                                    0.0,
                                ),
                            )
                        ),
                        3,
                    ),
                    "contributionAbsolute": round(contribution, 2),
                    "contributionPct": round(
                        contribution / portfolio_value * 100 if portfolio_value else 0.0,
                        4,
                    ),
                }
            )

        portfolio_effect = {
            "portfolioId": portfolio_id,
            "impactedStocks": impacted_symbols,
            "contributionAbsolute": round(contribution_abs, 2),
            "contributionPct": round(
                contribution_abs / portfolio_value * 100 if portfolio_value else 0.0,
                4,
            ),
            "portfolioValue": round(portfolio_value, 2),
        }
        causal_factors = list(macro_event["causalFactors"])
        sentiment_score = _safe_float(macro_event["sentimentScore"])
        conflicts = _conflicts_for_chain(
            sentiment_score,
            sectors,
            impacted_holdings,
            market_payload,
        )
        evidence_quality = _evidence_quality(news_item, sectors, impacted_holdings, causal_factors)
        confidence_payload = _confidence_score(
            news_item,
            sectors,
            impacted_holdings,
            causal_factors,
            conflicts,
            market_payload,
        )
        explanation_text = _explanation_text(
            macro_event,
            sector_impact,
            stock_impact,
            portfolio_effect,
            evidence_quality,
            conflicts,
            int(confidence_payload["confidence_score"]),
            str(confidence_payload["confidence_label"]),
        )
        evaluation_payload = _evaluate_reasoning_quality(
            macro_event,
            sector_impact,
            stock_impact,
            portfolio_effect,
            evidence_quality,
            conflicts,
            explanation_text,
            int(confidence_payload["confidence_score"]),
        )
        chain = {
            "macro_event": macro_event,
            "sector_impact": sector_impact,
            "stock_impact": stock_impact,
            "portfolio_effect": portfolio_effect,
            "explanation_text": explanation_text,
            **confidence_payload,
            "confidenceScore": round(float(confidence_payload["confidence_score"]) / 100, 2),
            **evaluation_payload,
            "evidence_quality": evidence_quality,
            "conflicting_signals": conflicts,
            "weak_evidence": evidence_quality == "weak",
        }
        chains.append(chain)

    chains.sort(
        key=lambda item: (
            abs(float(item["portfolio_effect"]["contributionAbsolute"])),
            _news_priority(item["macro_event"]),
        ),
        reverse=True,
    )
    return {
        "portfolioId": portfolio_id,
        "causal_reasoning": chains[:max_events],
    }


def build_assignment_causal_reasoning_from_files(
    base_path: str | Path = ".",
    portfolio_id: str = "PORTFOLIO_001",
    news_file: str = NEWS_FILE,
    sector_mapping_file: str = SECTOR_MAPPING_FILE,
    market_file: str = MARKET_FILE,
    portfolios_file: str = PORTFOLIOS_FILE,
) -> dict[str, Any]:
    base = Path(base_path)
    return build_assignment_causal_reasoning(
        news_data=_read_json(base / news_file),
        sector_mapping_data=_as_mapping(_read_json(base / sector_mapping_file)),
        market_data=_as_mapping(_read_json(base / market_file)),
        portfolios_data=_as_mapping(_read_json(base / portfolios_file)),
        portfolio_id=portfolio_id,
    )


def _extract_portfolios(portfolios_data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = portfolios_data.get("portfolios", portfolios_data)
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): _as_row(value) for key, value in raw.items()}


def _extract_mutual_funds(mutual_funds_data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = mutual_funds_data.get("mutual_funds", mutual_funds_data)
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): _as_row(value) for key, value in raw.items()}


def _stock_sector_lookup(sector_mapping_data: Mapping[str, Any] | None = None) -> dict[str, str]:
    sectors = _as_mapping((sector_mapping_data or {}).get("sectors"))
    lookup: dict[str, str] = {}
    for sector, payload in sectors.items():
        for symbol in _as_sequence(_as_mapping(payload).get("stocks")):
            lookup[_text(symbol).upper()] = _normalize_sector(sector)
    return lookup


def _portfolio_holdings(portfolio: Mapping[str, Any], asset_type: str) -> list[dict[str, Any]]:
    holdings = _as_mapping(portfolio.get("holdings"))
    return [_as_row(item) for item in _as_sequence(holdings.get(asset_type))]


def _holding_value(row: Mapping[str, Any]) -> float:
    return _safe_float(
        _first_present(row, ("current_value", "market_value", "value", "currentValue"))
    )


def _holding_weight(row: Mapping[str, Any], total_value: float) -> float:
    explicit = _first_present(row, ("weight_in_portfolio", "weight", "portfolioWeight"))
    if explicit is not None:
        return _safe_float(explicit)
    if total_value <= 0:
        return 0.0
    return _holding_value(row) / total_value * 100


def _holding_day_change(row: Mapping[str, Any]) -> float:
    explicit = _first_present(row, ("day_change", "dayChange", "daily_pnl", "dailyPnl"))
    if explicit is not None:
        return _safe_float(explicit)
    return _holding_value(row) * _safe_float(
        _first_present(row, ("day_change_percent", "dayChangePercent", "change_percent"))
    ) / 100


def _fund_sector_allocation(
    fund: Mapping[str, Any],
    fallback_holdings: Sequence[Any],
    stock_sector_lookup: Mapping[str, str],
) -> dict[str, float]:
    raw_allocation = _as_mapping(fund.get("sector_allocation"))
    if raw_allocation:
        return {
            _normalize_sector(sector): _safe_float(weight)
            for sector, weight in raw_allocation.items()
            if _safe_float(weight) != 0
        }

    allocation: dict[str, float] = defaultdict(float)
    top_holdings = _as_sequence(fund.get("top_holdings")) or list(fallback_holdings)
    equal_weight = 100 / max(len(top_holdings), 1)
    for item in top_holdings:
        if isinstance(item, Mapping):
            symbol = _text(_first_present(item, ("stock", "symbol", "name"))).upper()
            sector = _normalize_sector(
                _first_present(item, ("sector",), stock_sector_lookup.get(symbol, "UNKNOWN"))
            )
            weight = _safe_float(_first_present(item, ("weight", "allocation")), equal_weight)
        else:
            symbol = _text(item).upper()
            sector = stock_sector_lookup.get(symbol, "UNKNOWN")
            weight = equal_weight
        allocation[_normalize_sector(sector)] += weight
    return dict(allocation)


def _fund_top_holding_exposure(
    fund: Mapping[str, Any],
    portfolio_weight: float,
    fallback_holdings: Sequence[Any],
    stock_sector_lookup: Mapping[str, str],
) -> list[dict[str, Any]]:
    top_holdings = _as_sequence(fund.get("top_holdings")) or list(fallback_holdings)
    if not top_holdings:
        return []
    equal_weight = 100 / len(top_holdings)
    exposures = []
    for item in top_holdings:
        if isinstance(item, Mapping):
            symbol = _text(_first_present(item, ("stock", "symbol", "name"), "UNKNOWN")).upper()
            fund_weight = _safe_float(_first_present(item, ("weight", "allocation")), equal_weight)
            sector = _normalize_sector(
                _first_present(item, ("sector",), stock_sector_lookup.get(symbol, "UNKNOWN"))
            )
        else:
            symbol = _text(item, "UNKNOWN").upper()
            fund_weight = equal_weight
            sector = stock_sector_lookup.get(symbol, "UNKNOWN")
        exposures.append(
            {
                "symbol": symbol,
                "sector": _normalize_sector(sector),
                "fundWeightPct": round(fund_weight, 3),
                "portfolioLookThroughPct": round(portfolio_weight * fund_weight / 100, 3),
            }
        )
    return exposures


def _empty_portfolio_payload(portfolio_id: str) -> dict[str, Any]:
    return {
        "portfolio_summary": {
            "portfolioId": portfolio_id,
            "userName": "Unknown",
            "currentValue": 0.0,
            "dailyPnlAbsolute": 0.0,
            "dailyPnlPercent": 0.0,
            "assetAllocation": {"DIRECT_STOCKS": 0.0, "MUTUAL_FUNDS": 0.0},
            "stockHoldingCount": 0,
            "mutualFundHoldingCount": 0,
        },
        "risk_flags": [
            {
                "type": "missing_portfolio",
                "severity": "high",
                "message": "Portfolio was not found in the provided mock data.",
            }
        ],
        "sector_exposure": [],
    }


def build_assignment_portfolio_analytics(
    portfolios_data: Mapping[str, Any] | None,
    mutual_funds_data: Mapping[str, Any] | None,
    portfolio_id: str,
    sector_mapping_data: Mapping[str, Any] | None = None,
    concentration_threshold: float = 40.0,
) -> dict[str, Any]:
    portfolios = _extract_portfolios(_as_mapping(portfolios_data))
    portfolio = portfolios.get(portfolio_id)
    if portfolio is None:
        return _empty_portfolio_payload(portfolio_id)

    mutual_funds = _extract_mutual_funds(_as_mapping(mutual_funds_data))
    sector_lookup = _stock_sector_lookup(sector_mapping_data)
    stock_holdings = _portfolio_holdings(portfolio, "stocks")
    fund_holdings = _portfolio_holdings(portfolio, "mutual_funds")
    total_value = _safe_float(_first_present(portfolio, ("current_value", "currentValue")))
    if total_value <= 0:
        total_value = sum(_holding_value(row) for row in [*stock_holdings, *fund_holdings])

    direct_sector_pct: dict[str, float] = defaultdict(float)
    direct_sector_value: dict[str, float] = defaultdict(float)
    fund_sector_pct: dict[str, float] = defaultdict(float)
    fund_sector_value: dict[str, float] = defaultdict(float)
    look_through_holdings: dict[str, list[dict[str, Any]]] = {}

    for holding in stock_holdings:
        symbol = _text(_first_present(holding, ("symbol", "stock"), "UNKNOWN")).upper()
        sector = _normalize_sector(
            _first_present(holding, ("sector",), sector_lookup.get(symbol, "UNKNOWN"))
        )
        weight = _holding_weight(holding, total_value)
        value = _holding_value(holding)
        direct_sector_pct[sector] += weight
        direct_sector_value[sector] += value

    for holding in fund_holdings:
        scheme_code = _text(_first_present(holding, ("scheme_code", "schemeCode"), "UNKNOWN"))
        fund = mutual_funds.get(scheme_code, {})
        fund_weight = _holding_weight(holding, total_value)
        fund_value = _holding_value(holding)
        fallback_top_holdings = _as_sequence(holding.get("top_holdings"))
        allocation = _fund_sector_allocation(fund, fallback_top_holdings, sector_lookup)
        allocation_total = sum(max(weight, 0.0) for weight in allocation.values()) or 100.0

        for sector, sector_weight in allocation.items():
            normalized_sector = _normalize_sector(sector)
            look_through_pct = fund_weight * sector_weight / allocation_total
            look_through_value = fund_value * sector_weight / allocation_total
            fund_sector_pct[normalized_sector] += look_through_pct
            fund_sector_value[normalized_sector] += look_through_value

        look_through_holdings[scheme_code] = _fund_top_holding_exposure(
            fund,
            fund_weight,
            fallback_top_holdings,
            sector_lookup,
        )

    sector_names = sorted({*direct_sector_pct, *fund_sector_pct})
    sector_exposure = [
        {
            "sector": sector,
            "directPct": round(direct_sector_pct.get(sector, 0.0), 3),
            "mutualFundLookThroughPct": round(fund_sector_pct.get(sector, 0.0), 3),
            "totalPct": round(
                direct_sector_pct.get(sector, 0.0) + fund_sector_pct.get(sector, 0.0),
                3,
            ),
            "directValue": round(direct_sector_value.get(sector, 0.0), 2),
            "mutualFundLookThroughValue": round(fund_sector_value.get(sector, 0.0), 2),
        }
        for sector in sector_names
    ]
    sector_exposure.sort(key=lambda row: float(row["totalPct"]), reverse=True)

    stock_value = sum(_holding_value(row) for row in stock_holdings)
    fund_value = sum(_holding_value(row) for row in fund_holdings)
    daily_pnl = sum(_holding_day_change(row) for row in [*stock_holdings, *fund_holdings])
    daily_pnl_pct = daily_pnl / total_value * 100 if total_value else 0.0
    asset_allocation = {
        "DIRECT_STOCKS": round(stock_value / total_value * 100, 3) if total_value else 0.0,
        "MUTUAL_FUNDS": round(fund_value / total_value * 100, 3) if total_value else 0.0,
    }

    risk_flags: list[dict[str, Any]] = []
    for exposure in sector_exposure:
        if float(exposure["totalPct"]) > concentration_threshold:
            risk_flags.append(
                {
                    "type": "sector_concentration",
                    "severity": "critical" if float(exposure["totalPct"]) > 70 else "high",
                    "sector": exposure["sector"],
                    "exposurePct": exposure["totalPct"],
                    "thresholdPct": concentration_threshold,
                    "message": (
                        f"{exposure['sector']} exposure is {exposure['totalPct']}%, "
                        f"above the {concentration_threshold:.0f}% threshold."
                    ),
                }
            )

    if not risk_flags:
        risk_flags.append(
            {
                "type": "concentration",
                "severity": "low",
                "message": "No sector exposure exceeds the concentration threshold.",
            }
        )

    return {
        "portfolio_summary": {
            "portfolioId": portfolio_id,
            "userName": _text(portfolio.get("user_name"), "Unknown"),
            "portfolioType": _text(portfolio.get("portfolio_type"), "UNKNOWN"),
            "riskProfile": _text(portfolio.get("risk_profile"), "UNKNOWN"),
            "currentValue": round(total_value, 2),
            "dailyPnlAbsolute": round(daily_pnl, 2),
            "dailyPnlPercent": round(daily_pnl_pct, 3),
            "assetAllocation": asset_allocation,
            "stockHoldingCount": len(stock_holdings),
            "mutualFundHoldingCount": len(fund_holdings),
            "mutualFundLookThroughHoldings": look_through_holdings,
        },
        "risk_flags": risk_flags,
        "sector_exposure": sector_exposure,
    }


def build_assignment_portfolio_analytics_from_files(
    base_path: str | Path = ".",
    portfolio_id: str = "PORTFOLIO_001",
    portfolios_file: str = PORTFOLIOS_FILE,
    mutual_funds_file: str = MUTUAL_FUNDS_FILE,
    sector_mapping_file: str = SECTOR_MAPPING_FILE,
) -> dict[str, Any]:
    base = Path(base_path)
    portfolios_data = _read_json(base / portfolios_file)
    mutual_funds_data = _read_json(base / mutual_funds_file)
    sector_mapping_data = _read_json(base / sector_mapping_file)
    return build_assignment_portfolio_analytics(
        _as_mapping(portfolios_data),
        _as_mapping(mutual_funds_data),
        portfolio_id=portfolio_id,
        sector_mapping_data=_as_mapping(sector_mapping_data),
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Build mock-data assignment intelligence.")
    parser.add_argument(
        "--base-path",
        default=".",
        help="Directory containing the three JSON files.",
    )
    parser.add_argument("--market-file", default=MARKET_FILE)
    parser.add_argument("--historical-file", default=HISTORICAL_FILE)
    parser.add_argument("--news-file", default=NEWS_FILE)
    parser.add_argument("--portfolio-id", default=None)
    parser.add_argument("--portfolios-file", default=PORTFOLIOS_FILE)
    parser.add_argument("--mutual-funds-file", default=MUTUAL_FUNDS_FILE)
    parser.add_argument("--sector-mapping-file", default=SECTOR_MAPPING_FILE)
    args = parser.parse_args()

    if args.portfolio_id:
        payload = build_assignment_portfolio_analytics_from_files(
            base_path=args.base_path,
            portfolio_id=args.portfolio_id,
            portfolios_file=args.portfolios_file,
            mutual_funds_file=args.mutual_funds_file,
            sector_mapping_file=args.sector_mapping_file,
        )
    else:
        payload = build_assignment_intelligence_from_files(
            base_path=args.base_path,
            market_file=args.market_file,
            historical_file=args.historical_file,
            news_file=args.news_file,
        )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
