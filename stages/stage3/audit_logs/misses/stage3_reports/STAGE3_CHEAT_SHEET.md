# Stage 3 Diamond Funnel — Workflow Cheat Sheet
**Version:** 2.1 (Updated May 2026 — incorporates Hermes training corrections)
**Purpose:** Single-reference workflow for every Stage 3 analysis. If the output does not match this document, the output is wrong.

---

## BEFORE YOU START — Two Pre-Flight Checks

### Pre-Flight 1: Stage 2 Anomaly Check
Before running any Stage 3, confirm the Stage 2 signal is clean:
- Pull the one-year analyst price target from the Stage 2 report
- Compare it to the current stock price
- **If the analyst target is more than 15% BELOW current price → flag this at the top of the Stage 3 report.** Stage 2 may have passed the stock on IV/volume criteria while the Street is signaling meaningful downside. The Stage 3 must acknowledge this discrepancy and factor it into the scenario weights.

### Pre-Flight 2: Share Count Sanity Check
- Cross-check the share count used in any internal pipeline against the current 10-K/10-Q
- Market cap ÷ current price = implied shares outstanding
- If pipeline share count is more than 10% off from the implied shares → correct it before running scenarios. Stale share counts produce nonsense per-share fair values.

---

## STEP 1 — Category Classification (Hard Gate)

Run this gate first. Everything else depends on it.

| Question | Answer | Result |
|----------|--------|--------|
| Positive net income (TTM)? | YES | → Category A |
| Positive operating cash flow (TTM)? | YES | → Category A |
| Both negative, revenue growing 50%+ YoY? | YES | → Category B |
| Both negative, revenue growing <50% YoY? | YES | → Category A (mature but slow) |

**Special OCF/SBC flag (Category A only):** If OCF is positive but Stock-Based Compensation > OCF, state this explicitly: *"OCF of $X is fully SBC-funded — true economic cash generation is approximately negative $Y/year."* This is a Category A earnings-quality discount, not a reclassification trigger.

**SPAC/warrant liability flag:** Companies that went public via SPAC often carry non-cash warrant fair value changes inside GAAP net income. Check OCF as the primary profitability signal; do not rely on GAAP net income alone for SPAC-origin companies.

---

## STEP 2A — CATEGORY A WORKFLOW

### The Four Diagnostic Tests (MANDATORY — all four, in order, with named headers and verdict lines)

> ⚠️ **HARD RULE:** Every test must appear as a named section header with a one-line verdict. No exceptions. No collapsing tests into prose. If a test is absent, the Stage 3 is incomplete.

---

#### TEST 1: Paradox Test
**Purpose:** Determine whether the most recent annual financials accurately represent the current business reality, or whether a fundamental shift has occurred that the annual numbers don't yet reflect.

**How to run:**
1. State the headline FY number (revenue, net income, OCF)
2. State the most recent quarter's equivalent — is it consistent with the annual picture, or has something broken?
3. If the quarterly picture diverges materially from the annual → the business is in transition and the annual is a rearview mirror

**The question to answer explicitly:** Is this a cyclical dip (recovers), a structural reset (new lower normal), or a full business model change (forward thesis must be rebuilt)?

**Verdict line format:** `Paradox Test → ✅ PASS` / `⚠️ FLAG` / `🚨 FAIL`

**When this test matters most:**
- Any company where revenue has dropped >20% from peak
- Any company mid-pivot (HIMS, ENPH)
- Any company with governance/accounting history (SMCI)
- Any company where Q1/latest quarter contradicts FY results

---

#### TEST 2: Expense Efficiency Test
**Purpose:** Determine whether the company is growing revenue faster than expenses — the fundamental test of operating leverage.

**How to run:**
1. Pull TTM or FY revenue growth rate (%)
2. Pull TTM or FY total operating expense growth rate (%)
3. Compare directly

**Verdict:**
- Revenue growth > Expense growth → ✅ PASS (operating leverage is real)
- Expense growth ≥ Revenue growth → ❌ FAIL (growth is being purchased)
- Revenue growth > Expense growth but by <5 pts → ⚠️ FLAG (thin leverage)

**Also flag:** SBC as % of revenue. If SBC >15% of revenue, note it as an earnings-quality discount. The company is paying heavily in equity which dilutes shareholders regardless of reported profitability.

**Verdict line format:** `Expense Efficiency Test → ✅ PASS / ⚠️ FLAG / ❌ FAIL`

---

#### TEST 3: Segment Contribution Test
**Purpose:** Identify which parts of the business are driving growth, and whether the mix is healthy or deteriorating.

**How to run:**
1. Break revenue into segments (or geographic/product lines if no formal segments)
2. For each segment: revenue, contribution margin, YoY trend
3. Flag any segment where revenue is growing but margins are declining
4. Flag any segment that is masking weakness in another

**Single-segment companies:** If the company reports one segment, pivot the test to: what is driving growth within that segment? (geographic mix, customer tier mix, product mix, new vs. existing customers)

**Key SaaS metrics to use instead of segments:** DBNRR, ARR by customer tier, customer count growth, revenue per customer trend

**Verdict line format:** `Segment Contribution Test → ✅ PASS / ⚠️ FLAG / ❌ FAIL`

---

#### TEST 4: Balance Sheet & Cash Flow Reality Test
**Purpose:** Confirm that reported profits are backed by actual cash, and that the financial foundation supports the forward thesis.

**How to run:**
1. **Liquidity:** Cash + marketable securities. Is it sufficient for 12+ months of operations?
2. **Debt:** Total debt, net debt position (debt minus cash). Debt/EBITDA ratio.
   - <2x → clean
   - 2-3x → manageable
   - 3-4x → yellow flag
   - 4x+ → red flag
3. **Operating cash flow:** Positive? Normalized for one-time items?
4. **One-time items:** Strip out non-recurring items from OCF before calling it "cash generative." Examples: tax credit monetizations, insurance proceeds, asset sales, warrant settlements.
5. **Working capital:** Is inventory or A/R growing faster than revenue? (Demand-pull risk)

**Verdict line format:** `Balance Sheet & Cash Flow Reality Test → ✅ PASS / ⚠️ FLAG / ❌ FAIL`

---

### Category A Scenario Valuation

**Methodology for standard profitable companies:** EV/EBITDA on forward estimates
**Methodology for construction-phase infrastructure developers (APLD-type):** Forward buildout EV approach — see Special Cases section below

**Required table format for each scenario:**

| Item | Bear | Realistic | Bull |
|------|------|-----------|------|
| Forward Revenue | $X | $X | $X |
| EBITDA Margin | X% | X% | X% |
| EBITDA | $X | $X | $X |
| EV / EBITDA Multiple | Xx | Xx | Xx |
| Enterprise Value | $X | $X | $X |
| ± Net Cash / Net Debt | $X | $X | $X |
| Equity Value | $X | $X | $X |
| ÷ Diluted Shares | Xm | Xm | Xm |
| **Per Share Value** | **$X** | **$X** | **$X** |

**Standard Category A probability weights:** 25% Bear / 50% Realistic / 25% Bull
**Exception — governance/quality discount:** If the company carries residual governance risk (SEC investigation, auditor change, filing delays), weight Bear at 30-35% and state the reason explicitly.

**Weighted EV calculation must be shown:**
> `(Bear$ × 25%) + (Realistic$ × 50%) + (Bull$ × 25%) = $XX weighted fair value`

**Category A Margin of Safety:** 20%
> Buy threshold = Weighted FV × 80%
> If current price < buy threshold → ENTRY
> If current price ≥ buy threshold → PASS

**MOS cushion rule:** Always state the dollar and percentage gap between current price and buy threshold. A $1 cushion on a $25 stock (4%) is NOT the same as a $5 cushion on a $25 stock (20%). Thin cushions require explicit sizing guidance — do not present them as full-conviction entries.

---

## STEP 2B — CATEGORY B WORKFLOW

### ⛔ HARD GATE: DO NOT RUN THE FOUR DIAGNOSTIC TESTS ON CATEGORY B COMPANIES

The four tests (Paradox, Expense Efficiency, Segment Contribution, Balance Sheet) are Category A tools. Running them on a pre-profitable company produces either nonsensical results or misleading verdicts. For Category B, proceed directly to the Category B framework below.

---

### Category B Framework (in order)

**1. Cash Runway Assessment**
- Cash + liquid investments on hand
- Annual operational cash burn (OCF, not FCF — exclude capex)
- Implied runway = Cash / Annual burn
- Flag: If runway <2 years with no clear path to fundraising → existential risk
- **Construction-phase companies:** Operational runway and capex funding are separate questions. State both. The capex runway depends on the financing facility (credit line, preferred equity, project finance), not the operational cash.

**2. Revenue Trajectory**
- Year-by-year revenue table
- YoY growth rates — is growth accelerating, steady, or decelerating?
- Contracted/committed revenue (backlog, RPO) vs. reported revenue
- Quality of revenue: product vs. milestone vs. collaboration (lumpy)

**3. Core Technology / Moat Assessment**
- What is the specific technology or capability that creates the moat?
- Is it defensible (patents, know-how, contracts, network effects)?
- Can larger players replicate it in 2-3 years?
- What is the most credible bear case against the moat?

**4. Competitive Position & Management Quality**
- Insider buying/selling during the analysis period
- Management track record on execution vs. guidance
- Key hires or departures
- Capital allocation quality (dilutive raises at bad prices, etc.)

**5. Three Probability-Weighted Scenarios**

**Category B probability weights (NOT 25/50/25):**
- Pessimistic: **35–40%**
- Realistic: **45–48%**
- Optimistic: **13–17%**

*Why the asymmetry: Pre-profitable companies have materially higher execution risk and binary outcomes. The optimistic case is real but rare; the pessimistic case is common. Using 25/50/25 overstates the bull probability.*

**Required scenario table format (same as Category A — show all math):**

| Item | Bear | Realistic | Bull |
|------|------|-----------|------|
| Target Year Revenue | $X | $X | $X |
| EBITDA Margin | X% | X% | X% |
| EBITDA | $X | $X | $X |
| EV Multiple | Xx | Xx | Xx |
| Enterprise Value | $X | $X | $X |
| ± Net Cash / (Net Obligations) | $X | $X | $X |
| Equity Value | $X | $X | $X |
| ÷ Diluted Shares | Xm | Xm | Xm |
| **Per Share Value** | **$X** | **$X** | **$X** |

**Special case — construction-phase infra developers (e.g., APLD):**
- Do NOT use FCF DCF — the company is burning capital to build contracted revenue assets. FCF during construction is meaningless.
- Use Forward Buildout EV: target year = first full year all contracted capacity is operational
- Revenue = contracted capacity × lease rate per MW (or equivalent unit)
- Apply EBITDA margin, appropriate EV multiple, subtract total obligations (debt + preferred equity obligations including MOIC minimums)
- Net obligations must include ALL priority claims ahead of common equity

**Weighted EV (must be shown explicitly):**
> `(Bear$ × 38%) + (Realistic$ × 47%) + (Optimistic$ × 15%) = $XX weighted fair value`

**Category B Margin of Safety:** 50%
> Buy threshold = Weighted FV × 50%
> If current price < buy threshold → ENTRY
> If current price ≥ buy threshold → PASS

---

## STEP 3 — WATCH SIGNAL & KILL SIGNAL (Both Required, Both Must Be Specific)

### Watch Signal Rules

A watch signal is NOT a financial metric or a general business condition. It is a **specific, observable, time-bound operational milestone** that tells you whether the investment thesis is intact or breaking.

**Required elements of every watch signal:**
1. **Named event** — what specifically needs to happen (not "revenue improves," but what causes it)
2. **Named metric or threshold** — the specific number or condition that confirms it
3. **Named timeframe** — the specific quarter or date by which it must occur

**Examples of WRONG watch signals (too generic):**
- ❌ "Revenue stays above X% YoY growth"
- ❌ "Gross margin holds above 40%"
- ❌ "Construction stays on schedule"
- ❌ "EBITDA continues to improve"

**Examples of CORRECT watch signals (specific + named + time-bound):**
- ✅ APLD: *"Polaris Forge 1 ELN-03 (150MW) achieves Ready-for-Service status on or before August 31, 2026 — the first major construction milestone after the initial proof-of-concept building."*
- ✅ HIMS: *"Blended gross margin recovers to ≥67% by Q3 2026 earnings (~November 2026) — confirming the branded GLP-1 unit economics are viable."*
- ✅ IONQ: *"Peer-reviewed publication from a named commercial partner (AstraZeneca, NVIDIA, or national lab) demonstrating quantum-superior results on a real commercial problem — expected by end of 2026."*
- ✅ ENPH: *"Q3 2026 earnings (~October 2026): U.S. residential microinverter shipment volumes show positive YoY growth, confirming the post-25D demand reset is working through the channel rather than permanently repricing the ceiling."*
- ✅ BRZE: *"Q2 FY2027 earnings (~September 2026): customers with ARR ≥$500k exceed 360 AND quarterly bookings growth holds above 25% YoY — confirming BrazeAI is driving net new enterprise wins."*

### Kill Signal Rules

A kill signal is the specific event that invalidates the thesis and requires immediate position review or exit. It must name the actual event, not a financial outcome.

**Examples of WRONG kill signals:**
- ❌ "If gross margin falls below 40%"
- ❌ "If project timing slips"
- ❌ "If revenue growth decelerates materially"

**Examples of CORRECT kill signals:**
- ✅ APLD: *"CoreWeave ($CRWV) announces a material contract renegotiation, payment deferral, or financial covenant breach — CoreWeave represents 69% of APLD's contracted backlog."*
- ✅ HIMS: *"Novo Nordisk obtains a preliminary injunction preventing HIMS from distributing branded Wegovy, OR the FDA issues new guidance restricting GLP-1 DTC telehealth access broadly."*
- ✅ SMCI: *"Any new SEC filing delay, material weakness disclosure, or auditor qualification — given history of filing irregularities."*
- ✅ IONQ: *"IonQ misses its own AQ performance roadmap by more than one generation, OR a named competitor (IBM, Google) demonstrates quantum advantage on a commercial problem ahead of IonQ."*

---

## STEP 4 — FINAL VERDICT

**Required format:**

```
Expected Value: $XX.XX
Buy Threshold (X% MoS): $XX.XX
Current Price: $XX.XX
Verdict: ENTRY / PASS / WATCH
```

**Verdict definitions:**
- **ENTRY:** Current price < buy threshold. State the MoS cushion in dollars and percent.
- **PASS:** Current price ≥ buy threshold. State how far above threshold in dollars and percent.
- **WATCH:** Within 10-15% of buy threshold. State what would need to happen for entry.

**If ENTRY verdict, always add CSP strike guidance:**
- Aggressive strike: X% below current price, 30-45 DTE
- Conservative strike: X% below current price, 30-45 DTE
- Strike floor: Do not sell puts below [level] — cite bear case FV or 52-week low support

---

## SPECIAL CASES

### Governance-Impaired Category A Companies (SMCI-type)
- Apply the Paradox Test first, before any other test — the accounting history makes the financials unreliable until confirmed
- State governance risk explicitly as the primary valuation haircut — not as a footnote or "caveat"
- The standard 20% MoS may be insufficient; state whether 25-30% is more appropriate given residual risk
- Watch signal must name the specific filing or regulatory milestone, not generic "no new issues"

### Mid-Pivot Category A Companies (HIMS-type)
- The Paradox Test is the most critical test — annual financials will almost always look better than the forward reality
- State the pivot explicitly: what business existed before, what business exists now, what is unproven
- Scenario weights may need to shift Bear higher (30%) if the pivot is early-stage and unproven
- Watch signal must anchor to the specific pivot metric, not general business health

### SaaS / High-SBC Companies (BRZE-type)
- Always connect OCF to SBC explicitly: if SBC > OCF, state it clearly
- Non-GAAP operating income is useful for understanding the core business, but GAAP is the reality for shareholders
- Share buybacks offset by high SBC = "defensive buyback," not accretive capital return — state this distinction

### Construction-Phase Infrastructure Developers (APLD-type)
- Operational cash burn ≠ total cash need — separate the two
- Preferred equity and project finance obligations must be included in net obligations (including MOIC minimums, not just principal)
- 15% common equity stakes granted to preferred investors must reduce per-share calculations
- FCF during construction is irrelevant — do not cite it as a valuation input
- Counterparty concentration must be quantified (e.g., "69% of contracted backlog = one pre-profitable tenant")

### Cyclically Depressed Category A Companies (ENPH-type)
- Paradox Test frames the core question: cyclical trough or structural impairment?
- Bear scenario should use revenue BELOW current run rate (not above) if the current quarter is still declining
- Analyst target vs. current price discrepancy (if target < current price) must be flagged at the top of the report

---

## QUICK REFERENCE — SCORING CHECKLIST

Use this to verify every Stage 3 output before finalizing:

**Structure (all required):**
- [ ] Pre-flight 1: Stage 2 anomaly check (analyst target vs. current price)
- [ ] Pre-flight 2: Share count sanity check
- [ ] Step 1: Category classification with gate logic shown
- [ ] Step 2: Correct framework for category (A or B — not mixed)
- [ ] For Category A: All four named tests present with verdict lines
- [ ] For Category B: None of the four tests present (hard gate)
- [ ] Scenario table: Full math shown (revenue → EBITDA → multiple → EV → equity → per share)
- [ ] Probability weights: Explicitly stated before weighted EV
- [ ] Weighted EV: Calculation shown step by step
- [ ] MOS threshold: Correct % applied (20% for A, 50% for B)
- [ ] MOS cushion: Dollar and percent gap stated explicitly
- [ ] Watch signal: Specific event + specific threshold + specific date/quarter
- [ ] Kill signal: Specific event or counterparty named

**Common errors to catch:**
- [ ] Category A tests running on a Category B company → DELETE them
- [ ] FCF DCF on construction-phase infra company → SWITCH to forward buildout EV
- [ ] Generic watch signal ("revenue improves," "margins hold") → REWRITE with named milestone
- [ ] Generic kill signal ("project slips," "margins disappoint") → REWRITE with named event
- [ ] 25/50/25 weights on Category B → SWITCH to 38%/47%/15%
- [ ] SBC > OCF, not stated → ADD the connection explicitly
- [ ] MOS passes by <5% → FLAG as thin margin, add sizing guidance
- [ ] Governance risk buried in footnote → MOVE to primary haircut section
- [ ] Stale share count → CORRECT to current 10-K/10-Q

---

## MARGIN OF SAFETY REFERENCE

| Category | MoS Required | Buy Threshold Formula | Conviction Level |
|----------|-------------|----------------------|-----------------|
| A — Clean balance sheet | 20% | Weighted FV × 0.80 | Standard |
| A — Governance/quality discount | 25–30% | Weighted FV × 0.70–0.75 | Reduced position size |
| A — Thin MoS cushion (<5%) | 20% minimum | Weighted FV × 0.80 | Small position, tight stop |
| B — Standard | 50% | Weighted FV × 0.50 | Speculative sizing |
| B — Binary event risk | 60%+ | Weighted FV × 0.40 | Maximum caution |

---

## PROBABILITY WEIGHT REFERENCE

| Company Type | Bear | Realistic | Bull | Notes |
|-------------|------|-----------|------|-------|
| Category A — stable | 25% | 50% | 25% | Standard |
| Category A — governance discount | 30–35% | 45–50% | 20–25% | Shift Bear up |
| Category A — mid-pivot | 30% | 50% | 20% | Shift Bear up until pivot proven |
| Category B — standard | 38–40% | 45–47% | 13–17% | Never use 25/50/25 for Category B |
| Category B — binary event | 45–50% | 40–45% | 10–15% | Near-term FDA, regulatory, or tech gate |

---

*Document version 2.1 — May 24, 2026*
*Reflects corrections from Hermes training session: IONQ, HIMS, APLD, SMCI, ENPH, BRZE analyses*
