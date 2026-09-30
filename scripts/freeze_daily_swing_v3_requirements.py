"""Renders docs/DAILY_SWING_V3_REQUIREMENTS.md from edgelab.daily_swing_v3_spec.SPEC and records its hash in the registry (NOTE event).
Idempotent. Run BEFORE the audit; the audit refuses to run unless the registered hash equals the current SPEC hash."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edgelab.daily_swing_v3_spec import GATE_NAME, SPEC, SPEC_SHA256
from edgelab.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
S = SPEC
L = [f"# {GATE_NAME} -- requirements (version {S['version']})", "",
     f"Spec hash (sha256 of the canonical JSON in `edgelab/daily_swing_v3_spec.py`): `{SPEC_SHA256}`", "",
     "A **fourth, separate** gate: it CORRECTS DAILY_SWING_V2, whose OPEN verdict was withdrawn after an adversarial review (registry NOTE GATE_RELIANCE_WITHDRAWN). V1 and V2 are unchanged. "
     "Shared parameters are copied from V2; the corrections are listed in the spec. Thresholds new in V3 (R5c, R6d, R6f) were set knowing the V2 measurements (not blind). "
     "Requirements are labelled substantive or construction_check so a check that cannot fail is never mistaken for evidence. "
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
L += ["", "## Hard requirements (the gate is OPEN only if every one passes)", "", "| id | kind | requirement | comparison |", "|---|---|---|---|"]
for r in S["requirements"]:
    L.append(f"| {r['id']} | {r.get('kind', '')} | {r['text']} | {r['metric']} {r['op']} {r['threshold']} |")
L += ["", "## Accepted limitation (authorised, quantified, recorded, not a blocker)", ""] + [f"- `{k}`: {v}" for k, v in S["accepted_limitations"].items()]
L += ["", "## Declared limitations (not gated, always stated in the report)", ""] + [f"- {x}" for x in S["declared_limitations_not_gated"]]
(ROOT / "docs" / "DAILY_SWING_V3_REQUIREMENTS.md").write_text("\n".join(L) + "\n")

reg = Registry(ROOT / "registry" / "registry.sqlite")
SUPERSEDED = {"94fed561fafd1dee305aabda0eeb87e1fcce10cd52adb8237a571c23901a26fc":
              "First real-data run of the V3 pipeline (no V3 audit result was recorded) left two twin pairs, FISV/FI (533 sessions) and DOC/HCP (213), because the twin rule required 90% of the WHOLE overlap to be identical "
              "and these are re-used tickers whose earlier history is a different issuer. The rule now tests identity within the identical stretch. This changes a frozen rule after seeing that result; disclosed here."}
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
