"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Clock3,
  Database,
  Moon,
  RefreshCw,
  Send,
  ShieldCheck,
  SunMedium,
  TrendingDown,
  TrendingUp
} from "lucide-react";
import { api, ChatResponse, MarketBrief, PortfolioAnalysis, PortfolioSummary } from "../lib/api";

type LoadState = "loading" | "ready" | "error";
type ThemeMode = "dark" | "light";
type ChatTurn = {
  role: "user" | "assistant";
  text: string;
  bullets?: string[];
  suggestions?: string[];
  latencyMs?: number;
};

function money(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0
  }).format(value);
}

function signedPercent(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function tone(value: number) {
  if (value > 0) return "positive";
  if (value < 0) return "negative";
  return "muted";
}

function confidenceTone(label: string) {
  if (label === "high") return "positive";
  if (label === "low") return "warning";
  return "info";
}

function sentenceCase(value: string) {
  if (!value) return "Not available";
  return value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}

function splitRisk(text: string) {
  const [sector, ...rest] = text.split(" exposure is ");
  if (!rest.length) return text;
  return `${sector}: ${rest.join(" exposure is ")}`;
}

function Metric({
  label,
  value,
  helper,
  toneName = "text"
}: {
  label: string;
  value: string;
  helper?: string;
  toneName?: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={toneName}>{value}</strong>
      {helper ? <small>{helper}</small> : null}
    </div>
  );
}

function Panel({
  title,
  meta,
  children,
  className = ""
}: {
  title: string;
  meta?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-title">
        <h2>{title}</h2>
        {meta ? <span>{meta}</span> : null}
      </div>
      {children}
    </section>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="empty-state">{children}</div>;
}

export function AdvisorDashboard() {
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [brief, setBrief] = useState<MarketBrief | null>(null);
  const [analysis, setAnalysis] = useState<PortfolioAnalysis | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [error, setError] = useState("");
  const [theme, setTheme] = useState<ThemeMode>("dark");
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatTurn[]>([]);

  useEffect(() => {
    const stored = window.localStorage.getItem("advisor-theme");
    const preferred: ThemeMode =
      stored === "light" || stored === "dark"
        ? stored
        : window.matchMedia("(prefers-color-scheme: light)").matches
          ? "light"
          : "dark";
    setTheme(preferred);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("advisor-theme", theme);
  }, [theme]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [portfolioRows, marketBrief] = await Promise.all([
          api.portfolios(),
          api.marketBrief()
        ]);
        if (!active) return;
        setPortfolios(portfolioRows);
        setSelectedId(portfolioRows[0]?.id ?? "");
        setBrief(marketBrief);
        setLoadState("ready");
      } catch (exc) {
        if (!active) return;
        setError(String(exc));
        setLoadState("error");
      }
    }
    load();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!portfolios.length || chatHistory.length) return;
    setChatHistory([
      {
        role: "assistant",
        text: "Ask about market sentiment, portfolio impact, concentration risk, sector exposure, or why a selected portfolio moved.",
        suggestions: [
          "Why did my portfolio move?",
          "What is the concentration risk?",
          "Show sector exposure.",
          "What is the market sentiment today?"
        ]
      }
    ]);
  }, [portfolios, chatHistory.length]);

  async function runAnalysis(portfolioId = selectedId) {
    if (!portfolioId) return;
    setError("");
    setAnalysisLoading(true);
    try {
      const payload = await api.analyze(portfolioId);
      setAnalysis(payload);
      setSelectedId(portfolioId);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setAnalysisLoading(false);
    }
  }

  async function sendChatMessage(prompt = chatInput.trim()) {
    const message = prompt.trim();
    if (!message || chatLoading) return;

    setError("");
    setChatLoading(true);
    setChatInput("");
    setChatHistory((current) => [...current, { role: "user", text: message }]);

    try {
      const payload = await api.chat(message, selectedId || undefined);
      setChatHistory((current) => [...current, mapChatResponse(payload)]);
      if (payload.portfolioId && payload.portfolioId !== selectedId) {
        setSelectedId(payload.portfolioId);
      }
    } catch (exc) {
      const detail = String(exc);
      setError(detail);
      setChatHistory((current) => [
        ...current,
        {
          role: "assistant",
          text: "The chat agent could not complete that request. Please retry after checking the backend connection.",
          bullets: [detail]
        }
      ]);
    } finally {
      setChatLoading(false);
    }
  }

  const selectedPortfolio = portfolios.find((portfolio) => portfolio.id === selectedId);
  const primaryChain = analysis?.causal_reasoning[0];
  const sectorExposure = analysis?.sector_exposure ?? [];
  const maxExposure = useMemo(
    () => Math.max(...sectorExposure.map((row) => row.totalPct), 1),
    [sectorExposure]
  );
  const topHoldings = analysis?.holdings.slice(0, 8) ?? [];
  const topDrivers = brief?.events.slice(0, 5) ?? [];
  const dayPnl = analysis?.dayPnl ?? selectedPortfolio?.dayPnl ?? 0;
  const portfolioValue = analysis?.totalValue ?? selectedPortfolio?.totalValue ?? 0;

  if (loadState === "loading") {
    return (
      <main className="center-screen">
        <RefreshCw className="spin" />
        <h1>Loading portfolio intelligence</h1>
        <p>Fetching market context, portfolios, and risk signals.</p>
      </main>
    );
  }

  if (loadState === "error") {
    return (
      <main className="center-screen">
        <AlertTriangle className="warning" />
        <h1>Data connection unavailable</h1>
        <p>Start the backend from <code>Backend</code>, then refresh this page.</p>
        <pre>{error}</pre>
      </main>
    );
  }

  return (
    <main className="terminal">
      <aside className="portfolio-rail">
        <div className="product-mark">
          <span>Portfolio Intelligence</span>
          <strong>Financial Advisor Dashboard</strong>
        </div>

        <div className="rail-section">
          <div className="rail-heading">Portfolios</div>
          <div className="portfolio-list">
            {portfolios.map((portfolio) => (
              <button
                key={portfolio.id}
                className={portfolio.id === selectedId ? "portfolio-item active" : "portfolio-item"}
                onClick={() => {
                  setSelectedId(portfolio.id);
                  setAnalysis(null);
                }}
              >
                <span>
                  <strong>{portfolio.name}</strong>
                  <small>{portfolio.id}</small>
                </span>
                <b className={tone(portfolio.dayPnl)}>{money(portfolio.dayPnl)}</b>
              </button>
            ))}
          </div>
        </div>

        <div className="trust-panel">
          <div>
            <Database />
            <span>Data source</span>
            <strong>Local mock data</strong>
          </div>
          <div>
            <Clock3 />
            <span>Freshness</span>
            <strong>Provided fixtures</strong>
          </div>
          <div>
            <ShieldCheck />
            <span>Review mode</span>
            <strong>No external keys</strong>
          </div>
        </div>
      </aside>

      <section className="content">
        <header className="topbar">
          <div>
            <span className="screen-label">Dashboard</span>
            <h1>{analysis?.portfolioName ?? selectedPortfolio?.name ?? "Portfolio Analysis"}</h1>
            <p>Market context, sector exposure, key drivers, and portfolio impact.</p>
          </div>
          <div className="top-actions">
            <div className="market-chip">
              <span>Market sentiment</span>
              <strong className={confidenceTone(brief?.confidenceLabel ?? "medium")}>
                {sentenceCase(brief?.market_summary.sentiment ?? "neutral")}
              </strong>
            </div>
            <button
              type="button"
              className="theme-toggle"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              {theme === "dark" ? <SunMedium /> : <Moon />}
              <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
            </button>
            <button onClick={() => runAnalysis()} disabled={analysisLoading || !selectedId}>
              {analysisLoading ? "Running..." : "Run Analysis"}
            </button>
          </div>
        </header>

        {error ? <div className="error-banner">{error}</div> : null}

        <section className="summary-strip">
          <Metric label="Portfolio value" value={money(portfolioValue)} helper={selectedId} />
          <Metric
            label="Day P&L"
            value={money(dayPnl)}
            helper={analysis ? signedPercent(analysis.dayPnlPercent) : "Awaiting analysis"}
            toneName={tone(dayPnl)}
          />
          <Metric
            label="Portfolio impact"
            value={
              primaryChain
                ? signedPercent(primaryChain.portfolio_effect.contributionPct)
                : analysis
                  ? signedPercent(analysis.dayPnlPercent)
                  : "Pending"
            }
            helper={primaryChain ? "Top causal contribution" : "Run analysis"}
            toneName={tone(primaryChain?.portfolio_effect.contributionPct ?? dayPnl)}
          />
          <Metric
            label="Confidence"
            value={analysis ? `${analysis.confidence_score}/100` : "Pending"}
            helper={analysis ? sentenceCase(analysis.confidence_label) : "Evidence score"}
            toneName={confidenceTone(analysis?.confidence_label ?? "medium")}
          />
        </section>

        <section className="main-grid">
          <Panel title="Analyst Brief" meta={analysis ? "Structured explanation" : "Pending"}>
            {analysis ? (
              <div className="brief-grid">
                <BriefRow
                  label="Macro context"
                  value={primaryChain?.macro_event.headline ?? brief?.headline ?? "No major event mapped"}
                />
                <BriefRow
                  label="Sector impact"
                  value={
                    primaryChain?.sector_impact[0]
                      ? `${primaryChain.sector_impact[0].sector} moved ${signedPercent(
                          primaryChain.sector_impact[0].changePct
                        )}`
                      : analysis.marketRegime
                  }
                />
                <BriefRow
                  label="Stock impact"
                  value={
                    primaryChain?.portfolio_effect.impactedStocks.length
                      ? primaryChain.portfolio_effect.impactedStocks.slice(0, 5).join(", ")
                      : topHoldings.slice(0, 4).map((holding) => holding.symbol).join(", ")
                  }
                />
                <BriefRow
                  label="Portfolio effect"
                  value={`${money(analysis.dayPnl)} day P&L (${signedPercent(
                    analysis.dayPnlPercent
                  )})`}
                  toneName={tone(analysis.dayPnl)}
                />
                <BriefRow
                  label="Risk note"
                  value={splitRisk(analysis.overview.topRisks[0] ?? analysis.concentrationRisk)}
                  toneName="warning"
                />
              </div>
            ) : (
              <EmptyState>Select a portfolio and run analysis to view the structured brief.</EmptyState>
            )}
          </Panel>

          <Panel title="Confidence & Risk" meta={analysis ? "Evidence quality" : "Pending"}>
            {analysis ? (
              <div className="risk-stack">
                <ScoreRow label="Confidence" value={analysis.confidence_score} toneName="info" />
                <ScoreRow
                  label="Evidence quality"
                  value={analysis.reasoning_quality_score}
                  toneName="positive"
                />
                <div className="risk-list">
                  {analysis.overview.topRisks.slice(0, 3).map((risk) => (
                    <div key={risk}>{splitRisk(risk)}</div>
                  ))}
                  {analysis.evaluation_notes.slice(0, 2).map((note) => (
                    <div key={note}>{note}</div>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState>Risk signals and confidence appear after analysis.</EmptyState>
            )}
          </Panel>
        </section>

        <section className="secondary-grid">
          <Panel title="Market Context" meta="Index moves">
            <div className="compact-table">
              {brief?.macro.map((point) => (
                <div className="table-row" key={point.label}>
                  <span>{point.label}</span>
                  <strong>{point.value}</strong>
                  <b className={point.trend === "up" ? "positive" : "negative"}>{point.delta}</b>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Key Sector Moves" meta="Exposure view">
            {sectorExposure.length ? (
              <div className="sector-list">
                {sectorExposure.slice(0, 7).map((row) => (
                  <div className="sector-row" key={row.sector}>
                    <div className="sector-row-top">
                      <span>{row.sector}</span>
                      <strong>{row.totalPct.toFixed(1)}%</strong>
                    </div>
                    <div className="sector-meta">
                      Direct {row.directPct.toFixed(1)}% · MF look-through{" "}
                      {row.mutualFundLookThroughPct.toFixed(1)}%
                    </div>
                    <div className="bar-track">
                      <div style={{ width: `${(row.totalPct / maxExposure) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState>Sector exposure appears after analysis.</EmptyState>
            )}
          </Panel>
        </section>

        <section className="secondary-grid wide-left">
          <Panel title="Holdings Affected" meta="Portfolio impact">
            {topHoldings.length ? (
              <div className="holdings-table">
                <div className="holdings-head">
                  <span>Symbol</span>
                  <span>Sector</span>
                  <span>Weight</span>
                  <span>Day move</span>
                  <span>Signal</span>
                </div>
                {topHoldings.map((holding) => (
                  <div className="holdings-row" key={holding.symbol}>
                    <strong>{holding.symbol}</strong>
                    <span>{holding.sector}</span>
                    <span>{holding.weight.toFixed(1)}%</span>
                    <b className={tone(holding.dayChangePct)}>{signedPercent(holding.dayChangePct)}</b>
                    <span>{sentenceCase(holding.signalState)}</span>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState>Holding impact appears after analysis.</EmptyState>
            )}
          </Panel>

          <Panel title="Top Drivers" meta="News and signals">
            <div className="driver-list">
              {primaryChain ? (
                <div className="driver primary-driver">
                  <strong>{primaryChain.macro_event.headline}</strong>
                  <span>
                    {primaryChain.macro_event.impactLevel} impact ·{" "}
                    {primaryChain.portfolio_effect.impactedStocks.join(", ")}
                  </span>
                </div>
              ) : null}
              {topDrivers.slice(0, primaryChain ? 3 : 5).map((event) => (
                <div className="driver" key={event.headline}>
                  <strong>{event.headline}</strong>
                  <span>
                    {event.eventType} · sentiment{" "}
                    <b className={tone(event.sentiment)}>{event.sentiment.toFixed(2)}</b>
                  </span>
                </div>
              ))}
            </div>
          </Panel>
        </section>

        <section className="secondary-grid wide-left">
          <Panel title="Advisor Chat" meta="Grounded Q&A over the provided data" className="chat-panel">
            <div className="chat-thread">
              {chatHistory.map((turn, index) => (
                <div
                  className={turn.role === "assistant" ? "chat-bubble assistant" : "chat-bubble user"}
                  key={`${turn.role}-${index}-${turn.text.slice(0, 20)}`}
                >
                  <div className="chat-role">
                    <span>{turn.role === "assistant" ? "Advisor" : "You"}</span>
                    {turn.latencyMs ? <small>{turn.latencyMs.toFixed(1)} ms</small> : null}
                  </div>
                  <strong>{turn.text}</strong>
                  {turn.bullets?.length ? (
                    <div className="chat-bullets">
                      {turn.bullets.map((bullet) => (
                        <span key={bullet}>{bullet}</span>
                      ))}
                    </div>
                  ) : null}
                  {turn.suggestions?.length ? (
                    <div className="chat-suggestions">
                      {turn.suggestions.map((suggestion) => (
                        <button
                          key={suggestion}
                          type="button"
                          onClick={() => sendChatMessage(suggestion)}
                          disabled={chatLoading}
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
              {chatLoading ? <div className="chat-status">Analyzing the provided fixtures...</div> : null}
            </div>

            <form
              className="chat-composer"
              onSubmit={(event) => {
                event.preventDefault();
                void sendChatMessage();
              }}
            >
              <input
                type="text"
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                placeholder={
                  selectedId
                    ? `Ask about ${selectedId}, market sentiment, or key drivers`
                    : "Ask about market sentiment, risks, or sectors"
                }
              />
              <button type="submit" disabled={chatLoading || !chatInput.trim()}>
                <Send />
                <span>{chatLoading ? "Working..." : "Ask"}</span>
              </button>
            </form>
          </Panel>

          <Panel title="Suggested Questions" meta={selectedId || "Global market"}>
            <div className="driver-list">
              {[
                `Why did ${selectedId || "my portfolio"} move today?`,
                `What is the concentration risk in ${selectedId || "the selected portfolio"}?`,
                `Show sector exposure for ${selectedId || "the selected portfolio"}.`,
                "What is the market sentiment today?",
                "Which news events matter the most right now?"
              ].map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="prompt-card"
                  onClick={() => sendChatMessage(prompt)}
                  disabled={chatLoading}
                >
                  <strong>{prompt}</strong>
                  <span>Grounded in the current assignment data and portfolio context.</span>
                </button>
              ))}
            </div>
          </Panel>
        </section>
      </section>
    </main>
  );
}

function mapChatResponse(payload: ChatResponse): ChatTurn {
  return {
    role: "assistant",
    text: payload.answer,
    bullets: payload.bullets,
    suggestions: payload.suggestedPrompts,
    latencyMs: payload.trace.latencyMs
  };
}

function BriefRow({
  label,
  value,
  toneName = "text"
}: {
  label: string;
  value: string;
  toneName?: string;
}) {
  return (
    <div className="brief-row">
      <span>{label}</span>
      <strong className={toneName}>{value}</strong>
    </div>
  );
}

function ScoreRow({
  label,
  value,
  toneName
}: {
  label: string;
  value: number;
  toneName: string;
}) {
  return (
    <div className="score-row">
      <div>
        <span>{label}</span>
        <strong className={toneName}>{value}/100</strong>
      </div>
      <div className="score-track">
        <div className={toneName} style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}
