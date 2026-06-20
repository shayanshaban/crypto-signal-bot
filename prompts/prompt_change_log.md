# Prompt Changelog

## trader_v1.txt — baseline

Initial structure: Guidelines + a 7-step Process. Decision order:
```
1. structure → 2. trend/momentum → 3. volume → 4. S/R → 5. direction
→ 6. LONG/SHORT/NO_TRADE → 7. confidence
```
Stop-loss and RR had no defined order, just two separate guideline lines:
- "Stop loss beyond meaningful structure, not optimized for RR"
- "aim for minimum 1:2 RR"

**Bug observed:**
- These two lines contradicted each other. To hit RR=1:2, the model would pull the stop in tight (e.g. a BTC trade with an unrealistically tight stop that got hit almost immediately).

---

## trader_v2.txt — stop/RR ordering fix

**Change:**
- Added a rule: stop-loss is determined first and **independently of RR** (from structure + ATR), then take-profit from structure, then RR is only calculated afterward.
- If RR < 1:2 → NO_TRADE, instead of shrinking the stop.
- Process steps 8–11 added (previously only 7 steps existed).

**Bug observed:**
- The model sometimes pulled the take-profit from a **higher timeframe** (daily/weekly) even though the entry signal came from 15min (SUI example: TP taken from the daily support at 0.6618 instead of the 15min support at 0.7014 — "level shopping" to manufacture a better RR).

---

## trader_v3.txt — timeframe-locked levels + anti level-shopping

**Change:**
- Stop-loss and take-profit restricted to **only the nearest level from 15min or 4H** (no daily/weekly).
- Explicitly forbade: "if RR doesn't work, reach for a farther level to fix it."
- Added `_nearest_levels()` to `baker.py` — sorted, current-price-relative swing lists instead of a raw unordered list.

**Bug observed:**
- Despite the rule, the model sometimes second-guessed the nearest level **provided by baker** and manually derived a "more meaningful" level from raw 15min candles instead (BTC example: ignored 63404.93 in favor of 63322.96 — this time it made RR worse and produced an incorrect NO_TRADE, not a better one).

---

## trader_v4.txt — locked to baker-provided lists only

**Change:**
- Added a rule that the model may only use the precomputed `Nearest resistances` / `Nearest supports` lists; it is no longer allowed to manually derive levels from raw candle data.

**Status:** drafted, not yet used in backtesting (per project decision: changes are accumulated and compared all at once via the backtester, not pushed to production immediately).

---

## trader_v5.txt — current version under manual testing

**Newly discovered bug:**
- Ambiguity in the phrase **"Add at most 0.5-1x ATR as a noise buffer"** causes the model to sometimes apply the full buffer (correct, conservative RR) and sometimes **skip it entirely** (buffer=0), artificially inflating RR.
- Documented case: two runs ~2 minutes apart, on effectively the same 15min candles and the same levels (`63598.61` / `63788.68`):
  - Run with entry=63667.80 → buffer applied → RR≈0.7–1.0 → **correct NO_TRADE**
  - Run with entry=63650.68 → buffer=0 (skipped) → stop placed exactly at the raw support level → **RR=2.65, a fabricated LONG signal**

**Proposed fix for trader_v6.txt:**
```
* Add EXACTLY 0.75x ATR(entry timeframe) as a mandatory noise buffer
  beyond the nearest level — never less, never more, and never zero.
  This buffer is mandatory in all cases, not optional.
```
(replaces "at most 0.5-1x ATR" with a fixed number and an explicit "mandatory... never zero")

---

## trader_v6.txt — fixed mandatory buffer (planned)

**Change:**
- Replace the buffer range with a fixed, mandatory number (0.75x ATR).
- Removes the "at most" ambiguity that allowed buffer=0.

**Status:** ready to draft, pending backtesting alongside v3/v4.

---

## Pattern summary (quick reference)

Every bug traces back to the same root cause: **wherever the prompt left a range or interpretive freedom** (instead of a precise number/rule), the model exploited it unpredictably — sometimes in its own favor, sometimes against it:

| Version | Source of ambiguity | Direction of exploitation |
|---|---|---|
| v1 | "not optimized for RR" + "min RR=1:2" together | tighter stop to force a nice RR |
| v2 | which timeframe should TP come from? | jumping to a farther (daily) level for better RR |
| v3 | what exactly counts as "meaningful"? | departing from baker's list, sometimes hurting RR |
| v5 | does "at most 0.5-1x" allow zero? | dropping the buffer entirely for a fabricated RR |

**Takeaway for future versions:** every rule needs an exact number or hard limit — never an adjective or an interpretable range.