from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set


@dataclass(frozen=True)
class ActionDef:
    key: str
    label: str


# Canonical action keys (minimal stable set). Expand as needed, but do not rename keys.
ACTION_DEFS = [
    ActionDef("ask.chief_complaint", "Ask chief complaint / opening"),
    ActionDef("ask.symptom_history", "Ask symptom history (OPQRST/timeline)"),
    ActionDef("ask.red_flags", "Screen red flags"),
    ActionDef("ask.pm_hx", "Ask past medical history"),
    ActionDef("ask.meds_allergies", "Ask medications and allergies"),
    ActionDef("obtain.consent", "Obtain informed consent / explain stop signal"),
    ActionDef("communicate.teach_back", "Confirm understanding with teach-back"),
    ActionDef("exam.inspect", "Inspection/observation"),
    ActionDef("exam.rom", "ROM testing"),
    ActionDef("exam.neuro_screen", "Neuro screen"),
    ActionDef("exam.special_tests", "Special tests"),
    ActionDef("exam.functional_assessment", "Functional assessment"),
    ActionDef("investigation.request_basic", "Request basic investigations"),
    ActionDef("interpret.results", "Interpret provided results"),
    ActionDef("plan.treatment", "Treatment plan + dosage/progression"),
    ActionDef("advise.self_management", "Education/self-management"),
    ActionDef("advise.safety_net", "Safety netting / when to seek urgent care"),
    ActionDef("plan.reassessment_criteria", "Reassessment/discharge criteria"),
    ActionDef("plan.escalate_or_refer", "Escalate/refer/collaborate"),
]

ACTION_KEYS: Set[str] = {a.key for a in ACTION_DEFS}


def is_known_action_key(action_key: str) -> bool:
    return action_key in ACTION_KEYS


def normalize_allowed_actions(raw: object) -> Set[str]:
    """
    `cases.allowed_actions` currently may contain:
    - canonical keys: "ask.red_flags"
    - legacy free text: "Ask focused subjective history"

    We normalize by:
    - accepting canonical keys as-is
    - mapping a few common legacy strings to keys
    """
    if not raw or not isinstance(raw, list):
        return set()

    out: Set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if s in ACTION_KEYS:
            out.add(s)
            continue
        k = _legacy_string_to_key(s)
        if k:
            out.add(k)
    return out


def _legacy_string_to_key(s: str) -> Optional[str]:
    sl = " ".join(s.lower().split())
    # Very small mapping table (expand only when observed in data)
    mapping: Dict[str, str] = {
        "ask focused subjective history": "ask.symptom_history",
        "ask focused subjective history": "ask.symptom_history",
        "describe/justify objective tests (do not physically perform)": "exam.functional_assessment",
        "explain consent, risks/benefits, and safety-net advice": "obtain.consent",
        "request basic investigations (best-effort; only if clinically indicated)": "investigation.request_basic",
        "propose treatment plan with dosage/progression": "plan.treatment",
        "give education + self-management advice": "advise.self_management",
        "define reassessment/discharge criteria": "plan.reassessment_criteria",
        "identify precautions/contraindications and escalation triggers": "advise.safety_net",
        "describe collaboration/referral plan": "plan.escalate_or_refer",
    }
    for k, v in mapping.items():
        if sl == k:
            return v
    # heuristic contains checks
    if "red flag" in sl:
        return "ask.red_flags"
    if "consent" in sl:
        return "obtain.consent"
    if "teach" in sl and "back" in sl:
        return "communicate.teach_back"
    if "objective" in sl or "test" in sl:
        return "exam.functional_assessment"
    return None

