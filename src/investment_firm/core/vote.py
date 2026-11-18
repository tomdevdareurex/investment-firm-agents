"""Committee vote tally (M2).

Pure, deterministic bookkeeping over analyst views: weighted stance totals,
winner, veto detection and a plain-text rendering for the CIO prompt.  The
vote is *advisory* — the CIO keeps the final ruling (firm.yaml
``committee.cio_can_override_vote``).  No LLM or network access here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .schemas import AnalystView

STANCES = ("BULLISH", "BEARISH", "NEUTRAL")
TIE = "TIE"
DEFAULT_RULE = "weighted_majority_of_stance"
DEFAULT_VETO_MIN_CONVICTION = 3


@dataclass(frozen=True)
class VoteRow:
    role: str
    model: str
    stance: str
    conviction: int
    weight: float
    counted: bool
    note: str = ""


@dataclass
class VoteResult:
    rows: List[VoteRow] = field(default_factory=list)
    totals: Dict[str, float] = field(
        default_factory=lambda: {s: 0.0 for s in STANCES}
    )
    winner: str = TIE
    margin: float = 0.0
    veto: bool = False
    veto_by: List[str] = field(default_factory=list)
    participants: int = 0
    excluded: List[str] = field(default_factory=list)
    rule: str = DEFAULT_RULE
    veto_min_conviction: int = DEFAULT_VETO_MIN_CONVICTION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _spec_attr(spec: Any, name: str, default: Any) -> Any:
    """Read ``name`` from a RoleSpec-like object or a mapping."""
    if spec is None:
        return default
    if isinstance(spec, Mapping):
        return spec.get(name, default)
    return getattr(spec, name, default)


def _cfg(committee_cfg: Optional[Mapping[str, Any]], key: str, default: Any) -> Any:
    if not committee_cfg:
        return default
    value = committee_cfg.get(key, default)
    return default if value is None else value


def tally(
    views: Iterable[AnalystView],
    specs_by_role: Mapping[str, Any],
    committee_cfg: Optional[Mapping[str, Any]] = None,
) -> VoteResult:
    """Weighted majority of stance over the non-ERROR views of voting roles.

    * Roles with ``votes: false`` (or unknown to the roster) and ERROR views are
      excluded and listed in ``excluded``.
    * ``weight`` comes from ``RoleSpec.vote_weight`` (``<= 0`` → 1).
    * ``winner`` is the stance with the highest total, or ``"TIE"`` when the top
      two totals are equal (also when nobody voted).
    * ``veto`` is set when a role listed in ``committee.veto_roles`` holds a
      BEARISH view with ``conviction >= committee.veto_min_conviction``.
    """
    veto_roles = {str(r) for r in (_cfg(committee_cfg, "veto_roles", []) or [])}
    try:
        veto_min = int(
            _cfg(committee_cfg, "veto_min_conviction", DEFAULT_VETO_MIN_CONVICTION)
        )
    except (TypeError, ValueError):
        veto_min = DEFAULT_VETO_MIN_CONVICTION
    rule = str(_cfg(committee_cfg, "tally_rule", DEFAULT_RULE))

    result = VoteResult(rule=rule, veto_min_conviction=veto_min)

    for view in views:
        spec = specs_by_role.get(view.role)
        stance = str(view.stance or "NEUTRAL").upper()
        conviction = int(view.conviction or 0)
        raw_weight = _spec_attr(spec, "vote_weight", 0)
        try:
            weight = float(raw_weight)
        except (TypeError, ValueError):
            weight = 0.0
        if weight <= 0:
            weight = 1.0

        if view.error or stance == "ERROR":
            note = "excluded: ERROR view"
            counted = False
        elif spec is None:
            note = "excluded: role not in roster"
            counted = False
        elif not bool(_spec_attr(spec, "votes", False)):
            note = "excluded: non-voting role"
            counted = False
        elif stance not in STANCES:
            note = "excluded: unknown stance %s" % stance
            counted = False
        else:
            note = ""
            counted = True

        is_veto_role = view.role in veto_roles or bool(
            _spec_attr(spec, "veto", False)
        )
        if (
            is_veto_role
            and not view.error
            and stance == "BEARISH"
            and conviction >= veto_min
        ):
            result.veto = True
            result.veto_by.append(view.role)
            note = (note + "; " if note else "") + "VETO"

        result.rows.append(
            VoteRow(
                role=view.role,
                model=view.model or "",
                stance=stance,
                conviction=conviction,
                weight=weight,
                counted=counted,
                note=note,
            )
        )
        if counted:
            result.totals[stance] = result.totals.get(stance, 0.0) + weight
            result.participants += 1
        else:
            result.excluded.append(view.role)

    ranked = sorted(result.totals.items(), key=lambda kv: (-kv[1], kv[0]))
    top, second = ranked[0], ranked[1] if len(ranked) > 1 else (None, 0.0)
    result.margin = round(top[1] - second[1], 6)
    if top[1] <= 0 or result.margin == 0:
        result.winner = TIE
    else:
        result.winner = top[0]
    return result


def _fmt_weight(w: float) -> str:
    return ("%d" % w) if float(w).is_integer() else ("%.2f" % w)


def render_vote(result: VoteResult) -> str:
    """Plain-text block for the CIO synthesis prompt (deterministic order)."""
    lines: List[str] = []
    lines.append(
        "Rule: %s (weights from firm.yaml; vote is advisory, CIO rules)" % result.rule
    )
    totals = " | ".join(
        "%s %s" % (s, _fmt_weight(result.totals.get(s, 0.0))) for s in STANCES
    )
    lines.append("Totals: %s" % totals)
    if result.winner == TIE:
        lines.append("Outcome: TIE (no majority; the CIO must decide and say why)")
    else:
        lines.append(
            "Outcome: %s by a margin of %s"
            % (result.winner, _fmt_weight(result.margin))
        )
    if result.veto:
        lines.append(
            "VETO raised by: %s (BEARISH with conviction >= %d). The recommendation "
            "cannot be BUY unless you explicitly explain why the veto is overruled."
            % (", ".join(result.veto_by), result.veto_min_conviction)
        )
    lines.append(
        "Participants: %d counted, %d excluded"
        % (result.participants, len(result.excluded))
    )
    for row in result.rows:
        flag = "counted" if row.counted else "not counted"
        extra = (" — %s" % row.note) if row.note else ""
        lines.append(
            "- %s: %s (conviction %d, weight %s, %s)%s"
            % (
                row.role,
                row.stance,
                row.conviction,
                _fmt_weight(row.weight),
                flag,
                extra,
            )
        )
    return "\n".join(lines)
