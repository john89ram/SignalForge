"""Stage 2 seven-test HP sieve.

Each Stage 2 test is deliberately isolated as its own class with a `run(...)`
method so individual rules can be debugged, replaced, or tuned without touching
runner/orchestration code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol

from screener import TickerAnalysis

STARTING_HP = 10
PASS = "PASS"
WEAK = "WEAK"
BAD = "BAD"
SKIP = "SKIP"

BINARY_BAD_KEYWORDS = [
    "fda decision",
    "pdufa",
    "m&a vote",
    "merger vote",
    "acquisition vote",
    "legal ruling",
    "court ruling",
    "regulatory investigation",
    "sec investigation",
]
BINARY_WEAK_KEYWORDS = ["rumor", "product launch", "analyst day", "conference", "keynote"]
CATALYST_PASS_KEYWORDS = [
    "earnings",
    "guidance",
    "partnership",
    "contract",
    "sector",
    "market volatility",
    "upgrade",
    "revenue",
]
MEME_KEYWORDS = ["reddit", "meme", "squeeze", "robinhood", "retail"]
NEWS_BAD_KEYWORDS = [
    "ceo departure",
    "resigns",
    "major customer loss",
    "regulatory investigation",
    "debt downgrade",
    "fraud",
    "going concern",
]
NEWS_WEAK_KEYWORDS = ["downgrade", "miss", "cuts target", "negative", "proxy", "insider selling"]


@dataclass(frozen=True)
class Stage2TestResult:
    name: str
    status: str
    detail: str
    score: float
    hp_loss: int

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "score": self.score,
            "hp_loss": self.hp_loss,
        }


class Stage2Test(Protocol):
    name: str

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> Stage2TestResult:
        ...


def result(name: str, status: str, detail: str) -> Stage2TestResult:
    hp_loss = {PASS: 0, WEAK: 1, BAD: 2, SKIP: 0}[status]
    score = {PASS: 1.0, WEAK: 0.5, BAD: 0.0, SKIP: 0.0}[status]
    return Stage2TestResult(name=name, status=status, detail=detail, score=score, hp_loss=hp_loss)


def _headlines(analysis: TickerAnalysis) -> str:
    return " | ".join(str(item.get("headline", "")).lower() for item in analysis.quote.news[:10])


def _pct_change(new: float, old: float) -> Optional[float]:
    if old == 0:
        return None
    return (new / old) - 1.0


class IVSpikeDiagnosisTest:
    name = "iv spike diagnosis"

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> Stage2TestResult:
        headlines = _headlines(analysis)
        price_history = price_history or []
        if any(keyword in headlines for keyword in BINARY_BAD_KEYWORDS):
            return result(self.name, BAD, "True binary/non-earnings event found in headlines")
        if len(price_history) >= 2:
            day_move = _pct_change(price_history[-1], price_history[-2])
            if day_move is not None and day_move <= -0.30:
                return result(self.name, BAD, "Panic crash of 30%+ detected")
        if len(price_history) >= 20:
            month_move = _pct_change(price_history[-1], price_history[-20])
            if month_move is not None and month_move >= 0.50 and "rumor" in headlines:
                return result(self.name, BAD, "50%+ surge on unconfirmed rumor")
        if any(keyword in headlines for keyword in BINARY_WEAK_KEYWORDS):
            return result(self.name, WEAK, "Mixed/partial catalyst signal in headlines")
        if headlines and any(keyword in headlines for keyword in CATALYST_PASS_KEYWORDS):
            return result(self.name, PASS, "Elevated IV has a visible fundamental/sector catalyst")
        return result(self.name, PASS, "No binary IV-spike cause detected")


class MemeStockTest:
    name = "meme stock"

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> Stage2TestResult:
        q = analysis.quote
        headlines = _headlines(analysis)
        tells: List[str] = []
        if any(keyword in headlines for keyword in MEME_KEYWORDS):
            tells.append("meme/retail headline language")
        if q.inst_own is not None and q.inst_own < 30:
            tells.append("low institutional ownership")
        if q.eps_next_y is not None and q.eps_next_y <= 0:
            tells.append("weak/negative forward EPS")
        price_history = price_history or []
        if len(price_history) >= 20:
            move = _pct_change(price_history[-1], price_history[-20])
            if move is not None and move >= 0.50:
                tells.append("50%+ recent rally")
        if len(tells) >= 3:
            return result(self.name, BAD, "3+ meme signals: " + ", ".join(tells))
        if len(tells) == 2:
            return result(self.name, WEAK, "2 meme signals: " + ", ".join(tells))
        return result(self.name, PASS, "0-1 meme signals")


class ChartPatternTest:
    name = "chart pattern"

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> Stage2TestResult:
        q = analysis.quote
        price = q.price
        history = price_history or []
        if price is not None and q.week_52_high and price >= q.week_52_high * 0.995:
            return result(self.name, BAD, "At/new 52-week high")
        if len(history) >= 20:
            move = _pct_change(history[-1], history[-20])
            if move is not None and move >= 0.50:
                return result(self.name, BAD, "50%+ rally in the past month")
        if price is not None and q.sma200 and price < q.sma200:
            return result(self.name, BAD, "Broke 200-day moving average")
        if price is not None and q.sma50 and price < q.sma50:
            return result(self.name, WEAK, "Broke 50-day moving average but not 200-day")
        if len(history) >= 2:
            day_move = abs(_pct_change(history[-1], history[-2]) or 0.0)
            if day_move >= 0.15:
                return result(self.name, WEAK, "Single large gap event")
        if price is not None and q.week_52_high and q.week_52_low:
            position = (price - q.week_52_low) / (q.week_52_high - q.week_52_low)
            if position >= 0.70:
                return result(self.name, WEAK, "Upper portion of 52-week range")
        return result(self.name, PASS, "Consolidating/steady chart; no extension or breakdown detected")


class NewsSentimentTest:
    name = "news sentiment"

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> Stage2TestResult:
        headlines = _headlines(analysis)
        if any(keyword in headlines for keyword in NEWS_BAD_KEYWORDS):
            return result(self.name, BAD, "Major negative headline risk detected")
        if any(keyword in headlines for keyword in NEWS_WEAK_KEYWORDS):
            return result(self.name, WEAK, "Minor/isolated negative news flow")
        return result(self.name, PASS, "Neutral or positive recent news flow")


class AnalystConsensusTest:
    name = "analyst consensus"

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> Stage2TestResult:
        q = analysis.quote
        if q.price is None or q.target_price is None or q.price <= 0:
            return result(self.name, SKIP, "Analyst target/price unavailable")
        upside = (q.target_price / q.price) - 1.0
        recom_sell = q.recom is not None and q.recom >= 4.0
        if recom_sell or upside < 0:
            return result(self.name, BAD, f"Sell/negative consensus or target below price ({upside:.1%})")
        if upside < 0.20:
            return result(self.name, WEAK, f"Hold/modest upside profile ({upside:.1%})")
        return result(self.name, PASS, f"Constructive target upside ({upside:.1%})")


class LiquidityTest:
    name = "liquidity"

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> Stage2TestResult:
        q = analysis.quote
        o = analysis.options
        spread = o.atm_bid_ask_spread
        volume = o.total_volume
        oi = o.total_open_interest
        if q.market_cap is not None and q.market_cap < 1_000_000_000:
            return result(self.name, BAD, "Market cap dropped below $1B")
        if spread is None or volume is None or oi is None:
            return result(self.name, SKIP, "Liquidity fields incomplete")
        if spread > 0.25 or volume <= 1_500 or oi < 2_000:
            return result(self.name, BAD, f"Execution impaired: spread ${spread:.2f}, volume {volume:,}, OI {oi:,}")
        if spread >= 0.10 or volume < 5_000 or oi < 10_000:
            return result(self.name, WEAK, f"Borderline liquidity: spread ${spread:.2f}, volume {volume:,}, OI {oi:,}")
        return result(self.name, PASS, f"Clean liquidity: spread ${spread:.2f}, volume {volume:,}, OI {oi:,}")


class InstitutionalOwnershipTest:
    name = "institutional ownership"

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> Stage2TestResult:
        q = analysis.quote
        if q.inst_own is None:
            return result(self.name, SKIP, "Institutional ownership unavailable")
        if q.inst_own < 30:
            return result(self.name, BAD, f"Institutional ownership below 30% ({q.inst_own:.1f}%)")
        if q.inst_own <= 50:
            return result(self.name, WEAK, f"Institutional ownership 30-50% ({q.inst_own:.1f}%)")
        if q.insider_trans is not None and q.insider_trans <= -20:
            return result(self.name, BAD, f"Insider selling spike ({q.insider_trans:.1f}%)")
        return result(self.name, PASS, f"Institutional ownership above 50% ({q.inst_own:.1f}%)")


def hp_tier(hp_left: int) -> str:
    if hp_left >= 9:
        return "Diamond"
    if hp_left >= 7:
        return "Strong"
    if hp_left >= 5:
        return "Standard"
    if hp_left >= 3:
        return "Watch"
    return "Eliminated"


class Stage2Sieve:
    def __init__(self, tests: Optional[List[Stage2Test]] = None) -> None:
        self.tests: List[Stage2Test] = tests or [
            IVSpikeDiagnosisTest(),
            MemeStockTest(),
            ChartPatternTest(),
            NewsSentimentTest(),
            AnalystConsensusTest(),
            LiquidityTest(),
            InstitutionalOwnershipTest(),
        ]

    def run(self, analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> TickerAnalysis:
        results = [test.run(analysis, price_history=price_history) for test in self.tests]
        hp_left = max(0, STARTING_HP - sum(item.hp_loss for item in results))
        tier = hp_tier(hp_left)

        analysis.stage2_tests = [item.as_dict() for item in results]
        analysis.stage2_hp_total = STARTING_HP
        analysis.stage2_hp_left = hp_left
        analysis.stage2_score = round(sum(item.score for item in results), 3)
        analysis.stage2_kills = [item.detail for item in results if item.status == BAD]
        analysis.stage2_flags = [item.detail for item in results if item.status == WEAK]
        analysis.stage2_verdict = "ELIMINATED" if tier == "Eliminated" else "PASS"
        analysis.stage2_tier = tier
        analysis.eligible_for_stage3 = tier != "Eliminated"
        return analysis
