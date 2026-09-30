# Pre-discovery check 2: what the split/discontinuity exclusions removed (diagnostic, no pass/fail)

Registered plan `b0b3b0bbab4e65e1...`. Population: universe-member spells excluded by V2's split/discontinuity rules (one row per spell, its earliest exclusion). Window: 60 sessions of raw close-to-close log return starting AFTER the unobservable event window (split-ambiguous: claimed session + 4; unrecorded jump: the jump session's own close). Benchmark: median 60-session log return of raw PIT members on the same start session (members with a split claim in the window excluded). Excess = name minus benchmark. Names that stop trading inside the window use their last close; no terminal return is assumed. This is not a trial and not a signal search.

Dropped before measurement: {'no_endpoints': 2, 'other_split_in_window': 5} (no usable endpoints, or another split claim inside the window).

| group | n | median excess | mean excess | share negative | 95% CI of median | share stopping in window |
|---|---|---|---|---|---|---|
| all | 119 | -0.0023 | -0.0517 | 0.50 | [-0.131, +0.061] | 0.03 |
| AGREED_SPLIT_TESTABLE_AMBIGUOUS | 42 | -0.2337 | -0.1895 | 0.67 | [-0.427, -0.124] | 0.07 |
| DISPUTED_SPLIT_AMBIGUOUS | 33 | +0.0411 | -0.0245 | 0.45 | [-0.093, +0.135] | 0.00 |
| UNRECORDED_SPLIT_LIKE_DISCONTINUITY | 44 | +0.0516 | +0.0594 | 0.39 | [-0.036, +0.198] | 0.00 |
| excluding_stopped | 116 | +0.0047 | -0.0433 | 0.50 | [-0.124, +0.060] | 0.00 |

Median 60-session log return of the benchmark across events: +0.0356.

**Registered interpretation rule**: |median excess| > 0.02 is a material composition bias. Result: |-0.0023| -> **not material by that rule**. The bootstrap interval is over a small number of names and is wide; 'not material' means 'not distinguishable from small', not 'zero'.

**But the pooled figure hides a subgroup effect** (groups with a 95% CI entirely below zero and |median| > 0.02): `AGREED_SPLIT_TESTABLE_AMBIGUOUS`: n=42, median excess -0.234, CI [-0.427, -0.124]. These are names whose split adjustment cannot be verified from prices (42 of the 43 spells in that cause have a reverse-split claim); they subsequently underperformed the benchmark, so excluding them removes strong losers. The groups with positive medians offset them in the pooled median. Consequence for discovery: strategies that select extreme past losers (reversal longs, or momentum shorts) draw from exactly this pool, so their results must be read with this bias in mind; the pooled rule alone would understate it. The effect on a broad equal-weight book is small (a few names at a time).
