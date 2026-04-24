from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_portfolios_endpoint_lists_mock_portfolios() -> None:
    response = client.get("/advisor/portfolios")

    assert response.status_code == 200
    payload = response.json()
    assert payload
    assert {row["id"] for row in payload} >= {"PORTFOLIO_001", "PORTFOLIO_002"}


def test_portfolio_two_detects_banking_concentration_and_causal_chain() -> None:
    response = client.post("/advisor/analyze/PORTFOLIO_002")

    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolioId"] == "PORTFOLIO_002"
    assert payload["confidence_score"] >= 50
    assert any(flag["type"] == "sector_concentration" for flag in payload["risk_flags"])
    assert any("RBI" in chain["macro_event"]["headline"] for chain in payload["causal_reasoning"])
    assert "primarily because" in payload["portfolioNarrative"]


def test_market_brief_contains_assignment_schema() -> None:
    response = client.get("/advisor/market-brief")

    assert response.status_code == 200
    payload = response.json()
    assert {"market_summary", "sector_trends", "key_news_drivers"} <= set(payload)
    assert payload["market_summary"]["sentiment"] in {"bullish", "bearish", "neutral"}


def test_chat_endpoint_answers_portfolio_causal_question() -> None:
    response = client.post(
        "/advisor/chat",
        json={
            "message": "Why did Portfolio 2 fall today?",
            "portfolio_id": "PORTFOLIO_002",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "causal_explanation"
    assert payload["portfolioId"] == "PORTFOLIO_002"
    assert "portfolio" in payload["answer"].lower()
    assert payload["bullets"]


def test_chat_endpoint_answers_market_question_without_portfolio() -> None:
    response = client.post(
        "/advisor/chat",
        json={"message": "What is the market sentiment right now?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "market"
    assert "market sentiment" in payload["answer"].lower()
