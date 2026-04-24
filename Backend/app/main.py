from __future__ import annotations

from pydantic import BaseModel
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .service import analyze_portfolio, chat_with_advisor, get_market_brief, list_portfolios


class ChatRequest(BaseModel):
    message: str
    portfolio_id: str | None = None

app = FastAPI(title="Autonomous Financial Advisor Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/advisor/portfolios")
def advisor_portfolios() -> list[dict]:
    return list_portfolios()


@app.post("/advisor/analyze/{portfolio_id}")
def advisor_analyze(portfolio_id: str) -> dict:
    try:
        return analyze_portfolio(portfolio_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio not found") from exc


@app.get("/advisor/market-brief")
def advisor_market_brief() -> dict:
    return get_market_brief()


@app.post("/advisor/chat")
def advisor_chat(payload: ChatRequest) -> dict:
    try:
        return chat_with_advisor(payload.message, payload.portfolio_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Portfolio not found") from exc
