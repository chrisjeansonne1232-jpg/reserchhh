# Pre-discovery check 1: universe-parameter sweep (no returns used)

Registered plan `b0b3b0bbab4e65e1...`. One-at-a-time variations around the frozen V2 baseline; the spell-level split resolution and identity mask are unchanged, membership and the membership-dependent discontinuity exclusions are recomputed for each variant.
Thresholds are V2's (R2b <= 0.5%, R2c <= 5%, R4c <= 5%, R6d <= 3%); R5b is scaled to 0.8 x top_n on >= 99% of sessions (registered clarification, seq 112).

| variant | top_n | lookback | min price | size min/median | R2b | R2c | R4c | R6d | R5b (scaled) | passes |
|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 1000 | 60 | 5.0 | 950/966 | 0.0917% | 0.519% | 2.595% | 0.637% | 1.0000 | **PASS** |
| top500 | 500 | 60 | 5.0 | 474/480 | 0.0660% | 0.830% | 2.962% | 0.653% | 1.0000 | **PASS** |
| top750 | 750 | 60 | 5.0 | 712/723 | 0.0856% | 0.688% | 2.677% | 0.684% | 1.0000 | **PASS** |
| top1500 | 1500 | 60 | 5.0 | 1421/1449 | 0.1040% | 0.490% | 2.766% | 0.544% | 1.0000 | **PASS** |
| lb30 | 1000 | 30 | 5.0 | 950/966 | 0.0999% | 0.623% | 2.577% | 0.652% | 1.0000 | **PASS** |
| lb120 | 1000 | 120 | 5.0 | 953/967 | 0.0825% | 0.518% | 2.475% | 0.608% | 1.0000 | **PASS** |
| px3 | 1000 | 60 | 3.0 | 948/965 | 0.0924% | 0.519% | 2.651% | 0.636% | 1.0000 | **PASS** |
| px10 | 1000 | 60 | 10.0 | 958/969 | 0.0899% | 0.618% | 2.205% | 0.636% | 1.0000 | **PASS** |

Descriptive metrics (not gated):

| variant | median trailing $ volume of members | containment vs baseline | daily entry share | expected missing members (median) | as share of universe | upper bound | member spells ended | mean annual ending hazard |
|---|---|---|---|---|---|---|---|---|
| baseline | 133,316,169 | 1.000 | 0.0035 | 11.0 | 1.100% | 74 | 487 | 6.251% |
| top500 | 274,501,570 | 0.997 | 0.0041 | 5.6 | 1.112% | 74 | 203 | 5.212% |
| top750 | 184,069,642 | 0.998 | 0.0037 | 8.3 | 1.103% | 74 | 344 | 5.880% |
| top1500 | 76,320,893 | 0.998 | 0.0029 | 16.7 | 1.116% | 74 | 795 | 6.798% |
| lb30 | 135,414,356 | 0.967 | 0.0058 | 11.0 | 1.099% | 74 | 572 | 7.348% |
| lb120 | 130,025,557 | 0.967 | 0.0022 | 11.0 | 1.097% | 74 | 409 | 5.235% |
| px3 | 133,612,844 | 0.995 | 0.0033 | 11.0 | 1.101% | 74 | 491 | 6.306% |
| px10 | 131,185,895 | 0.977 | 0.0041 | 11.0 | 1.102% | 74 | 483 | 6.174% |

**Registered criterion**: baseline and at least 6 of the 7 variants pass -> baseline passes: True; variants passing: 7/7; **criterion met: True**.
