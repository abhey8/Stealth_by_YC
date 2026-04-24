function apiBase() {
  if (process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL;
  }

  if (typeof window !== "undefined" && window.location.hostname.endsWith(".onrender.com")) {
    return "https://stealth-advisor-backend.onrender.com";
  }

  return "";
}

export type PortfolioSummary = {
  id: string;
  name: string;
  totalValue: number;
  dayPnl: number;
  concentrationRisk: string;
  holdingCount: number;
  topHoldings: string[];
  riskNotes: string[];
};

export type MarketBrief = {
  regime: string;
  confidenceLabel: string;
  headline: string;
  summary: string;
  keyRisks: string[];
  events: Array<{
    headline: string;
    eventType: string;
    sentiment: number;
    uncertainty: number;
  }>;
  macro: Array<{
    label: string;
    value: string;
    delta: string;
    trend: "up" | "down" | "flat";
  }>;
  market_summary: {
    sentiment: string;
    score: number;
    averageIndexChangePct: number;
  };
  sector_trends: Array<{
    sector: string;
    trend: string;
    score: number;
    sectorChangePct: number;
    drivers: string[];
  }>;
  key_news_drivers: Array<{
    headline: string;
    classification: string;
    impact: string;
    affectedSectors: string[];
    affectedStocks: string[];
  }>;
};

export type PortfolioAnalysis = {
  portfolioId: string;
  portfolioName: string;
  totalValue: number;
  dayPnl: number;
  dayPnlPercent: number;
  concentrationRisk: string;
  marketRegime: string;
  portfolioNarrative: string;
  confidence_score: number;
  confidence_label: string;
  reasoning_quality_score: number;
  evaluation_notes: string[];
  recommendedActions: string[];
  overview: {
    bullishCount: number;
    bearishCount: number;
    monitorCount: number;
    mixedCount: number;
    abstainCount: number;
    topRisks: string[];
  };
  holdings: Array<{
    symbol: string;
    name: string;
    sector: string;
    weight: number;
    dayChangePct: number;
    signalState: string;
    thesisSummary: string;
    confidence_score: number;
  }>;
  risk_flags: Array<{
    type: string;
    severity: string;
    sector?: string;
    exposurePct?: number;
    message: string;
  }>;
  sector_exposure: Array<{
    sector: string;
    directPct: number;
    mutualFundLookThroughPct: number;
    totalPct: number;
  }>;
  causal_reasoning: Array<{
    macro_event: {
      headline: string;
      impactLevel: string;
      causalFactors: string[];
    };
    sector_impact: Array<{
      sector: string;
      changePct: number;
    }>;
    stock_impact: Array<{
      symbol: string;
      portfolioWeightPct: number;
      contributionPct: number;
    }>;
    portfolio_effect: {
      contributionPct: number;
      impactedStocks: string[];
    };
    explanation_text: string;
    confidence_score: number;
    confidence_label: string;
    reasoning_quality_score: number;
    conflicting_signals: string[];
  }>;
};

export type ChatResponse = {
  message: string;
  answer: string;
  intent: string;
  portfolioId?: string | null;
  bullets: string[];
  suggestedPrompts: string[];
  trace: {
    latencyMs: number;
    inputs: string[];
  };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  portfolios: () => request<PortfolioSummary[]>("/advisor/portfolios"),
  marketBrief: () => request<MarketBrief>("/advisor/market-brief"),
  analyze: (portfolioId: string) =>
    request<PortfolioAnalysis>(`/advisor/analyze/${portfolioId}`, { method: "POST" }),
  chat: (message: string, portfolioId?: string) =>
    request<ChatResponse>("/advisor/chat", {
      method: "POST",
      body: JSON.stringify({ message, portfolio_id: portfolioId })
    })
};
