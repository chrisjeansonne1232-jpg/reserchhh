"""Renders docs/DAILY_SWING_V1_REQUIREMENTS.md from edgelab.daily_swing_spec.SPEC and records its hash in the registry (NOTE event).
Idempotent. Run BEFORE the audit; the audit refuses to run unless the registered hash equals the current SPEC hash."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.daily_swing_spec import GATE_NAME, SPEC, SPEC_SHA256
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
S = SPEC
L = [f"# {GATE_NAME} -- requirements (version {S['version']})", "",
     f"Spec hash (sha256 of the canonical JSON in `edgelab/daily_swing_spec.py`): `{SPEC_SHA256}`", "",
     "A **second, separate** discovery gate. The existing gate (`overnight_news_open_to_close`) and its requirements are not modified and remain BLOCKED for its own reasons. "
     "All parameters and thresholds below were fixed before any universe-level statistic was computed; they are recorded in the append-only registry and the audit refuses to run if they change. "
     "A change means a new version, never an edit. **Passing this gate does not start strategy discovery; that needs explicit confirmation.**", "",
     "## Scope", ""]
L += [f"- **{k}**: {v if not isinstance(v, list) else ', '.join(v)}" for k, v in S["scope"].items()]
L += ["", "## Identity", ""] + [f"- **{k}**: {v}" for k, v in S["identity"].items()]
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
(ROOT / "docs" / "DAILY_SWING_V1_REQUIREMENTS.md").write_text("\n".join(L) + "\n")

reg = Registry(ROOT / "registry" / "registry.sqlite")
have = [e for e in reg.events("NOTE") if e["payload"].get("spec_sha256") == SPEC_SHA256]
if have:
    print("already registered at seq", have[0]["seq"])
else:
    ev = reg.append("NOTE", {"kind": "GATE_REQUIREMENTS_FROZEN", "experiment": GATE_NAME, "version": S["version"], "spec_sha256": SPEC_SHA256, "spec": SPEC})
    print("registered at seq", ev["seq"])
print("chain valid:", reg.verify_chain(), "| sha256", SPEC_SHA256)
