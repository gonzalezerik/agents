"""Deterministic risk-register math for capability #9 (`risk_manager.py`).

Pure functions over plain data -- no Jira, LLM, or DB -- so every number the
risk review reports is reproducible and unit-testable. Per LUNA's JEV
pattern, the model never does arithmetic: the Decision Engine only proposes
a Likelihood/Impact for a *new* risk (`risk_manager.propose_risks`); scoring,
banding, staleness and milestone exposure all happen here, in code.

## Conventions (team policy, not physics -- tune them in one place)

- Likelihood and Impact are the 1-5 `Risk Likelihood` / `Risk Impact` Jira
  custom fields set up by `seed/seed_jira.py`; `Risk Score` = L x I.
- Score bands: LOW 1-4, MEDIUM 5-12, HIGH 15-25. (L x I over 1..5 never
  produces 13 or 14, so the bands have no gap in practice.)
- `LIKELIHOOD_PROBABILITY` maps each likelihood level to a probability of
  occurrence for the milestone-exposure numbers. It is the same convention
  the L scale's labels state ("Possible (~40%)", ...) so the two never drift.
- Milestone exposure treats open risks as **independent** events. Real risks
  are often correlated (one late motor order hits Chassis and Excavation),
  so `p_any_major` is an approximation, labelled as such in the report.

Levels are always rendered as words (LOW/MEDIUM/HIGH), never colour alone,
so the Discord/Slack text stays meaningful to screen-reader users (WCAG
1.4.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

LIKELIHOOD_PROBABILITY: dict[int, float] = {1: 0.05, 2: 0.2, 3: 0.4, 4: 0.6, 5: 0.85}

LIKELIHOOD_LABELS = [
    "Remote (~5%): would take an unusual chain of events",
    "Unlikely (~20%)",
    "Possible (~40%)",
    "Likely (~60%)",
    "Near certain (~85%+): expect it unless we act",
]
IMPACT_LABELS = [
    "Minimal: absorbed inside the subteam, no milestone impact",
    "Minor: < 1 week slip or small rework, inside budget reserve",
    "Moderate: 1-3 week slip, a requirement at risk, or reserve consumed",
    "Major: milestone missed or a key rover function degraded at test",
    "Severe: cannot compete at a milestone, safety incident, or rover lost",
]

MEDIUM_FROM = 5
HIGH_FROM = 15
MAJOR_IMPACT = 4  # impact >= this counts toward a milestone's p_any_major
STALE_AFTER_DAYS = 14
MILESTONE_WINDOW_DAYS = 21


def level(score: int) -> str:
    if score >= HIGH_FROM:
        return "HIGH"
    if score >= MEDIUM_FROM:
        return "MEDIUM"
    return "LOW"


def level_from_score_answer(score: float, n_levels: int = 5) -> int:
    """`ScoreAnswer.score` is a probability-weighted 0-based level index;
    the Jira fields are 1-based."""
    return max(1, min(n_levels, round(score) + 1))


@dataclass
class RiskItem:
    key: str
    summary: str
    components: list[str]
    assignee: str | None
    status: str
    updated: date | None
    likelihood: int | None
    impact: int | None
    score_field: float | None
    milestones: list[str] = field(default_factory=list)
    link_count: int = 0

    @property
    def scored(self) -> bool:
        return self.likelihood is not None and self.impact is not None

    @property
    def score(self) -> int | None:
        return self.likelihood * self.impact if self.scored else None  # type: ignore[operator]

    @property
    def probability(self) -> float | None:
        return LIKELIHOOD_PROBABILITY[self.likelihood] if self.likelihood else None


def _as_level(value: Any) -> int | None:
    """Jira float fields come back as e.g. `3.0`; anything outside 1..5 is
    treated as unscored rather than silently clamped."""
    if value is None:
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return int(n) if n.is_integer() and 1 <= n <= 5 else None


def parse_risk_issue(issue: dict[str, Any], field_map: dict[str, str]) -> RiskItem:
    f = issue.get("fields", {})
    updated_raw = f.get("updated")
    updated = (
        datetime.fromisoformat(updated_raw.replace("Z", "+00:00")).date() if updated_raw else None
    )
    score_raw = f.get(field_map["risk_score"])
    return RiskItem(
        key=issue["key"],
        summary=f.get("summary") or "",
        components=[c.get("name") for c in f.get("components") or []],
        assignee=(f.get("assignee") or {}).get("displayName"),
        status=(f.get("status") or {}).get("name", ""),
        updated=updated,
        likelihood=_as_level(f.get(field_map["risk_likelihood"])),
        impact=_as_level(f.get(field_map["risk_impact"])),
        score_field=float(score_raw) if score_raw is not None else None,
        milestones=[v.get("name") for v in f.get("fixVersions") or []],
        link_count=len(f.get("issuelinks") or []),
    )


def matrix(risks: list[RiskItem]) -> dict[tuple[int, int], list[str]]:
    """(likelihood, impact) -> risk keys, for scored risks only."""
    cells: dict[tuple[int, int], list[str]] = {}
    for r in risks:
        if r.scored:
            cells.setdefault((r.likelihood, r.impact), []).append(r.key)  # type: ignore[arg-type]
    return cells


def render_matrix(risks: list[RiskItem]) -> str:
    """5x5 text grid, likelihood rows (5 at top) x impact columns. Each cell
    shows its band initial and count, e.g. `H2` = two HIGH risks."""
    cells = matrix(risks)
    lines = ["L\\I    1    2    3    4    5"]
    for lik in range(5, 0, -1):
        row = []
        for imp in range(1, 6):
            n = len(cells.get((lik, imp), []))
            row.append(f"{level(lik * imp)[0]}{n}" if n else " . ")
        lines.append(f"{lik}   " + "  ".join(f"{c:>3}" for c in row))
    return "\n".join(lines)


@dataclass
class Finding:
    key: str
    kind: str
    detail: str


def review(
    risks: list[RiskItem],
    *,
    today: date,
    milestone_dates: dict[str, date],
    stale_after_days: int = STALE_AFTER_DAYS,
) -> list[Finding]:
    """The weekly-review checklist a risk manager would run by hand."""
    out: list[Finding] = []
    for r in risks:
        if not r.scored:
            out.append(Finding(r.key, "unscored", "Likelihood and/or Impact not set (need 1-5)"))
            continue
        if r.score_field is not None and r.score_field != r.score:
            out.append(
                Finding(
                    r.key,
                    "score_out_of_sync",
                    f"Risk Score field is {r.score_field:g} but L x I = {r.score}",
                )
            )
        if r.assignee is None:
            out.append(Finding(r.key, "no_owner", "No assignee owns this risk"))
        if r.updated and (today - r.updated).days > stale_after_days:
            out.append(Finding(r.key, "stale", f"Not updated in {(today - r.updated).days} days"))
        if level(r.score) == "HIGH":  # type: ignore[arg-type]
            if r.link_count == 0:
                out.append(
                    Finding(
                        r.key,
                        "high_without_mitigation",
                        "HIGH risk with no linked mitigation issue",
                    )
                )
            for m in r.milestones:
                due = milestone_dates.get(m)
                if due and 0 <= (due - today).days <= MILESTONE_WINDOW_DAYS:
                    out.append(
                        Finding(
                            r.key,
                            "high_near_milestone",
                            f"HIGH risk open {(due - today).days} days before {m}",
                        )
                    )
    return out


def _p_any(probabilities: list[float]) -> float:
    p_none = 1.0
    for p in probabilities:
        p_none *= 1.0 - p
    return 1.0 - p_none


def milestone_outlook(
    risks: list[RiskItem], milestone_dates: dict[str, date], *, today: date
) -> list[dict[str, Any]]:
    """Per upcoming milestone: P(at least one Major/Severe-impact risk tagged
    to it occurs), assuming independence, plus how much each contributing
    risk moves that number if it were retired (the best mitigation buys)."""
    out = []
    for name, due in sorted(milestone_dates.items(), key=lambda kv: kv[1]):
        if due < today:
            continue
        tagged = [r for r in risks if name in r.milestones and r.scored]
        major = [r for r in tagged if r.impact >= MAJOR_IMPACT]  # type: ignore[operator]
        probs = [r.probability for r in major]
        p_any = _p_any(probs)  # type: ignore[arg-type]
        drivers = sorted(
            (
                {
                    "key": r.key,
                    "summary": r.summary,
                    "p_any_if_retired": _p_any([p for j, p in enumerate(probs) if j != i]),  # type: ignore[misc]
                }
                for i, r in enumerate(major)
            ),
            key=lambda d: d["p_any_if_retired"],
        )
        out.append(
            {
                "milestone": name,
                "due": due.isoformat(),
                "days_until": (due - today).days,
                "open_risks": len(tagged),
                "major_risks": len(major),
                "p_any_major": p_any,
                "expected_major_events": sum(probs),  # type: ignore[arg-type]
                "drivers": drivers[:3],
            }
        )
    return out


def subteam_exposure(risks: list[RiskItem]) -> dict[str, float]:
    """Sum of probability x impact per component (expected impact points).
    A risk on two components counts toward both."""
    exposure: dict[str, float] = {}
    for r in risks:
        if not r.scored:
            continue
        for comp in r.components or ["Unassigned"]:
            exposure[comp] = exposure.get(comp, 0.0) + r.probability * r.impact  # type: ignore[operator]
    return dict(sorted(exposure.items(), key=lambda kv: -kv[1]))


def render_report(
    risks: list[RiskItem],
    findings: list[Finding],
    outlook: list[dict[str, Any]],
    exposure: dict[str, float],
    *,
    top_n: int = 5,
) -> str:
    """Discord/Slack-ready Markdown summary."""
    scored = sorted((r for r in risks if r.scored), key=lambda r: -r.score)  # type: ignore[operator]
    counts = {b: sum(1 for r in scored if level(r.score) == b) for b in ("HIGH", "MEDIUM", "LOW")}  # type: ignore[arg-type]
    lines = [
        f"**Risk review**: {len(risks)} open risk(s): "
        f"{counts['HIGH']} HIGH, {counts['MEDIUM']} MEDIUM, {counts['LOW']} LOW, "
        f"{len(risks) - len(scored)} unscored.",
        "",
        "```",
        render_matrix(risks),
        "```",
    ]
    if scored:
        lines += ["", f"**Top {min(top_n, len(scored))}**"]
        for r in scored[:top_n]:
            lines.append(
                f"- {r.key} {level(r.score)} {r.score} (L{r.likelihood} x I{r.impact}) "  # type: ignore[arg-type]
                f"{r.summary} | {', '.join(r.components) or 'no subteam'} | "
                f"owner: {r.assignee or 'none'}"
            )
    if outlook:
        lines += [
            "",
            "**Milestones** (chance at least one Major/Severe risk hits; assumes independent risks)",
        ]
        for m in outlook:
            line = (
                f"- {m['milestone']} in {m['days_until']} days: {m['p_any_major']:.0%} "
                f"({m['major_risks']} major of {m['open_risks']} tagged)"
            )
            if m["drivers"]:
                d = m["drivers"][0]
                line += f"; retiring {d['key']} alone brings it to {d['p_any_if_retired']:.0%}"
            lines.append(line)
    if exposure:
        lines += ["", "**Exposure by subteam** (sum of probability x impact)"]
        lines += [f"- {comp}: {val:.1f}" for comp, val in exposure.items()]
    if findings:
        lines += ["", f"**Needs attention** ({len(findings)})"]
        lines += [f"- {f.key}: {f.detail}" for f in findings]
    return "\n".join(lines)
