#!/usr/bin/env python3
"""Premium-first market screener.

This is a local MVP for the user's Stage 1 / Stage 2 / Stage 3 funnel.
It uses public sources:
- Barchart quote overview for IV rank / IV percentile / implied vol context
- Finviz quote page for quote stats, analyst consensus, news, and option-chain liquidity
- SEC companyfacts for the Stage 3 fundamental spine

The goal is not to be fancy. The goal is to be ruthless.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import html
import io
import json
import math
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# -----------------------------
# Utilities
# -----------------------------


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


class FetchError(RuntimeError):
    pass


class HTTP:
    def __init__(self, timeout: int = 25, retries: int = 2):
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        last_exc = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, headers=headers)
                resp.raise_for_status()
                return resp
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < self.retries:
                    time.sleep(0.8 * (attempt + 1))
        raise FetchError(f"GET failed for {url}: {last_exc}")


# -----------------------------
# Data models
# -----------------------------


@dataclass
class QuoteSnapshot:
    symbol: str
    price: Optional[float] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    market_cap: Optional[float] = None
    volume: Optional[float] = None
    avg_volume: Optional[float] = None
    rel_volume: Optional[float] = None
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    sma200: Optional[float] = None
    week_52_high: Optional[float] = None
    week_52_low: Optional[float] = None
    inst_own: Optional[float] = None
    insider_own: Optional[float] = None
    insider_trans: Optional[float] = None
    short_float: Optional[float] = None
    target_price: Optional[float] = None
    recom: Optional[float] = None
    beta: Optional[float] = None
    eps_next_y: Optional[float] = None
    eps_next_q: Optional[float] = None
    earnings_date: Optional[str] = None
    news: List[Dict[str, str]] = dataclasses.field(default_factory=list)


@dataclass
class BarchartSnapshot:
    implied_volatility: Optional[float] = None
    historical_volatility: Optional[float] = None
    iv_percentile: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_high: Optional[float] = None
    iv_low: Optional[float] = None
    expected_move: Optional[float] = None


@dataclass
class OptionsSnapshot:
    expiry: Optional[str] = None
    total_volume: Optional[int] = None
    total_open_interest: Optional[int] = None
    atm_bid_ask_spread: Optional[float] = None
    atm_strike: Optional[float] = None
    spread_note: Optional[str] = None


@dataclass
class SECFacts:
    cik: Optional[str] = None
    revenue: List[Tuple[str, float]] = dataclasses.field(default_factory=list)
    net_income: List[Tuple[str, float]] = dataclasses.field(default_factory=list)
    op_income: List[Tuple[str, float]] = dataclasses.field(default_factory=list)
    op_cash_flow: List[Tuple[str, float]] = dataclasses.field(default_factory=list)
    cash: List[Tuple[str, float]] = dataclasses.field(default_factory=list)
    shares: List[Tuple[str, float]] = dataclasses.field(default_factory=list)


@dataclass
class TickerAnalysis:
    symbol: str
    quote: QuoteSnapshot
    barchart: BarchartSnapshot
    options: OptionsSnapshot
    sec: Optional[SECFacts] = None
    stage1_pass: bool = False
    stage1_reasons: List[str] = dataclasses.field(default_factory=list)
    stage2_kills: List[str] = dataclasses.field(default_factory=list)
    stage2_flags: List[str] = dataclasses.field(default_factory=list)
    stage2_tests: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    stage2_hp_total: int = 8
    stage2_hp_left: int = 8
    stage2_score: float = 0.0
    stage3: Optional[Dict[str, Any]] = None


# -----------------------------
# Finviz parsing
# -----------------------------


def parse_finviz_quote(html_text: str, symbol: str) -> QuoteSnapshot:
    snapshot = QuoteSnapshot(symbol=symbol)

    # Parse label/value pairs from the quote table.
    pattern = re.compile(
        r'<div class="snapshot-td-label">(.*?)</div></td>\s*'
        r'<td class="snapshot-td2[^\"]*"[^>]*>\s*<div class="snapshot-td-content">(.*?)</div>',
        re.S,
    )
    pairs = pattern.findall(html_text)
    data: Dict[str, str] = {}
    for raw_label, raw_value in pairs:
        label = strip_tags(raw_label)
        value = strip_tags(raw_value)
        if label and label not in data:
            data[label] = value

    def fnum(key: str) -> Optional[float]:
        val = data.get(key)
        if not val or val in {"-", "N/A", "NA"}:
            return None
        cleaned = val.replace(",", "").replace("$", "").replace("%", "")
        m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        return float(m.group(0)) if m else None

    # Core quote metrics.
    snapshot.price = fnum("Price")
    snapshot.sector = data.get("Sector")
    snapshot.industry = data.get("Industry")
    snapshot.market_cap = _parse_money(data.get("Market Cap"))
    snapshot.volume = _parse_number(data.get("Rel Volume"))  # overwritten if we have today volume below
    snapshot.avg_volume = _parse_number(data.get("Avg Volume"))
    snapshot.rel_volume = fnum("Rel Volume")
    snapshot.sma20 = _parse_percent(data.get("SMA20"))
    snapshot.sma50 = _parse_percent(data.get("SMA50"))
    snapshot.sma200 = _parse_percent(data.get("SMA200"))
    snapshot.week_52_high = _parse_price_from_label(data.get("52W High"))
    snapshot.week_52_low = _parse_price_from_label(data.get("52W Low"))
    snapshot.inst_own = _parse_percent(data.get("Inst Own"))
    snapshot.insider_own = _parse_percent(data.get("Insider Own"))
    snapshot.insider_trans = _parse_percent(data.get("Insider Trans"))
    snapshot.short_float = _parse_percent(data.get("Short Float"))
    snapshot.target_price = _parse_price_from_label(data.get("Target Price"))
    snapshot.recom = fnum("Recom")
    snapshot.beta = fnum("Beta")
    snapshot.eps_next_y = _parse_number(data.get("EPS next Y"))
    snapshot.eps_next_q = _parse_number(data.get("EPS next Q"))

    # Today's volume is often the value in the same row as Price/Prev Close.
    if "Rel Volume" in data:
        pass
    if "Volume" in data:
        snapshot.volume = _parse_number(data.get("Volume"))

    # Earnings date if present.
    for key in ("Earnings", "Earnings Date", "Earnings/Ann. Date"):
        if key in data:
            snapshot.earnings_date = data[key]
            break

    snapshot.news = parse_finviz_news(html_text)
    return snapshot


def parse_finviz_news(html_text: str) -> List[Dict[str, str]]:
    section_match = re.search(
        r'<table[^>]*id="news-table"[^>]*>(.*?)</table>', html_text, re.S
    )
    if not section_match:
        return []
    section = section_match.group(1)
    items: List[Dict[str, str]] = []
    row_pattern = re.compile(r"<tr[^>]*onclick=.*?</tr>", re.S)
    for row in row_pattern.findall(section):
        time_m = re.search(r"<td[^>]*align=\"right\">\s*(.*?)\s*</td>", row, re.S)
        headline_m = re.search(r'class="tab-link-news"[^>]*>(.*?)</a>', row, re.S)
        source_m = re.search(r"<span>\((.*?)\)</span>", row, re.S)
        if not headline_m:
            continue
        items.append(
            {
                "time": strip_tags(time_m.group(1)) if time_m else "",
                "headline": strip_tags(headline_m.group(1)),
                "source": strip_tags(source_m.group(1)) if source_m else "",
            }
        )
    return items


# -----------------------------
# Barchart parsing
# -----------------------------


def parse_barchart_overview(html_text: str) -> BarchartSnapshot:
    snap = BarchartSnapshot()
    pairs = re.findall(
        r'<span class="left">([^<]+)</span>\s*<span class="right">\s*(.*?)\s*</span>',
        html_text,
        re.S,
    )
    data: Dict[str, str] = {}
    for label, raw_value in pairs:
        label = strip_tags(label)
        value = strip_tags(raw_value)
        if label and label not in data:
            data[label] = value

    snap.implied_volatility = _parse_percent(data.get("Implied Volatility"))
    snap.historical_volatility = _parse_percent(data.get("Historical Volatility"))
    snap.iv_percentile = _parse_percent(data.get("IV Percentile"))
    snap.iv_rank = _parse_percent(data.get("IV Rank"))
    snap.iv_high = _parse_percent(_first_number(data.get("IV High")))
    snap.iv_low = _parse_percent(_first_number(data.get("IV Low")))
    snap.expected_move = _parse_percent(_first_number(data.get("Expected Move")))
    return snap


# -----------------------------
# Options chain parsing (Finviz)
# -----------------------------


def parse_finviz_options(html_text: str, price: Optional[float]) -> OptionsSnapshot:
    snap = OptionsSnapshot()
    current_expiry_match = re.search(r'"currentExpiry":"([0-9\-]+)"', html_text)
    expiry_text = current_expiry_match.group(1) if current_expiry_match else None
    if expiry_text:
        snap.expiry = expiry_text

    # Extract the embedded JSON array for the option chain.
    ticker_match = re.search(r'"ticker":"([A-Z.]+)","options":\[', html_text)
    if not ticker_match:
        return snap
    start = ticker_match.end() - 1  # points at '['
    depth = 0
    end = None
    for idx in range(start, len(html_text)):
        ch = html_text[idx]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    if end is None:
        return snap

    try:
        options = json.loads(html_text[start:end])
    except Exception:
        return snap

    if expiry_text:
        expiry_key = int(expiry_text.replace("-", "")) % 1000000
    else:
        expiry_key = min(int(o.get("exDate") or 999999) for o in options)

    current = [o for o in options if int(o.get("exDate") or 0) == expiry_key]
    if not current:
        return snap

    snap.total_volume = int(sum(int(o.get("lastVolume") or 0) for o in current))
    snap.total_open_interest = int(sum(int(o.get("openInterest") or 0) for o in current))

    # Estimate liquidity from the closest-atm call/put.
    if price is not None:
        nearest = min(current, key=lambda o: abs(float(o.get("strike") or 0) - price))
        atm_strike = float(nearest.get("strike") or 0)
        snap.atm_strike = atm_strike
        # Find closest call and put at that strike or the nearest same-strike contract.
        same_strike = [o for o in current if float(o.get("strike") or 0) == atm_strike]
        spreads = []
        for typ in ("call", "put"):
            matches = [o for o in same_strike if o.get("type") == typ]
            if matches:
                o = matches[0]
                bid = float(o.get("bidPrice") or 0)
                ask = float(o.get("askPrice") or 0)
                if bid > 0 and ask > 0:
                    spreads.append(ask - bid)
        if not spreads:
            # fallback: use best bid/ask among current expiry around the ATM strike.
            for o in current:
                strike = float(o.get("strike") or 0)
                if abs(strike - price) <= max(2.0, price * 0.1):
                    bid = float(o.get("bidPrice") or 0)
                    ask = float(o.get("askPrice") or 0)
                    if bid > 0 and ask > 0:
                        spreads.append(ask - bid)
        if spreads:
            snap.atm_bid_ask_spread = max(spreads)
            if snap.atm_bid_ask_spread > 1.0:
                snap.spread_note = f"ATM spread is wide (${snap.atm_bid_ask_spread:.2f})."
            else:
                snap.spread_note = f"ATM spread looks tradable (${snap.atm_bid_ask_spread:.2f})."

    return snap


# -----------------------------
# SEC facts
# -----------------------------


def load_sec_companyfacts(http: HTTP, symbol: str) -> Optional[SECFacts]:
    ticker_map = http.get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": "Hermes analysis hermes@example.com"}).json()
    cik = None
    for _, row in ticker_map.items():
        if row.get("ticker", "").upper() == symbol.upper():
            cik = int(row["cik_str"])
            break
    if cik is None:
        return None

    cik_str = f"CIK{cik:010d}"
    data = http.get(
        f"https://data.sec.gov/api/xbrl/companyfacts/{cik_str}.json",
        headers={"User-Agent": "Hermes analysis hermes@example.com"},
    ).json()

    facts = data.get("facts", {}).get("us-gaap", {})
    out = SECFacts(cik=cik_str)
    extract_map = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": out.revenue,
        "NetIncomeLoss": out.net_income,
        "OperatingIncomeLoss": out.op_income,
        "NetCashProvidedByUsedInOperatingActivities": out.op_cash_flow,
        "CashAndCashEquivalentsAtCarryingValue": out.cash,
        "CommonStockSharesOutstanding": out.shares,
    }
    for fact_name, collector in extract_map.items():
        fact = facts.get(fact_name)
        if not fact:
            continue
        units = fact.get("units", {})
        if not units:
            continue
        # Prefer USD or shares if present.
        unit_name = "USD" if "USD" in units else ("shares" if "shares" in units else next(iter(units)))
        for item in units[unit_name]:
            val = item.get("val")
            if val is None:
                continue
            when = item.get("end") or item.get("start") or item.get("filed") or ""
            collector.append((when, float(val)))

    # sort by date string; SEC date strings are yyyy-mm-dd, so lexicographic works.
    for collector in (out.revenue, out.net_income, out.op_income, out.op_cash_flow, out.cash, out.shares):
        collector.sort(key=lambda x: x[0])

    return out


# -----------------------------
# Helpers
# -----------------------------


def _parse_number(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    s = text.strip().replace(",", "")
    if s in {"-", "N/A", "NA", "--"}:
        return None
    # support shorthand like 21.98B / 373.17M
    m = re.search(r"(-?\d+(?:\.\d+)?)([KMBT]?)", s)
    if not m:
        return None
    num = float(m.group(1))
    suffix = m.group(2)
    mult = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(suffix, 1.0)
    return num * mult


def _parse_money(text: Optional[str]) -> Optional[float]:
    return _parse_number(text)


def _first_number(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    return m.group(0) if m else None


def _parse_price_from_label(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    # Handles strings like "84.64 - 25.89" or "$69.95"
    cleaned = text.replace("$", "").replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    return float(m.group(0)) if m else None


def _parse_percent(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    cleaned = text.replace("%", "").replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not m:
        return None
    return float(m.group(0))


def format_money(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 1e9:
        return f"${value/1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"${value/1e6:.2f}M"
    if abs(value) >= 1e3:
        return f"${value/1e3:.2f}K"
    return f"${value:.2f}"


def format_pct(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def latest_annual_fact(series: List[Tuple[str, float]]) -> Optional[float]:
    if not series:
        return None
    # Pick the latest year-end-ish row.
    # If there are monthly/quarterly rows mixed in, the latest row still wins.
    return series[-1][1]


def previous_annual_fact(series: List[Tuple[str, float]]) -> Optional[float]:
    if len(series) < 2:
        return None
    return series[-2][1]


def stage3_share_count(analysis: TickerAnalysis, sec: Optional[SECFacts]) -> Tuple[Optional[float], str, Optional[str]]:
    """Choose a per-share denominator for Stage 3.

    Prefer SEC shares when they are broadly consistent with market cap / price.
    Fall back to market-cap-implied shares when the SEC denominator is stale or
    obviously inconsistent with the live quote.
    """

    sec_shares = latest_annual_fact(sec.shares) if sec and sec.shares else None
    price = analysis.quote.price
    market_cap = analysis.quote.market_cap
    implied_shares = None
    if market_cap is not None and price is not None and price > 0:
        implied_shares = market_cap / price

    if sec_shares is None or sec_shares <= 0:
        if implied_shares is None:
            return None, "sec", "SEC shares unavailable and market-cap-implied shares unavailable"
        return implied_shares, "market_cap_implied", "SEC shares unavailable; using market cap / price"

    if implied_shares is not None:
        ratio = sec_shares / implied_shares
        if ratio < 0.5 or ratio > 2.0:
            return (
                implied_shares,
                "market_cap_implied",
                f"SEC shares {sec_shares:,.0f} disagree with market-cap-implied shares {implied_shares:,.0f}",
            )

    return sec_shares, "sec", None


def latest_q(series: List[Tuple[str, float]]) -> Optional[float]:
    if not series:
        return None
    return series[-1][1]


def load_nasdaq_meta(http: HTTP, symbol: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        data = http.get(
            f"https://api.nasdaq.com/api/quote/{symbol}/summary?assetclass=stocks",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*", "Referer": "https://www.nasdaq.com/"},
        ).json()
        summary = data.get("data", {}).get("summaryData", {})
        sector = summary.get("Sector", {}).get("value")
        industry = summary.get("Industry", {}).get("value")
        return sector, industry
    except Exception:
        return None, None


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# -----------------------------
# Stage logic
# -----------------------------


def stage1_filter(
    quote: QuoteSnapshot,
    barchart: BarchartSnapshot,
    options: OptionsSnapshot,
    *,
    min_implied_vol: float = 75,
    min_options_volume: int = 1000,
    min_market_cap: float = 1e9,
    min_today_volume: float = 1e6,
    min_open_interest: int = 1000,
    min_price: float = 10,
    max_price: float = 75,
) -> Tuple[bool, List[str]]:
    reasons = []

    # min_implied_vol is the best filter for our case.
    # min_iv_rank needs further investigation before we use it.
    if barchart.implied_volatility is None:
        reasons.append("implied volatility unavailable")
    elif barchart.implied_volatility < min_implied_vol:
        reasons.append(f"implied volatility {barchart.implied_volatility:.2f}% < {min_implied_vol:.2f}%")

    if options.total_volume is None or options.total_volume < min_options_volume:
        reasons.append(f"options volume {options.total_volume or 0:,} < {min_options_volume:,}")

    if quote.market_cap is None or quote.market_cap < min_market_cap:
        reasons.append(f"market cap {format_money(quote.market_cap)} < {format_money(min_market_cap)}")

    if quote.volume is None or quote.volume < min_today_volume:
        reasons.append(f"today volume {quote.volume or 0:,.0f} < {min_today_volume:,.0f}")

    if options.total_open_interest is None or options.total_open_interest < min_open_interest:
        reasons.append(f"open interest {options.total_open_interest or 0:,} < {min_open_interest:,}")

    if quote.price is None or not (min_price <= quote.price <= max_price):
        reasons.append(
            f"price {quote.price if quote.price is not None else 'n/a'} outside ${min_price:.0f}-${max_price:.0f}"
        )

    return len(reasons) == 0, reasons


NEWS_KILL_KEYWORDS = ["fraud", "sec investigation", "going concern", "bankruptcy", "recall threatens", "lawsuit", "accounting irregularity"]
NEWS_FLAG_KEYWORDS = ["earnings", "guidance", "acquire", "merger", "fda", "approval", "partnership", "conference", "launch", "upgrade", "downgrade", "ceo", "analyst"]
MOMO_KEYWORDS = ["reddit", "meme", "squeeze", "robinhood", "retail"]


def _stage2_add_test(
    tests: List[Dict[str, Any]],
    *,
    name: str,
    status: str,
    detail: str,
    score: Optional[float],
) -> None:
    tests.append(
        {
            "name": name,
            "status": status,
            "detail": detail,
            "score": score,
            "hp_loss": 1 if status == "KILL" else 0,
        }
    )


def analyze_stage2(analysis: TickerAnalysis, price_history: Optional[List[float]] = None) -> None:
    q = analysis.quote
    b = analysis.barchart
    o = analysis.options
    sec = analysis.sec

    tests: List[Dict[str, Any]] = []

    def add_test(name: str, status: str, detail: str, score: Optional[float]) -> None:
        _stage2_add_test(tests, name=name, status=status, detail=detail, score=score)
        if status == "KILL":
            analysis.stage2_kills.append(detail)
        elif status == "FLAG":
            analysis.stage2_flags.append(detail)

    # Test 1: IV spike diagnosis.
    headlines = " | ".join(n["headline"].lower() for n in q.news[:7])
    catalyst_hits = [kw for kw in NEWS_FLAG_KEYWORDS if kw in headlines]
    kill_hits = [kw for kw in NEWS_KILL_KEYWORDS if kw in headlines]
    if kill_hits:
        add_test("headline catalyst", "KILL", "News suggests existential damage: " + ", ".join(kill_hits), 0.0)
    elif not catalyst_hits:
        add_test("headline catalyst", "FLAG", "IV is elevated, but catalyst is not obvious from headlines", 0.5)
    else:
        add_test("headline catalyst", "FLAG", f"Real catalyst visible in headlines: {', '.join(catalyst_hits[:3])}", 0.5)

    # Test 2: Meme stock test.
    meme_kills = 0
    if sec and latest_annual_fact(sec.revenue) is not None and latest_annual_fact(sec.revenue) <= 0:
        meme_kills += 1
    if any(k in headlines for k in MOMO_KEYWORDS):
        meme_kills += 1
    if q.inst_own is not None and q.inst_own < 20 and (q.eps_next_y is None or q.eps_next_y <= 0):
        meme_kills += 1
    if price_history:
        if len(price_history) >= 20:
            rally = price_history[-1] / price_history[-20] - 1
            if rally >= 1.0 and not catalyst_hits:
                meme_kills += 1
    if meme_kills >= 3:
        add_test("meme-stock signature", "KILL", "Meme-stock signature: 3+ tells", 0.0)
    elif meme_kills == 2:
        add_test("meme-stock signature", "FLAG", "Meme-stock behavior is present; size down", 0.5)
    else:
        add_test("meme-stock signature", "PASS", "No meme-stock tells detected", 1.0)

    # Test 3: Binary event assessment.
    event_details: List[str] = []
    if q.earnings_date:
        event_details.append(f"Earnings/date watch: {q.earnings_date}")
    if sec is None:
        event_details.append("SEC facts unavailable; skipping operating-floor check")
        add_test("event / operating floor", "FLAG", " | ".join(event_details), 0.5)
    elif latest_annual_fact(sec.revenue) is not None and latest_annual_fact(sec.revenue) > 0:
        if q.price is not None and q.price > 0 and q.inst_own is not None:
            event_details.append("Business has real revenue under it")
            add_test("event / operating floor", "FLAG", " | ".join(event_details), 0.5)
        else:
            add_test("event / operating floor", "PASS", "Operating floor check cleared", 1.0)
    else:
        add_test("event / operating floor", "KILL", "No real operating floor visible", 0.0)

    # Test 4: Chart pattern check.
    if price_history and len(price_history) >= 20:
        recent = price_history[-20:]
        sma20 = statistics.mean(recent)
        if len(price_history) >= 2:
            day_move = price_history[-1] / price_history[-2] - 1
            if day_move <= -0.30:
                add_test("chart pattern", "KILL", "30%+ one-day breakdown", 0.0)
            elif q.price is not None and q.price < sma20 * 0.95:
                add_test("chart pattern", "FLAG", "Price is below the 20-day trend; tread carefully", 0.5)
            else:
                add_test("chart pattern", "PASS", "20-day trend intact", 1.0)
        else:
            if q.price is not None and q.price < sma20 * 0.95:
                add_test("chart pattern", "FLAG", "Price is below the 20-day trend; tread carefully", 0.5)
            else:
                add_test("chart pattern", "PASS", "20-day trend intact", 1.0)
    else:
        add_test("chart pattern", "SKIP", "Insufficient price history for 20-day trend check", None)

    # Test 5: News sentiment.
    if kill_hits:
        add_test("news sentiment", "SKIP", "Existing existential-news kill already captured in headline catalyst", None)
    elif any(kw in headlines for kw in ["fraud", "going concern", "sec"]):
        add_test("news sentiment", "KILL", "Bad news flow", 0.0)
    else:
        add_test("news sentiment", "FLAG", "No existential news in the last batch of headlines", 0.5)

    # Test 6: Analyst consensus.
    if q.recom is not None and q.target_price is not None and q.price is not None:
        if q.recom >= 4 and q.target_price < q.price * 0.8:
            add_test(
                "analyst consensus",
                "KILL",
                "Analyst consensus broken: sell/underweight with target >20% below price",
                0.0,
            )
        elif q.recom <= 2:
            add_test("analyst consensus", "FLAG", f"Consensus is constructive (recom {q.recom:.2f}, target {q.target_price:.2f})", 0.5)
        else:
            add_test("analyst consensus", "PASS", "Consensus not adverse", 1.0)
    else:
        add_test("analyst consensus", "SKIP", "Analyst consensus data incomplete", None)

    # Test 7: Liquidity sanity.
    if o.atm_bid_ask_spread is None:
        add_test("liquidity sanity", "SKIP", "ATM spread unavailable", None)
    elif o.atm_bid_ask_spread > 1.0:
        add_test("liquidity sanity", "KILL", f"ATM options spread is wide (${o.atm_bid_ask_spread:.2f})", 0.0)
    else:
        add_test("liquidity sanity", "FLAG", f"Options liquidity is workable (${o.atm_bid_ask_spread:.2f} ATM spread)", 0.5)

    # Test 8: Institutional ownership.
    if q.inst_own is None:
        add_test("institutional ownership", "SKIP", "Institutional ownership unavailable", None)
    elif q.inst_own < 20:
        add_test("institutional ownership", "KILL", f"Institutional ownership too low ({q.inst_own:.2f}%)", 0.0)
    else:
        add_test("institutional ownership", "FLAG", f"Institutional ownership is present ({q.inst_own:.2f}%)", 0.5)

    # Final stage2 verdict: 3+ hard kills = kill; 2 = watch; 0-1 = pass.
    unique_kills = list(dict.fromkeys(analysis.stage2_kills))
    analysis.stage2_kills = unique_kills
    analysis.stage2_tests = tests
    analysis.stage2_hp_total = len(tests)
    analysis.stage2_hp_left = analysis.stage2_hp_total - sum(test["hp_loss"] for test in tests)
    analysis.stage2_score = round(
        sum(test["score"] for test in tests if test["score"] is not None),
        3,
    )
    if len(unique_kills) >= 3:
        analysis.stage1_pass = False
    else:
        pass


# -----------------------------
# Stage 3: rough DCF
# -----------------------------


def _apld_forward_buildout_stage3(analysis: TickerAnalysis) -> Optional[Dict[str, Any]]:
    """APLD-specific forward buildout EV model.

    APLD is a construction-phase infrastructure developer, so the generic
    5-year FCF DCF path over-weights the near-term build cost and under-weights
    the value of the operating campus once the buildout is complete.
    """

    sec = analysis.sec
    q = analysis.quote
    if analysis.symbol != "APLD" or not sec or not sec.revenue or q.price is None:
        return None

    revenue = latest_annual_fact(sec.revenue)
    prev_revenue = previous_annual_fact(sec.revenue)
    net_income = latest_annual_fact(sec.net_income)
    op_income = latest_annual_fact(sec.op_income)
    op_cf = latest_annual_fact(sec.op_cash_flow)
    cash = latest_annual_fact(sec.cash)
    shares, share_source, share_note = stage3_share_count(analysis, sec)

    if revenue is None or revenue <= 0 or shares is None:
        return None

    # Net obligations = net debt + estimated Macquarie preferred obligations.
    # The estimate is intentionally surfaced as a single per-share haircut so the
    # valuation reflects the true burden of the buildout structure.
    net_obligations = 4.30e9

    scenario_inputs = {
        "bear": {"fy2029_revenue": 2.688e9, "ebitda_margin": 0.25, "ev_multiple": 10.0},
        "realistic": {"fy2029_revenue": 3.25e9, "ebitda_margin": 0.30, "ev_multiple": 11.0},
        "bull": {"fy2029_revenue": 3.90e9, "ebitda_margin": 0.33, "ev_multiple": 12.0},
    }

    scenarios: Dict[str, Dict[str, float]] = {}
    for name, params in scenario_inputs.items():
        fy2029_revenue = params["fy2029_revenue"]
        ebitda_margin = params["ebitda_margin"]
        ev_multiple = params["ev_multiple"]
        ebitda = fy2029_revenue * ebitda_margin
        enterprise_value = ebitda * ev_multiple
        equity_value = enterprise_value - net_obligations
        per_share = equity_value / shares
        scenarios[name] = {
            "fy2029_revenue": fy2029_revenue,
            "ebitda_margin": ebitda_margin,
            "ebitda": ebitda,
            "ev_multiple": ev_multiple,
            "enterprise_value": enterprise_value,
            "net_obligations": net_obligations,
            "equity_value": equity_value,
            "per_share": per_share,
        }

    bull = scenarios["bull"]["per_share"]
    realistic = scenarios["realistic"]["per_share"]
    bear = scenarios["bear"]["per_share"]
    # APLD is Category B — use pessimistic-weighted scenario mix.
    weights = {"bear": 0.42, "realistic": 0.46, "bull": 0.12}
    weighted = (
        bear * weights["bear"]
        + realistic * weights["realistic"]
        + bull * weights["bull"]
    )
    mos_threshold = 0.50 * weighted

    share_qc_detail = None
    if q.market_cap is not None and q.market_cap > 0:
        implied_mktcap = weighted * shares
        delta = abs(implied_mktcap - q.market_cap) / q.market_cap
        if delta > 0.20:
            share_qc_detail = (
                f"implied ${implied_mktcap / 1e9:.2f}B vs "
                f"known ${q.market_cap / 1e9:.2f}B ({delta * 100:.1f}%)"
            )
            return {
                "verdict": "QC FAIL",
                "qc_fail_reason": f"share denominator sanity failed: {share_qc_detail}",
                "category": "B",
                "share_count_source": share_source,
                "share_qc_detail": share_qc_detail,
                "weighted_fair_value": None,
                "mos_threshold": None,
            }

    return {
        "category": "B",
        "valuation_method": "forward_buildout_ev",
        "valuation_year": 2029,
        "scenario_weights": weights,
        "share_count_source": share_source,
        "share_qc_detail": share_qc_detail,
        "bull": bull,
        "realistic": realistic,
        "bear": bear,
        "weighted_fair_value": weighted,
        "mos_threshold": mos_threshold,
        "current_price": q.price,
        "undervaluation_pct": (weighted / q.price - 1) * 100,
        "watch_signal": "Polaris Forge 1 ELN-03 (150MW) achieves Ready-for-Service status on or before August 31, 2026.",
        "kill_signal": "CoreWeave ($CRWV) announces a material contract renegotiation, payment deferral, or financial covenant breach.",
        "key_facts": {
            "revenue": revenue,
            "previous_revenue": prev_revenue,
            "net_income": net_income,
            "op_income": op_income,
            "op_cash_flow": op_cf,
            "cash": cash,
            "shares": shares,
            "shares_source": share_source,
            "shares_note": share_note,
            "net_obligations": net_obligations,
            "coreweave_concentration_pct": 69.0,
            "coreweave_debt": 10.6e9,
            "coreweave_profitability": "pre-profitable",
        },
        "moat_risk": [
            "CoreWeave is the dominant tenant proxy at 69% concentration, so tenant health is the key risk variable.",
            "CoreWeave remains pre-profitable and carries roughly $10.6B of debt, so counterparty stress would matter quickly.",
            "APLD's moat is operational, not structural: it depends on execution, power access, and financing discipline.",
        ],
        "scenarios": scenarios,
    }


def stage3_analysis(analysis: TickerAnalysis) -> Optional[Dict[str, Any]]:
    apld_custom = _apld_forward_buildout_stage3(analysis)
    if apld_custom is not None:
        return apld_custom

    sec = analysis.sec
    q = analysis.quote

    def qc_fail(
        reason: str,
        *,
        category: Optional[str] = None,
        share_source: str = "unavailable",
        share_qc_detail: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "verdict": "QC FAIL",
            "qc_fail_reason": reason,
            "category": category,
            "share_count_source": share_source,
            "share_qc_detail": share_qc_detail,
            "weighted_fair_value": None,
            "mos_threshold": None,
        }

    if not sec or not sec.revenue or q.price is None:
        return qc_fail("SEC data unavailable or no live price")

    revenue = latest_annual_fact(sec.revenue)
    prev_revenue = previous_annual_fact(sec.revenue)
    net_income = latest_annual_fact(sec.net_income)
    op_income = latest_annual_fact(sec.op_income)
    op_cf = latest_annual_fact(sec.op_cash_flow)
    cash = latest_annual_fact(sec.cash)
    shares, share_source, share_note = stage3_share_count(analysis, sec)

    if revenue is None or revenue <= 0 or shares is None:
        fail_reason = "share count unresolvable" if shares is None else "zero or missing revenue"
        return qc_fail(fail_reason, share_source=share_source)

    growth = 0.25
    if prev_revenue and prev_revenue > 0:
        growth = clamp(revenue / prev_revenue - 1, -0.25, 2.5)
    fcf_proxy_margin = None
    if op_cf is not None:
        fcf_proxy_margin = op_cf / revenue
    elif op_income is not None:
        fcf_proxy_margin = op_income / revenue
    elif net_income is not None:
        fcf_proxy_margin = net_income / revenue
    else:
        fcf_proxy_margin = -0.2

    category = "A" if ((op_cf is not None and op_cf > 0) or (op_income is not None and op_income > 0)) else "B"
    discount = 0.10 if category == "A" else 0.15
    years = 5

    def project(scenario: str) -> Tuple[float, List[Dict[str, float]]]:
        rev = revenue
        rows = []
        pv = 0.0
        if category == "A":
            if scenario == "bull":
                growths = [max(growth * 1.15, 0.20), 0.35, 0.25, 0.20, 0.15]
                margins = [clamp(fcf_proxy_margin + 0.02, -0.05, 0.18), 0.06, 0.10, 0.14, 0.18]
                terminal_mult = 22
            elif scenario == "realistic":
                growths = [max(growth, 0.12), 0.25, 0.18, 0.14, 0.10]
                margins = [clamp(fcf_proxy_margin, -0.08, 0.14), 0.05, 0.08, 0.11, 0.14]
                terminal_mult = 16
            else:
                growths = [max(growth * 0.6, 0.05), 0.15, 0.10, 0.08, 0.05]
                margins = [clamp(fcf_proxy_margin - 0.02, -0.10, 0.08), 0.02, 0.04, 0.06, 0.08]
                terminal_mult = 10
        else:
            if scenario == "bull":
                growths = [0.80, 0.60, 0.45, 0.30, 0.20]
                margins = [-0.40, -0.15, 0.00, 0.07, 0.12]
                terminal_mult = 15
            elif scenario == "realistic":
                growths = [0.60, 0.45, 0.30, 0.20, 0.15]
                margins = [-0.50, -0.30, -0.12, -0.03, 0.05]
                terminal_mult = 12
            else:
                growths = [0.40, 0.25, 0.20, 0.15, 0.10]
                margins = [-0.60, -0.45, -0.35, -0.28, -0.20]
                terminal_mult = 0

        for year in range(1, years + 1):
            rev *= 1 + growths[year - 1]
            fcf = rev * margins[year - 1]
            rows.append({"year": year, "revenue": rev, "fcf": fcf, "margin": margins[year - 1], "growth": growths[year - 1]})
            pv += fcf / ((1 + discount) ** year)

        terminal_value = 0.0
        if rows[-1]["fcf"] > 0 and terminal_mult > 0:
            terminal_value = rows[-1]["fcf"] * terminal_mult / ((1 + discount) ** years)
        equity_value = pv + terminal_value + (cash or 0.0)
        per_share = equity_value / shares
        return per_share, rows

    bull, bull_rows = project("bull")
    realistic, realistic_rows = project("realistic")
    bear, bear_rows = project("bear")

    if category == "A":
        weights = {"bear": 0.25, "realistic": 0.50, "bull": 0.25}
    else:
        weights = {"bear": 0.42, "realistic": 0.46, "bull": 0.12}

    weighted = (
        bear * weights["bear"]
        + realistic * weights["realistic"]
        + bull * weights["bull"]
    )
    mos_threshold = 0.80 * weighted if category == "A" else 0.50 * weighted

    share_qc_detail = None
    if q.market_cap is not None and q.market_cap > 0:
        implied_mktcap = weighted * shares
        delta = abs(implied_mktcap - q.market_cap) / q.market_cap
        if delta > 0.20:
            share_qc_detail = (
                f"implied ${implied_mktcap / 1e9:.2f}B vs "
                f"known ${q.market_cap / 1e9:.2f}B ({delta * 100:.1f}%)"
            )
            return qc_fail(
                f"share denominator sanity failed: {share_qc_detail}",
                category=category,
                share_source=share_source,
                share_qc_detail=share_qc_detail,
            )

    watch_signal = (
        "Close below the 50-day SMA by 5% on elevated volume"
        if category == "A"
        else "Next revenue step-down below 50% YoY or cash runway under 18 months"
    )

    return {
        "category": category,
        "discount_rate": discount,
        "scenario_weights": weights,
        "bull": bull,
        "realistic": realistic,
        "bear": bear,
        "weighted_fair_value": weighted,
        "mos_threshold": mos_threshold,
        "current_price": q.price,
        "undervaluation_pct": (weighted / q.price - 1) * 100,
        "watch_signal": watch_signal,
        "share_count_source": share_source,
        "share_qc_detail": share_qc_detail,
        "key_facts": {
            "revenue": revenue,
            "previous_revenue": prev_revenue,
            "net_income": net_income,
            "op_income": op_income,
            "op_cash_flow": op_cf,
            "cash": cash,
            "shares": shares,
            "shares_source": share_source,
            "shares_note": share_note,
            "growth": growth,
            "fcf_proxy_margin": fcf_proxy_margin,
        },
        "scenarios": {
            "bull": bull_rows,
            "realistic": realistic_rows,
            "bear": bear_rows,
        },
    }


# -----------------------------
# Orchestration
# -----------------------------


def analyze_ticker(
    http: HTTP,
    symbol: str,
    include_stage3: bool = True,
    *,
    min_implied_vol: float = 75,
    min_options_volume: int = 1000,
    min_market_cap: float = 1e9,
    min_today_volume: float = 1e6,
    min_open_interest: int = 1000,
    min_price: float = 10,
    max_price: float = 75,
) -> TickerAnalysis:
    symbol = symbol.upper().strip()

    finviz_html = http.get(f"https://finviz.com/quote.ashx?t={symbol}").text
    barchart_html = http.get(f"https://www.barchart.com/stocks/quotes/{symbol}/overview").text
    q = parse_finviz_quote(finviz_html, symbol)
    b = parse_barchart_overview(barchart_html)
    o = parse_finviz_options(http.get(f"https://finviz.com/quote.ashx?t={symbol}&ta=1&p=d&ty=oc").text, q.price)
    nasdaq_sector, nasdaq_industry = load_nasdaq_meta(http, symbol)
    if not q.sector:
        q.sector = nasdaq_sector
    if not q.industry:
        q.industry = nasdaq_industry

    analysis = TickerAnalysis(symbol=symbol, quote=q, barchart=b, options=o)
    analysis.stage1_pass, analysis.stage1_reasons = stage1_filter(
        q,
        b,
        o,
        min_implied_vol=min_implied_vol,
        min_options_volume=min_options_volume,
        min_market_cap=min_market_cap,
        min_today_volume=min_today_volume,
        min_open_interest=min_open_interest,
        min_price=min_price,
        max_price=max_price,
    )

    if analysis.stage1_pass:
        if include_stage3:
            analysis.sec = load_sec_companyfacts(http, symbol)

        history = fetch_nasdaq_history(http, symbol, days=90)
        analyze_stage2(analysis, price_history=history)

        if include_stage3 and len(analysis.stage2_kills) <= 2:
            analysis.stage3 = stage3_analysis(analysis)
    else:
        analysis.stage2_tests = []

    return analysis


def analyze_stage1_ticker(
    http: HTTP,
    symbol: str,
    *,
    min_implied_vol: float = 75,
    min_options_volume: int = 1000,
    min_market_cap: float = 1e9,
    min_today_volume: float = 1e6,
    min_open_interest: int = 1000,
    min_price: float = 10,
    max_price: float = 75,
) -> TickerAnalysis:
    """Fast path for broad scans: Stage 1 only, no SEC/history/stage2/stage3."""

    symbol = symbol.upper().strip()

    finviz_html = http.get(f"https://finviz.com/quote.ashx?t={symbol}").text
    barchart_html = http.get(f"https://www.barchart.com/stocks/quotes/{symbol}/overview").text
    q = parse_finviz_quote(finviz_html, symbol)
    b = parse_barchart_overview(barchart_html)
    o = parse_finviz_options(http.get(f"https://finviz.com/quote.ashx?t={symbol}&ta=1&p=d&ty=oc").text, q.price)
    nasdaq_sector, nasdaq_industry = load_nasdaq_meta(http, symbol)
    if not q.sector:
        q.sector = nasdaq_sector
    if not q.industry:
        q.industry = nasdaq_industry

    analysis = TickerAnalysis(symbol=symbol, quote=q, barchart=b, options=o)
    analysis.stage1_pass, analysis.stage1_reasons = stage1_filter(
        q,
        b,
        o,
        min_implied_vol=min_implied_vol,
        min_options_volume=min_options_volume,
        min_market_cap=min_market_cap,
        min_today_volume=min_today_volume,
        min_open_interest=min_open_interest,
        min_price=min_price,
        max_price=max_price,
    )
    return analysis


def fetch_nasdaq_history(http: HTTP, symbol: str, days: int = 90) -> List[float]:
    end = dt.date.today()
    start = end - dt.timedelta(days=max(days * 2, 120))
    url = (
        f"https://api.nasdaq.com/api/quote/{symbol}/historical?assetclass=stocks"
        f"&fromdate={start.isoformat()}&todate={end.isoformat()}"
    )
    try:
        data = http.get(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*", "Referer": "https://www.nasdaq.com/"}).json()
        rows = data["data"]["tradesTable"]["rows"]
        rows = list(reversed(rows))
        closes = [float(r["close"].replace("$", "").replace(",", "")) for r in rows if r.get("close") not in {None, ""}]
        return closes[-days:]
    except Exception:
        return []


# -----------------------------
# Reporting
# -----------------------------


def render_analysis(a: TickerAnalysis, *, stage2_ran: bool = True) -> str:
    out = []
    q, b, o = a.quote, a.barchart, a.options
    out.append(f"## {a.symbol}")
    out.append("")
    out.append(f"- Price: {q.price if q.price is not None else 'n/a'}")
    out.append(f"- Market cap: {format_money(q.market_cap)}")
    out.append(f"- Sector: {q.sector if q.sector is not None else 'n/a'}")
    out.append(f"- Industry: {q.industry if q.industry is not None else 'n/a'}")
    out.append(f"- Implied vol: {format_pct(b.implied_volatility)}")
    out.append(f"- IV rank: {format_pct(b.iv_rank)}")
    out.append(f"- IV percentile: {format_pct(b.iv_percentile)}")
    out.append(f"- Options volume: {o.total_volume if o.total_volume is not None else 'n/a'}")
    out.append(f"- Open interest: {o.total_open_interest if o.total_open_interest is not None else 'n/a'}")
    out.append(f"- ATM spread: ${o.atm_bid_ask_spread:.2f}" if o.atm_bid_ask_spread is not None else "- ATM spread: n/a")
    out.append(f"- Institutional ownership: {format_pct(q.inst_own)}")
    out.append(f"- Analyst target: {q.target_price if q.target_price is not None else 'n/a'}")
    out.append(f"- Analyst recom: {q.recom if q.recom is not None else 'n/a'}")
    out.append("")
    out.append("### Stage 1")
    out.append(f"- Verdict: {'PASS' if a.stage1_pass else 'KILL'}")
    if a.stage1_reasons:
        for r in a.stage1_reasons:
            out.append(f"- {r}")
    else:
        out.append("- All mechanical filters cleared.")
    if stage2_ran:
        out.append("")
        out.append("### Stage 2")
        kills = len(a.stage2_kills)
        verdict = "PASS"
        if kills >= 3:
            verdict = "KILL"
        elif kills == 2:
            verdict = "WATCH PASS"
        out.append(f"- Verdict: {verdict} ({kills} hard kills)")
        if a.stage2_kills:
            out.extend([f"- kill: {k}" for k in a.stage2_kills])
        if a.stage2_flags:
            out.extend([f"- flag: {f}" for f in a.stage2_flags])
        out.append("")
    if a.stage3:
        s3 = a.stage3
        out.append("### Stage 3")
        if s3.get("verdict") == "QC FAIL":
            out.append("- Verdict: QC FAIL")
            out.append(f"- Reason: {s3.get('qc_fail_reason', 'unknown')}")
            if s3.get("share_qc_detail"):
                out.append(f"- Share QC detail: {s3['share_qc_detail']}")
        elif s3.get("valuation_method") == "forward_buildout_ev":
            out.append(f"- Category: {s3['category']}")
            share_source = s3.get("share_count_source") or s3.get("key_facts", {}).get("shares_source")
            share_note = s3.get("key_facts", {}).get("shares_note")
            if share_source:
                out.append(f"- Shares denominator: {share_source.replace('_', ' ')}")
            if share_note:
                out.append(f"- Share QC: {share_note}")
            out.append("- Method: Forward buildout EV")
            out.append(f"- Target year: FY{s3['valuation_year']}")
            out.append(f"- Net obligations haircut: ${s3['key_facts']['net_obligations']/1e9:.2f}B")
            out.append(f"- CoreWeave concentration: {s3['key_facts']['coreweave_concentration_pct']:.0f}% of contracted backlog")
            out.append(f"- CoreWeave profile: {s3['key_facts']['coreweave_profitability']}, debt ~${s3['key_facts']['coreweave_debt']/1e9:.1f}B")
            if s3.get("scenario_weights"):
                w = s3["scenario_weights"]
                out.append(f"- Scenario weights: bear {w['bear']*100:.0f}% / realistic {w['realistic']*100:.0f}% / bull {w['bull']*100:.0f}%")
            out.append("- Scenario buildout assumptions:")
            for name in ["bear", "realistic", "bull"]:
                sc = s3["scenarios"][name]
                out.append(
                    f"  - {name.title()}: FY2029 revenue ${sc['fy2029_revenue']/1e9:.2f}B, "
                    f"EBITDA margin {sc['ebitda_margin']*100:.1f}%, EV/EBITDA {sc['ev_multiple']:.1f}x, "
                    f"EV ${sc['enterprise_value']/1e9:.2f}B, net-of-obligations per share ${sc['per_share']:.2f}"
                )
            out.append(f"- Bull FV: ${s3['bull']:.2f}")
            out.append(f"- Realistic FV: ${s3['realistic']:.2f}")
            out.append(f"- Bear FV: ${s3['bear']:.2f}")
            out.append(f"- Probability-weighted FV: ${s3['weighted_fair_value']:.2f}")
            out.append(f"- Margin-of-safety threshold: ${s3['mos_threshold']:.2f}")
            out.append(f"- Watch signal: {s3['watch_signal']}")
            out.append(f"- Kill signal: {s3['kill_signal']}")
            if s3.get("moat_risk"):
                out.append("- Moat / risk:")
                out.extend([f"  - {r}" for r in s3["moat_risk"]])
            out.append(f"- Current price vs FV: {s3['current_price']:.2f} / {s3['weighted_fair_value']:.2f}")
            out.append(f"- Undervaluation: {s3['undervaluation_pct']:.1f}%")
            out.append(f"- Final verdict: {summary_verdict(a)}")
        else:
            out.append(f"- Category: {s3['category']}")
            share_source = s3.get("share_count_source") or s3.get("key_facts", {}).get("shares_source")
            share_note = s3.get("key_facts", {}).get("shares_note")
            if share_source:
                out.append(f"- Shares denominator: {share_source.replace('_', ' ')}")
            if share_note:
                out.append(f"- Share QC: {share_note}")
            if s3.get("scenario_weights"):
                w = s3["scenario_weights"]
                out.append(f"- Scenario weights: bear {w['bear']*100:.0f}% / realistic {w['realistic']*100:.0f}% / bull {w['bull']*100:.0f}%")
            out.append(f"- Bull FV: ${s3['bull']:.2f}")
            out.append(f"- Realistic FV: ${s3['realistic']:.2f}")
            out.append(f"- Bear FV: ${s3['bear']:.2f}")
            out.append(f"- Probability-weighted FV: ${s3['weighted_fair_value']:.2f}")
            out.append(f"- Margin-of-safety threshold: ${s3['mos_threshold']:.2f}")
            out.append(f"- Watch signal: {s3['watch_signal']}")
            out.append(f"- Current price vs FV: {s3['current_price']:.2f} / {s3['weighted_fair_value']:.2f}")
            out.append(f"- Undervaluation: {s3['undervaluation_pct']:.1f}%")
            out.append(f"- Final verdict: {summary_verdict(a)}")
    return "\n".join(out)


def summary_verdict(a: TickerAnalysis) -> str:
    """Return one of exactly four legal Stage 3 verdict labels.

    DIAMOND  — price at or below MOS threshold, zero Stage 2 kills
    ENTRY    — price at or below MOS threshold, 1–2 Stage 2 kills
    NO ENTRY — price above MOS threshold, Stage 1 failure, or Stage 3 not run
    QC FAIL  — data failure, failed valuation, or share denominator sanity failure

    Do not embed FV amounts or kill counts in the verdict string.
    Explanatory detail belongs in separate fields (qc_fail_reason, stage2_kills, etc.).
    """
    if not a.stage1_pass:
        return "NO ENTRY"
    if len(a.stage2_kills) >= 3:
        return "NO ENTRY"
    if a.stage3 is None:
        return "NO ENTRY"
    if a.stage3.get("verdict") == "QC FAIL":
        return "QC FAIL"

    fv = a.stage3.get("weighted_fair_value")
    mos = a.stage3.get("mos_threshold")
    price = a.quote.price
    if fv is None or mos is None or price is None:
        return "QC FAIL"

    if price <= mos:
        return "DIAMOND" if len(a.stage2_kills) == 0 else "ENTRY"
    return "NO ENTRY"


def sector_spread(analyses: List[TickerAnalysis]) -> List[Tuple[str, int]]:
    counts: Dict[str, int] = {}
    for a in analyses:
        sector = a.quote.sector or "Unknown"
        counts[sector] = counts.get(sector, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def analysis_csv_row(a: TickerAnalysis, rank: Optional[int] = None) -> Dict[str, Any]:
    s3 = a.stage3 or {}
    return {
        "rank": rank if rank is not None else "",
        "symbol": a.symbol,
        "stage3_verdict": summary_verdict(a),
        "stage1_pass": a.stage1_pass,
        "price": _csv_cell(a.quote.price),
        "sector": _csv_cell(a.quote.sector),
        "market_cap": _csv_cell(a.quote.market_cap),
        "implied_vol": _csv_cell(a.barchart.implied_volatility),
        "iv_rank": _csv_cell(a.barchart.iv_rank),
        "iv_percentile": _csv_cell(a.barchart.iv_percentile),
        "options_volume": _csv_cell(a.options.total_volume),
        "open_interest": _csv_cell(a.options.total_open_interest),
        "atm_spread": _csv_cell(a.options.atm_bid_ask_spread),
        "stage1_reasons": " | ".join(a.stage1_reasons),
        "stage2_kills": " | ".join(a.stage2_kills),
        "stage2_flags": " | ".join(a.stage2_flags),
        "stage3_category": _csv_cell(s3.get("category")),
        "scenario_weights": _csv_cell(s3.get("scenario_weights")),
        "weighted_fair_value": _csv_cell(s3.get("weighted_fair_value")),
        "mos_threshold": _csv_cell(s3.get("mos_threshold")),
        "qc_fail_reason": _csv_cell(s3.get("qc_fail_reason")),
        "share_count_source": _csv_cell(s3.get("share_count_source")),
        "share_qc_detail": _csv_cell(s3.get("share_qc_detail")),
        "watch_signal": _csv_cell(s3.get("watch_signal")),
    }


def write_csv_output(analyses: List[TickerAnalysis], *, all_us: bool, csv_path: Optional[str] = None) -> None:
    fieldnames = [
        "rank",
        "symbol",
        "stage3_verdict",
        "stage1_pass",
        "price",
        "sector",
        "market_cap",
        "iv_rank",
        "iv_percentile",
        "implied_vol",
        "options_volume",
        "open_interest",
        "atm_spread",
        "stage1_reasons",
        "stage2_kills",
        "stage2_flags",
        "stage3_category",
        "scenario_weights",
        "weighted_fair_value",
        "mos_threshold",
        "qc_fail_reason",
        "share_count_source",
        "share_qc_detail",
        "watch_signal",
    ]
    if all_us:
        rows = [analysis_csv_row(a, rank=idx + 1) for idx, a in enumerate(rank_stage1_candidates(analyses))]
    else:
        rows = [analysis_csv_row(a) for a in analyses]

    target = open(csv_path, "w", newline="", encoding="utf-8") if csv_path else sys.stdout
    try:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key)) for key in fieldnames})
    finally:
        if csv_path:
            target.close()


# -----------------------------
# CLI
# -----------------------------


def load_tickers_from_file(path: str) -> List[str]:
    tickers: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tickers.extend([t.strip().upper() for t in re.split(r"[\s,]+", line) if t.strip()])
    return list(dict.fromkeys(tickers))


def load_all_us_tickers(http: HTTP) -> List[str]:
    """Load a broad US-listed universe from the SEC company ticker map."""

    data = http.get(
        "https://www.sec.gov/files/company_tickers.json",
        headers={"User-Agent": "Hermes analysis hermes@example.com"},
    ).json()
    tickers: List[str] = []
    for _, row in data.items():
        ticker = str(row.get("ticker", "")).strip().upper()
        if ticker:
            tickers.append(ticker)
    return list(dict.fromkeys(tickers))


def stage1_sort_key(a: TickerAnalysis) -> Tuple[float, float, float, float, float, str]:
    q = a.quote
    b = a.barchart
    o = a.options
    implied_volatility = b.implied_volatility if b.implied_volatility is not None else -1.0
    options_volume = float(o.total_volume or 0)
    open_interest = float(o.total_open_interest or 0)
    market_cap = float(q.market_cap or 0)
    spread = float(o.atm_bid_ask_spread if o.atm_bid_ask_spread is not None else 9_999.0)
    return (-implied_volatility, -options_volume, -open_interest, -market_cap, spread, a.symbol)


def rank_stage1_candidates(analyses: List[TickerAnalysis]) -> List[TickerAnalysis]:
    return sorted((a for a in analyses if a.stage1_pass), key=stage1_sort_key)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Premium-first market screener")
    parser.add_argument("--tickers", help="Comma-separated list of tickers")
    parser.add_argument("--universe", help="Text file with tickers, one per line or comma separated")
    parser.add_argument("--output", choices=["markdown", "json", "csv"], default="markdown")
    parser.add_argument("--csv-path", help="Write CSV output directly to this file path")
    parser.add_argument("--stage1-only", action="store_true", help="Run only Stage 1 mechanics (skip SEC / Stage 2 / Stage 3)")
    parser.add_argument("--no-stage3", action="store_true", help="Skip SEC / Stage 3 analysis")
    parser.add_argument("--all-us", action="store_true", help="Scan the broad US-listed universe from SEC company tickers")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent workers for large scans")
    parser.add_argument("--min-implied-vol", dest="min_implied_vol", type=float, default=75.0, help="Stage 1 minimum implied volatility")
    parser.add_argument("--min-options-volume", type=int, default=1000, help="Stage 1 minimum options volume")
    parser.add_argument("--min-market-cap", type=float, default=1e9, help="Stage 1 minimum market cap")
    parser.add_argument("--min-volume", type=float, default=1e6, help="Stage 1 minimum today's share volume")
    parser.add_argument("--min-open-interest", type=int, default=1000, help="Stage 1 minimum open interest")
    parser.add_argument("--min-price", type=float, default=10.0, help="Stage 1 minimum price")
    parser.add_argument("--max-price", type=float, default=75.0, help="Stage 1 maximum price")
    parser.add_argument("--max-sector-share", type=float, default=0.5, help="Warn if one sector exceeds this share of screened names")
    args = parser.parse_args(argv)

    http = HTTP()

    if args.csv_path:
        args.output = "csv"

    if args.all_us:
        args.stage1_only = True
        tickers = load_all_us_tickers(http)
    else:
        tickers = []
        if args.tickers:
            tickers.extend([t.strip().upper() for t in args.tickers.split(",") if t.strip()])
        if args.universe:
            tickers.extend(load_tickers_from_file(args.universe))
        tickers = list(dict.fromkeys(tickers))

    if not tickers:
        print("Provide --tickers, --universe, or --all-us", file=sys.stderr)
        return 2

    def _analyze_symbol(sym: str) -> TickerAnalysis:
        try:
            if args.stage1_only:
                return analyze_stage1_ticker(
                    HTTP(),
                    sym,
                    min_implied_vol=args.min_implied_vol,
                    min_options_volume=args.min_options_volume,
                    min_market_cap=args.min_market_cap,
                    min_today_volume=args.min_volume,
                    min_open_interest=args.min_open_interest,
                    min_price=args.min_price,
                    max_price=args.max_price,
                )
            return analyze_ticker(
                HTTP(),
                sym,
                include_stage3=not args.no_stage3,
                min_implied_vol=args.min_implied_vol,
                min_options_volume=args.min_options_volume,
                min_market_cap=args.min_market_cap,
                min_today_volume=args.min_volume,
                min_open_interest=args.min_open_interest,
                min_price=args.min_price,
                max_price=args.max_price,
            )
        except Exception as exc:  # noqa: BLE001
            return TickerAnalysis(
                symbol=sym,
                quote=QuoteSnapshot(symbol=sym),
                barchart=BarchartSnapshot(),
                options=OptionsSnapshot(),
                stage1_pass=False,
                stage1_reasons=[f"fetch failed: {exc}"],
            )

    if args.all_us:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            analyses = list(executor.map(_analyze_symbol, tickers))
    else:
        analyses = []
        for sym in tickers:
            analyses.append(_analyze_symbol(sym))

    analyses.sort(key=lambda a: (0 if a.stage1_pass else 1, summary_verdict(a), a.symbol))

    sector_counts = sector_spread(analyses)
    tradeable = [a for a in analyses if a.stage1_pass]
    tradeable_total = len(tradeable)
    sector_warning = None
    if tradeable_total:
        top_sector, top_count = sector_spread(tradeable)[0]
        top_share = top_count / tradeable_total
        if top_share > args.max_sector_share:
            sector_warning = (
                f"{top_sector} is {top_share:.0%} of Stage 1 pass names;"
                f" consider diversifying below {args.max_sector_share:.0%}."
            )

    if args.output == "json":
        payload: Dict[str, Any]
        if args.all_us:
            ranked = rank_stage1_candidates(analyses)
            payload = {
                "universe": "sec_company_tickers",
                "tickers_scanned": len(tickers),
                "stage1_pass_count": len(ranked),
                "sector_spread": sector_counts,
                "sector_warning": sector_warning,
                "stage1_passes": [
                    {
                        "symbol": a.symbol,
                        "price": a.quote.price,
                        "sector": a.quote.sector,
                        "iv_rank": a.barchart.iv_rank,
                        "iv_percentile": a.barchart.iv_percentile,
                        "implied_vol": a.barchart.implied_volatility,
                        "options_volume": a.options.total_volume,
                        "open_interest": a.options.total_open_interest,
                        "atm_spread": a.options.atm_bid_ask_spread,
                        "market_cap": a.quote.market_cap,
                    }
                    for a in ranked
                ],
                "all_results": [
                    {
                        "symbol": a.symbol,
                        "verdict": summary_verdict(a),
                        "stage1_pass": a.stage1_pass,
                        "stage1_reasons": a.stage1_reasons,
                        "stage2_kills": a.stage2_kills,
                        "stage2_flags": a.stage2_flags,
                        "quote": dataclasses.asdict(a.quote),
                        "barchart": dataclasses.asdict(a.barchart),
                        "options": dataclasses.asdict(a.options),
                        "stage3": a.stage3,
                    }
                    for a in analyses
                ],
            }
        else:
            payload = [
                {
                    "symbol": a.symbol,
                    "verdict": summary_verdict(a),
                    "stage1_pass": a.stage1_pass,
                    "stage1_reasons": a.stage1_reasons,
                    "stage2_kills": a.stage2_kills,
                    "stage2_flags": a.stage2_flags,
                    "quote": dataclasses.asdict(a.quote),
                    "barchart": dataclasses.asdict(a.barchart),
                    "options": dataclasses.asdict(a.options),
                    "stage3": a.stage3,
                }
                for a in analyses
            ]
        print(json.dumps(payload, indent=2, default=str))
        return 0

    if args.output == "csv":
        write_csv_output(analyses, all_us=args.all_us, csv_path=args.csv_path)
        return 0

    # Markdown output.
    print(f"# Market Screener Report\n")
    print(f"Generated: {dt.datetime.now().isoformat(timespec='seconds')}\n")
    if args.all_us:
        ranked = rank_stage1_candidates(analyses)
        print("## Universe")
        print(f"- Source: SEC company ticker map")
        print(f"- Tickers scanned: {len(tickers)}")
        print(f"- Stage 1 passes: {len(ranked)}")
        if sector_counts:
            print("- Sector spread:")
            for sector, count in sector_counts:
                print(f"  - {sector}: {count}")
        if sector_warning:
            print(f"- Diversification warning: {sector_warning}")
        print("")
        print("## Stage 1 survivors")
        for idx, a in enumerate(ranked, start=1):
            spread_text = f"${a.options.atm_bid_ask_spread:.2f}" if a.options.atm_bid_ask_spread is not None else "n/a"
            print(
                f"{idx}. {a.symbol} | price {a.quote.price if a.quote.price is not None else 'n/a'} | "
                f"sector {a.quote.sector if a.quote.sector else 'n/a'} | "
                f"implied vol {a.barchart.implied_volatility if a.barchart.implied_volatility is not None else 'n/a'} | "
                f"options vol {a.options.total_volume if a.options.total_volume is not None else 'n/a'} | "
                f"OI {a.options.total_open_interest if a.options.total_open_interest is not None else 'n/a'} | "
                f"spread {spread_text}"
            )
        return 0
    if sector_counts:
        print("## Sector spread")
        for sector, count in sector_counts:
            print(f"- {sector}: {count}")
        if sector_warning:
            print(f"- Diversification warning: {sector_warning}")
        print("")
    for a in analyses:
        print(render_analysis(a, stage2_ran=not args.stage1_only))
        print("\n---\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
