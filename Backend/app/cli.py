from __future__ import annotations

import argparse
import json

from .service import analyze_portfolio, chat_with_advisor, get_market_brief


def main() -> None:
    parser = argparse.ArgumentParser(description="Run advisor analysis from local mock data.")
    parser.add_argument("portfolio_id", nargs="?", default="PORTFOLIO_002")
    parser.add_argument("--ask", default=None, help="Ask a natural-language question.")
    args = parser.parse_args()

    if args.ask:
        print(
            json.dumps(
                chat_with_advisor(args.ask, args.portfolio_id),
                indent=2,
            )
        )
        return

    payload = {
        "market_summary": get_market_brief()["market_summary"],
        "analysis": analyze_portfolio(args.portfolio_id),
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
