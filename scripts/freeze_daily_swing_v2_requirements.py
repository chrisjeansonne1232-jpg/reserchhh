"""Renders docs/DAILY_SWING_V2_REQUIREMENTS.md from edgelab.daily_swing_v2_spec.SPEC and records its hash in the registry (NOTE event).
Idempotent. Run BEFORE the audit; the audit refuses to run unless the registered hash equals the current SPEC hash."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.daily_swing_v2_spec import GATE_NAME, SPEC, SPEC_SHA256
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
S = SPEC
L = [f"# {GATE_NAME} -- requirements (version {S['version']})", "",
     f"Spec hash (sha256 of the canonical JSON in `edgelab/daily_swing_v2_spec.py`): `{SPEC_SHA256}`", "",
     "A **third, separate** gate: V1 plus ONE change (the ticker hand-over identity fix). `DAILY_SWING_V1` (frozen, run, BLOCKED) and the original gate (`overnight_news_open_to_close`) are not modified. "
     "Every V1 parameter and threshold is copied unchanged (a test asserts it). The two NEW requirements, R6c and R6d, were fixed before any V2 statistic was computed, "
     "but NOT blind: R6d's 3% ceiling was set with the V1 audit's estimate (at most 1.77% of member cells after a hand-over) already known. They are recorded in the append-only registry and the audit refuses to run if they change. "
     "A change means a new version, never an edit. **Passing this gate does not start strategy discovery; that needs explicit confirmation.**", "",
     "## Scope", ""]
L += [f"- **{k}**: {v if not isinstance(v, list) else ', '.join(v)}" for k, v in S["scope"].items()]
L += ["", "## Identity", ""]
for k, v in S["identity"].items():
    if isinstance(v, dict):
        L.append(f"- **{k}**:")
        L += [f"  - `{a}`: {b}" for a, b in v.items()]
    else:
        L.append(f"- **{k}**: {v}")
L += ["", "## Point-in-time liquid universe", ""] + [f"- **{k}**: {v}" for k, v in S["universe"].items()]
sr = S["split_resolution"]
L += ["", "## Empirical split resolution", ""]
for k, v in sr.items():
    if isinstance(v, dict):
        L.append(f"- **{k}**:")
        L += [f"  - `{a}`: {b}" for a, b in v.items()]
    else:
        L.append(f"- **{k}**: {v}")
L += ["", "## Hard requirements (the gate is OPEN only if every one passes)", "", "| id | requirement | comparison |", "|---|---|---|"]
for r in S["requirements"]:
    L.append(f"| {r['id']} | {r['text']} | {r['metric']} {r['op']} {r['threshold']} |")
L += ["", "## Accepted limitation (authorised, quantified, recorded, not a blocker)", ""] + [f"- `{k}`: {v}" for k, v in S["accepted_limitations"].items()]
L += ["", "## Declared limitations (not gated, always stated in the report)", ""] + [f"- {x}" for x in S["declared_limitations_not_gated"]]
(ROOT / "docs" / "DAILY_SWING_V2_REQUIREMENTS.md").write_text("\n".join(L) + "\n")

reg = Registry(ROOT / "registry" / "registry.sqlite")
SUPERSEDED = {"1bc1615121e32467a86691fb3224219d354d7b53f32213d334da87fcaa122e2c":
              "A dry run of the V2 audit (temporary registry; no result was recorded) showed that the first identity-mask rule did not satisfy R6c: 11 spells that START inside a hand-over's "
              "ambiguity window were left unmasked (322 member cells, about 0.02% of cells), because a series that starts inside the window is not known to hold a single issuer. "
              "The rule now also masks any spell with a real bar inside the window. No threshold was changed and the rule only removes more cells. This edit was made AFTER seeing that dry-run "
              "result; it is disclosed here and the earlier hash stays in the registry."}
SUPERSEDED["27a969b94597f22f6063634a0e61c6545ddb187ade760fa4bd3898936e8114be"] = (
    "TEXT-ONLY change: requirement R9's wording still named DAILY_SWING_V1 (inherited); it now names DAILY_SWING_V2. No rule, parameter or threshold changed. "
    "Made after the second dry run (which came out OPEN); disclosed here.")
have_old = {e["payload"].get("superseded_spec_sha256") for e in reg.events("NOTE")}
for old, why in SUPERSEDED.items():
    if old != SPEC_SHA256 and old not in have_old and any(e["payload"].get("spec_sha256") == old for e in reg.events("NOTE")):
        reg.append("NOTE", {"kind": "GATE_REQUIREMENTS_SUPERSEDED", "experiment": GATE_NAME, "superseded_spec_sha256": old, "replaced_by_spec_sha256": SPEC_SHA256, "reason": why})
        print("recorded supersession of", old[:12])
have = [e for e in reg.events("NOTE") if e["payload"].get("spec_sha256") == SPEC_SHA256]
if have:
    print("already registered at seq", have[0]["seq"])
else:
    ev = reg.append("NOTE", {"kind": "GATE_REQUIREMENTS_FROZEN", "experiment": GATE_NAME, "version": S["version"], "spec_sha256": SPEC_SHA256, "spec": SPEC})
    print("registered at seq", ev["seq"])
print("chain valid:", reg.verify_chain(), "| sha256", SPEC_SHA256)
