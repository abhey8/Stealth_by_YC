from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .intelligence import (
    build_assignment_causal_reasoning,
    build_assignment_intelligence,
    build_assignment_portfolio_analytics,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _read_json(name: str) -> Any:
    path = DATA_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_inputs() -> dict[str, Any]:
    return {
        "market": _read_json("market_data.json"),
        "historical": _read_json("historical_data.json"),
        "news": _read_json("news_data.json"),
        "portfolios": _read_json("portfolios.json"),
        "mutual_funds": _read_json("mutual_funds.json"),
        "sector_mapping": _read_json("sector_mapping.json"),
    }


def _portfolio_rows(portfolios_data: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = portfolios_data.get("portfolios", portfolios_data)
    return rows if isinstance(rows, Mapping) else {}


def _stock_holdings(portfolio: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    holdings = portfolio.get("holdings", {})
    if not isinstance(holdings, Mapping):
        return []
    rows = holdings.get("stocks", [])
    return [row for row in rows if isinstance(row, Mapping)]


def _fund_holdings(portfolio: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    holdings = portfolio.get("holdings", {})
    if not isinstance(holdings, Mapping):
        return []
    rows = holdings.get("mutual_funds", [])
    return [row for row in rows if isinstance(row, Mapping)]


def _change_pct(row: Mapping[str, Any]) -> float:
    explicit = row.get("day_change_percent", row.get("change_percent"))
    if explicit is not None:
        return _safe_float(explicit)
    value = _safe_float(row.get("current_value"))
    change = _safe_float(row.get("day_change"))
    return change / value * 100 if value else 0.0


def _signal_from_change(change_pct: float) -> str:
    if change_pct >= 1.0:
        return "bullish"
    if change_pct <= -1.0:
        return "bearish"
    return "monitor"


def _confidence_label(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _money(value: float) -> str:
    return f"Rs. {value:,.0f}"


def _portfolio_day_pnl(portfolio: Mapping[str, Any]) -> float:
    return sum(
        _safe_float(row.get("day_change"))
        for row in [*_stock_holdings(portfolio), *_fund_holdings(portfolio)]
    )


def _top_holding_symbols(portfolio: Mapping[str, Any], limit: int = 3) -> list[str]:
    holdings = sorted(
        _stock_holdings(portfolio),
        key=lambda row: _safe_float(row.get("weight_in_portfolio")),
        reverse=True,
    )
    return [str(row.get("symbol", "UNKNOWN")) for row in holdings[:limit]]


def list_portfolios() -> list[dict[str, Any]]:
    inputs = _load_inputs()
    rows = _portfolio_rows(_as_mapping(inputs["portfolios"]))
    summaries: list[dict[str, Any]] = []
    for portfolio_id, portfolio in rows.items():
        analytics = build_assignment_portfolio_analytics(
            _as_mapping(inputs["portfolios"]),
            _as_mapping(inputs["mutual_funds"]),
            str(portfolio_id),
            _as_mapping(inputs["sector_mapping"]),
        )
        risk_flags = analytics.get("risk_flags", [])
        concentration = "Low concentration risk"
        if risk_flags and risk_flags[0].get("type") != "concentration":
            concentration = str(risk_flags[0].get("message", "High concentration risk"))
        summaries.append(
            {
                "id": str(portfolio_id),
                "name": str(portfolio.get("user_name", portfolio_id)),
                "totalValue": _safe_float(portfolio.get("current_value")),
                "dayPnl": _portfolio_day_pnl(portfolio),
                "concentrationRisk": concentration,
                "holdingCount": len(_stock_holdings(portfolio)) + len(_fund_holdings(portfolio)),
                "topHoldings": _top_holding_symbols(portfolio),
                "riskNotes": [str(flag.get("message", "")) for flag in risk_flags[:3]],
            }
        )
    return summaries


def get_market_brief() -> dict[str, Any]:
    inputs = _load_inputs()
    intelligence = build_assignment_intelligence(
        _as_mapping(inputs["market"]),
        _as_mapping(inputs["historical"]),
        inputs["news"],
    )
    market_summary = intelligence["market_summary"]
    sector_trends = intelligence["sector_trends"]
    news_drivers = intelligence["key_news_drivers"]
    score = abs(_safe_float(market_summary.get("score"))) * 100
    confidence = 80 if score >= 35 else 60 if score >= 15 else 45
    headline = f"Market sentiment is {market_summary['sentiment']}"
    risks = [
        f"{row['sector']} trend is {row['trend']} ({row['score']:+.2f})"
        for row in sector_trends
        if row.get("trend") == "negative"
    ][:3]
    opportunities = [
        {
            "symbol": str(row["sector"]),
            "signalState": "bullish" if row.get("trend") == "positive" else "monitor",
            "confidenceScore": abs(_safe_float(row.get("score"))),
            "regime": str(row.get("trend")),
            "thesisSummary": ", ".join(row.get("drivers", [])[:2]) or "Sector trend from mock data",
        }
        for row in sector_trends
        if row.get("trend") == "positive"
    ][:3]
    return {
        "asOf": datetime.now(UTC).isoformat(),
        "regime": str(market_summary["sentiment"]),
        "confidenceLabel": _confidence_label(confidence),
        "headline": headline,
        "summary": "; ".join(market_summary.get("drivers", []))
        or "Market sentiment is derived from provided index moves.",
        "keyRisks": risks,
        "opportunities": opportunities,
        "events": [
            {
                "headline": str(row["headline"]),
                "eventType": str(row["classification"]),
                "sentiment": _safe_float(row["sentimentScore"]),
                "uncertainty": 1 - min(abs(_safe_float(row["sentimentScore"])), 1),
            }
            for row in news_drivers[:5]
        ],
        "macro": [
            {
                "label": str(row["name"]),
                "value": f"{_safe_float(row['lastPrice']):,.2f}",
                "delta": f"{_safe_float(row['changePct']):+.2f}%",
                "trend": "up" if _safe_float(row["changePct"]) > 0 else "down",
            }
            for row in market_summary.get("indices", [])[:5]
        ],
        **intelligence,
    }


def analyze_portfolio(portfolio_id: str) -> dict[str, Any]:
    started = time.perf_counter()
    inputs = _load_inputs()
    portfolios = _portfolio_rows(_as_mapping(inputs["portfolios"]))
    portfolio = portfolios.get(portfolio_id)
    if portfolio is None:
        raise KeyError(portfolio_id)

    intelligence = build_assignment_intelligence(
        _as_mapping(inputs["market"]),
        _as_mapping(inputs["historical"]),
        inputs["news"],
    )
    analytics = build_assignment_portfolio_analytics(
        _as_mapping(inputs["portfolios"]),
        _as_mapping(inputs["mutual_funds"]),
        portfolio_id,
        _as_mapping(inputs["sector_mapping"]),
    )
    causal = build_assignment_causal_reasoning(
        inputs["news"],
        _as_mapping(inputs["sector_mapping"]),
        _as_mapping(inputs["market"]),
        _as_mapping(inputs["portfolios"]),
        portfolio_id,
    )

    summary = analytics["portfolio_summary"]
    chains = causal.get("causal_reasoning", [])
    primary_chain = chains[0] if chains else None
    holdings = _build_holding_analysis(portfolio, chains)
    overview_counts = {
        "bullishCount": sum(1 for row in holdings if row["signalState"] == "bullish"),
        "bearishCount": sum(1 for row in holdings if row["signalState"] == "bearish"),
        "monitorCount": sum(1 for row in holdings if row["signalState"] == "monitor"),
        "mixedCount": sum(1 for row in holdings if row["signalState"] == "mixed"),
        "abstainCount": sum(1 for row in holdings if row["signalState"] == "abstain"),
    }
    confidence = _portfolio_confidence(chains, analytics)
    reasoning_quality = _portfolio_reasoning_quality(chains)
    pnl_pct = _safe_float(summary.get("dailyPnlPercent"))
    direction = "fell" if pnl_pct < 0 else "rose" if pnl_pct > 0 else "was flat"
    if primary_chain:
        narrative = primary_chain["explanation_text"]
    else:
        top_sector = analytics["sector_exposure"][0] if analytics["sector_exposure"] else {}
        narrative = (
            f"Your portfolio {direction} {abs(pnl_pct):.3f}% based on the provided holdings. "
            f"The largest exposure is {top_sector.get('sector', 'unknown')}, representing "
            f"{_safe_float(top_sector.get('totalPct')):.2f}% of the portfolio. "
            f"Confidence score: {confidence}/100 ({_confidence_label(confidence)})."
        )

    return {
        "portfolioId": portfolio_id,
        "portfolioName": str(portfolio.get("user_name", portfolio_id)),
        "analyzedAt": datetime.now(UTC).isoformat(),
        "totalValue": _safe_float(summary.get("currentValue")),
        "dayPnl": _safe_float(summary.get("dailyPnlAbsolute")),
        "dayPnlPercent": pnl_pct,
        "concentrationRisk": _concentration_text(analytics),
        "marketRegime": str(intelligence["market_summary"]["sentiment"]),
        "portfolioNarrative": narrative,
        "confidence_score": confidence,
        "confidence_label": _confidence_label(confidence),
        "reasoning_quality_score": reasoning_quality,
        "evaluation_notes": _evaluation_notes(chains, confidence),
        "recommendedActions": _recommended_actions(analytics, chains),
        "overview": {
            **overview_counts,
            "topRisks": [str(flag.get("message", "")) for flag in analytics["risk_flags"][:5]],
        },
        "holdings": holdings,
        "portfolio_summary": summary,
        "risk_flags": analytics["risk_flags"],
        "sector_exposure": analytics["sector_exposure"],
        "market_summary": intelligence["market_summary"],
        "sector_trends": intelligence["sector_trends"],
        "key_news_drivers": intelligence["key_news_drivers"],
        "causal_reasoning": chains,
        "trace": {
            "inputs": [
                "market_data.json",
                "historical_data.json",
                "news_data.json",
                "portfolios.json",
                "mutual_funds.json",
                "sector_mapping.json",
            ],
            "latencyMs": round((time.perf_counter() - started) * 1000, 2),
        },
    }


def chat_with_advisor(message: str, portfolio_id: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    cleaned_message = " ".join(message.split())
    if not cleaned_message:
        return {
            "message": "",
            "answer": "Please ask a finance question about the provided market, news, or portfolio data.",
            "intent": "empty",
            "portfolioId": portfolio_id,
            "suggestedPrompts": _chat_suggestions(portfolio_id),
            "trace": {
                "inputs": [
                    "market_data.json",
                    "historical_data.json",
                    "news_data.json",
                    "portfolios.json",
                    "mutual_funds.json",
                    "sector_mapping.json",
                ],
                "latencyMs": round((time.perf_counter() - started) * 1000, 2),
            },
        }

    inputs = _load_inputs()
    portfolios = _portfolio_rows(_as_mapping(inputs["portfolios"]))
    resolved_portfolio_id = _resolve_portfolio_id(cleaned_message, portfolio_id, portfolios)
    analysis = analyze_portfolio(resolved_portfolio_id) if resolved_portfolio_id else None
    market_brief = get_market_brief()
    intent = _detect_chat_intent(cleaned_message)
    answer, bullets = _chat_answer(intent, cleaned_message, analysis, market_brief)

    return {
        "message": cleaned_message,
        "answer": answer,
        "intent": intent,
        "portfolioId": resolved_portfolio_id,
        "bullets": bullets,
        "suggestedPrompts": _chat_suggestions(resolved_portfolio_id),
        "trace": {
            "inputs": [
                "market_data.json",
                "historical_data.json",
                "news_data.json",
                "portfolios.json",
                "mutual_funds.json",
                "sector_mapping.json",
            ],
            "latencyMs": round((time.perf_counter() - started) * 1000, 2),
        },
    }


def _build_holding_analysis(
    portfolio: Mapping[str, Any],
    chains: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    holdings: list[dict[str, Any]] = []
    chain_by_symbol: dict[str, Mapping[str, Any]] = {}
    for chain in chains:
        for row in chain.get("stock_impact", []):
            if isinstance(row, Mapping):
                chain_by_symbol[str(row.get("symbol", "")).upper()] = chain

    for holding in _stock_holdings(portfolio):
        symbol = str(holding.get("symbol", "UNKNOWN")).upper()
        change = _change_pct(holding)
        signal = _signal_from_change(change)
        chain = chain_by_symbol.get(symbol)
        confidence = int(chain.get("confidence_score", 45)) if chain else 45
        thesis = (
            str(chain.get("explanation_text", ""))
            if chain
            else f"{symbol} moved {change:+.2f}% in the provided mock data."
        )
        holdings.append(
            {
                "symbol": symbol,
                "name": str(holding.get("name", symbol)),
                "sector": str(holding.get("sector", "UNKNOWN")),
                "quantity": _safe_float(holding.get("quantity")),
                "weight": _safe_float(holding.get("weight_in_portfolio")),
                "currentPrice": _safe_float(holding.get("current_price")),
                "dayChangePct": change,
                "horizon": "1D",
                "signalState": signal,
                "directionalBias": "bullish" if change > 0 else "bearish" if change < 0 else "mixed",
                "advisorAction": "watch" if signal == "monitor" else "hold" if signal == "bullish" else "reduce",
                "confidenceScore": confidence / 100,
                "confidenceLabel": _confidence_label(confidence),
                "confidence_score": confidence,
                "confidence_label": _confidence_label(confidence),
                "reasoning_quality_score": int(chain.get("reasoning_quality_score", 55)) if chain else 55,
                "evaluation_notes": list(chain.get("evaluation_notes", []))[:3] if chain else [],
                "regime": signal,
                "thesisSummary": thesis,
                "actionSummary": f"{symbol}: {signal} signal from day move and causal exposure.",
                "topDrivers": [str(item) for item in chain.get("macro_event", {}).get("causalFactors", [])[:3]]
                if chain
                else [],
                "riskFlags": [str(item) for item in chain.get("conflicting_signals", [])[:3]]
                if chain
                else [],
                "invalidationConditions": [],
                "intelligence": {
                    "ruleAgreement": 1 if chain else 0.5,
                    "regimeStability": 0.7,
                    "mlTrustScore": 0.0,
                    "featureCompleteness": 0.9 if chain else 0.6,
                    "eventClarity": confidence / 100,
                },
            }
        )
    return sorted(holdings, key=lambda row: row["weight"], reverse=True)


def _resolve_portfolio_id(
    message: str,
    explicit_portfolio_id: str | None,
    portfolios: Mapping[str, Any],
) -> str | None:
    if explicit_portfolio_id and explicit_portfolio_id in portfolios:
        return explicit_portfolio_id
    match = re.search(r"portfolio[\s_-]*(\d{1,3})", message, flags=re.IGNORECASE)
    if match:
        candidate = f"PORTFOLIO_{int(match.group(1)):03d}"
        if candidate in portfolios:
            return candidate
    upper_message = message.upper()
    for candidate in portfolios:
        if candidate in upper_message:
            return candidate
    return explicit_portfolio_id if explicit_portfolio_id in portfolios else None


def _detect_chat_intent(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("why", "cause", "explain", "driver", "impact", "affected")):
        return "causal_explanation"
    if any(token in lowered for token in ("p&l", "pnl", "profit", "loss", "fell", "rose", "down", "up")):
        return "pnl"
    if any(token in lowered for token in ("concentration", "risk", "risky", "overexposed")):
        return "risk"
    if any(token in lowered for token in ("sector", "allocation", "exposure", "look-through", "look through")):
        return "allocation"
    if any(token in lowered for token in ("confidence", "quality", "reliable", "certainty")):
        return "confidence"
    if any(token in lowered for token in ("market", "nifty", "sensex", "sentiment", "brief")):
        return "market"
    if any(token in lowered for token in ("news", "headline", "rbi", "driver")):
        return "news"
    return "overview"


def _chat_answer(
    intent: str,
    message: str,
    analysis: Mapping[str, Any] | None,
    market_brief: Mapping[str, Any],
) -> tuple[str, list[str]]:
    if intent == "market":
        market_summary = _as_mapping(market_brief.get("market_summary"))
        sector_trends = market_brief.get("sector_trends", [])
        lead_sector = sector_trends[0] if sector_trends else {}
        answer = (
            f"Market sentiment is {market_summary.get('sentiment', 'neutral')}. "
            f"The average index move in the provided data is "
            f"{_safe_float(market_summary.get('averageIndexChangePct')):+.2f}%. "
            f"The strongest sector trend is {lead_sector.get('sector', 'not available')} "
            f"with a score of {_safe_float(_as_mapping(lead_sector).get('score')):+.2f}."
        )
        bullets = [
            str(market_brief.get("headline", "Market brief unavailable.")),
            str(market_brief.get("summary", "No additional market summary available.")),
        ]
        return answer, bullets

    if analysis is None:
        return (
            "I can answer market-level questions immediately, but portfolio-specific questions need a valid portfolio context such as PORTFOLIO_001, PORTFOLIO_002, or PORTFOLIO_003.",
            _chat_suggestions(None),
        )

    summary = _as_mapping(analysis.get("portfolio_summary"))
    sector_exposure = analysis.get("sector_exposure", [])
    risk_flags = analysis.get("risk_flags", [])
    chains = analysis.get("causal_reasoning", [])
    top_chain = chains[0] if chains else {}
    top_sector = sector_exposure[0] if sector_exposure else {}
    portfolio_name = str(analysis.get("portfolioName", analysis.get("portfolioId", "This portfolio")))
    pnl_pct = _safe_float(analysis.get("dayPnlPercent"))
    pnl_abs = _safe_float(analysis.get("dayPnl"))
    direction = "fell" if pnl_pct < 0 else "rose" if pnl_pct > 0 else "was flat"

    if intent == "pnl":
        answer = (
            f"{portfolio_name} {direction} {abs(pnl_pct):.3f}% today, which is "
            f"{_money(pnl_abs)} on a portfolio value of {_money(_safe_float(analysis.get('totalValue')))}. "
            f"This is calculated by summing the day change of every stock and mutual fund holding."
        )
        bullets = [
            f"Absolute daily P&L: {_money(pnl_abs)}",
            f"Daily P&L %: {pnl_pct:+.3f}%",
            f"Asset split: direct stocks { _safe_float(_as_mapping(summary.get('assetAllocation')).get('DIRECT_STOCKS')):.2f}% | mutual funds { _safe_float(_as_mapping(summary.get('assetAllocation')).get('MUTUAL_FUNDS')):.2f}%",
        ]
        return answer, bullets

    if intent == "risk":
        primary_flag = risk_flags[0] if risk_flags else {}
        answer = (
            f"The main risk signal for {portfolio_name} is "
            f"{primary_flag.get('message', 'no concentration breach detected')}. "
            f"Current confidence in this assessment is {analysis.get('confidence_score', 0)}/100."
        )
        bullets = [
            str(flag.get("message", "")) for flag in risk_flags[:3]
        ] or ["No major risk flags were found."]
        return answer, bullets

    if intent == "allocation":
        answer = (
            f"The largest sector exposure in {portfolio_name} is {top_sector.get('sector', 'not available')} "
            f"at {_safe_float(_as_mapping(top_sector).get('totalPct')):.2f}% of the portfolio. "
            f"This includes direct holdings plus mutual fund look-through exposure."
        )
        bullets = [
            (
                f"{row.get('sector')}: total {_safe_float(_as_mapping(row).get('totalPct')):.2f}% "
                f"(direct {_safe_float(_as_mapping(row).get('directPct')):.2f}%, "
                f"MF look-through {_safe_float(_as_mapping(row).get('mutualFundLookThroughPct')):.2f}%)"
            )
            for row in sector_exposure[:4]
        ]
        return answer, bullets

    if intent == "confidence":
        answer = (
            f"The portfolio explanation confidence is {analysis.get('confidence_score', 0)}/100 "
            f"({analysis.get('confidence_label', 'unknown')}). "
            f"The reasoning quality score is {analysis.get('reasoning_quality_score', 0)}/100."
        )
        bullets = [str(note) for note in analysis.get("evaluation_notes", [])[:4]]
        return answer, bullets

    if intent == "news":
        events = market_brief.get("events", [])
        lead_event = events[0] if events else {}
        answer = (
            f"The top market news driver in the provided data is "
            f"{lead_event.get('headline', 'not available')}. "
            f"Its classified sentiment score is {_safe_float(_as_mapping(lead_event).get('sentiment')):+.2f}."
        )
        bullets = [
            str(row.get("headline", "")) for row in market_brief.get("key_news_drivers", [])[:4]
        ] or ["No news drivers available."]
        return answer, bullets

    if intent == "causal_explanation":
        if top_chain:
            bullets = [
                f"Macro: {str(_as_mapping(top_chain.get('macro_event')).get('headline', ''))}",
                f"Sectors: {', '.join(str(row.get('sector')) for row in top_chain.get('sector_impact', [])[:3]) or 'None'}",
                f"Stocks: {', '.join(str(row.get('symbol')) for row in top_chain.get('stock_impact', [])[:4]) or 'None'}",
                f"Portfolio effect: {_safe_float(_as_mapping(top_chain.get('portfolio_effect')).get('contributionPct')):+.3f}%",
            ]
            return str(top_chain.get("explanation_text", analysis.get("portfolioNarrative", ""))), bullets
        return (
            f"{portfolio_name} has no strong causal chain in the provided data, so the best available summary is: {analysis.get('portfolioNarrative', '')}",
            ["No high-impact news item intersected strongly with the current holdings."],
        )

    answer = (
        f"{portfolio_name} {direction} {abs(pnl_pct):.3f}% today. "
        f"The top sector exposure is {top_sector.get('sector', 'not available')} at "
        f"{_safe_float(_as_mapping(top_sector).get('totalPct')):.2f}%, and the current explanation confidence is "
        f"{analysis.get('confidence_score', 0)}/100."
    )
    bullets = [
        str(analysis.get("portfolioNarrative", "")),
        f"Top risk: {risk_flags[0].get('message', 'None') if risk_flags else 'None'}",
        f"Reasoning quality: {analysis.get('reasoning_quality_score', 0)}/100",
    ]
    return answer, bullets


def _chat_suggestions(portfolio_id: str | None) -> list[str]:
    suffix = f" for {portfolio_id}" if portfolio_id else ""
    return [
        f"Why did my portfolio move{suffix}?",
        f"What is the concentration risk{suffix}?",
        f"Show sector exposure{suffix}.",
        "What is the market sentiment today?",
    ]


def _concentration_text(analytics: Mapping[str, Any]) -> str:
    flags = analytics.get("risk_flags", [])
    if flags and flags[0].get("type") != "concentration":
        return str(flags[0].get("message", "High concentration risk"))
    return "No sector exceeds the 40% concentration threshold."


def _portfolio_confidence(chains: list[Mapping[str, Any]], analytics: Mapping[str, Any]) -> int:
    if not chains:
        return 45
    weighted = sum(_safe_float(chain.get("confidence_score")) for chain in chains)
    score = round(weighted / len(chains))
    if any(flag.get("type") == "sector_concentration" for flag in analytics.get("risk_flags", [])):
        score = min(95, score + 5)
    return int(max(0, min(100, round(score / 5) * 5)))


def _portfolio_reasoning_quality(chains: list[Mapping[str, Any]]) -> int:
    if not chains:
        return 45
    return int(
        round(
            sum(_safe_float(chain.get("reasoning_quality_score")) for chain in chains)
            / len(chains)
            / 5
        )
        * 5
    )


def _evaluation_notes(chains: list[Mapping[str, Any]], confidence: int) -> list[str]:
    if not chains:
        return ["Reasoning quality is limited because no causal chain matched portfolio holdings."]
    notes = list(chains[0].get("evaluation_notes", []))[:3]
    notes.append(f"Confidence alignment: portfolio score is {confidence}/100 after aggregation.")
    return notes


def _recommended_actions(
    analytics: Mapping[str, Any],
    chains: list[Mapping[str, Any]],
) -> list[str]:
    actions: list[str] = []
    for flag in analytics.get("risk_flags", []):
        if flag.get("type") == "sector_concentration":
            actions.append(f"Review concentration in {flag.get('sector')}.")
    if chains:
        actions.append("Prioritize the highest-impact causal chain before making allocation changes.")
    if not actions:
        actions.append("Monitor the portfolio; no high concentration breach was detected.")
    return actions
