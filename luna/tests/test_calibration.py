"""Calibration harness (spec §2.4 item 7) -- a small hand-labeled eval set,
reliability bins, and Expected Calibration Error (ECE) against
`LocalDecisionProvider` on the live endpoint.

**This is an explicitly soft target for v1** (CONTRACT.md: "log the number,
don't hard-fail CI on it yet", spec §2.5's honesty requirement that local
models will calibrate worse than Jev's RLCD-trained model). This test does
NOT assert `ECE < 0.10`. It computes and logs the real number (printed, and
written to `calibration_report.md` in the test's tmp output dir), and only
fails on outright infrastructure problems (an exception, a malformed
answer) -- never on the calibration number itself. Tightening this into a
hard gate is a follow-up once there's a real track record of ECE over time
to know what threshold is achievable, not aspirational.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from luna.config import get_settings
from luna.decision.local_provider import LocalDecisionProvider
from luna.decision.schemas import ChoiceQuestion, NoulQuestion

pytestmark = pytest.mark.llm

MOOD_QUESTION = ChoiceQuestion(
    instructions="What mood does this message express?",
    criteria={
        "happy": "positive, upbeat mood",
        "sad": "negative, down mood",
        "angry": "frustrated or hostile mood",
        "neutral": "no strong emotional content",
    },
)

BLOCKER_QUESTION = NoulQuestion(
    instructions="Does this message report that the author is blocked and cannot proceed?"
)

# ~50 hand-labeled examples: 40 mood (Choice) + 10 blocker (Noul), covering
# the kind of text capabilities #1/#4 will actually see (status updates,
# standup chatter). Labels are the author's own judgment, not sourced from a
# public dataset -- documented as such per spec §2.5's honesty requirement.
MOOD_EXAMPLES: list[tuple[str, str]] = [
    ("I'm thrilled with how the demo went today!", "happy"),
    ("Finally got the chassis mount working, feels great.", "happy"),
    ("Team lunch was awesome, morale is high.", "happy"),
    ("So proud of what we shipped this sprint.", "happy"),
    ("Great news -- the budget review passed with no changes.", "happy"),
    ("Excited to start the new excavation subsystem tomorrow.", "happy"),
    ("The sensor calibration finally worked, I'm relieved and happy.", "happy"),
    ("Everyone loved the design review presentation.", "happy"),
    ("This is such a fun problem to work on.", "happy"),
    ("Feeling optimistic about hitting the midpoint showcase deadline.", "happy"),
    ("I'm really disappointed the part didn't arrive in time.", "sad"),
    ("Lost most of today's progress after the crash, feeling down.", "sad"),
    ("Nobody showed up to the standup again, it's discouraging.", "sad"),
    ("The prototype failed its first test, pretty bummed about it.", "sad"),
    ("Feeling burnt out after pulling three late nights in a row.", "sad"),
    ("Sad to see two teammates drop the course this week.", "sad"),
    ("We missed the milestone and I feel awful about it.", "sad"),
    ("It's discouraging how far behind the power budget is.", "sad"),
    ("I'm sorry to report the wiring harness is unusable now.", "sad"),
    ("Kind of a rough week, motivation is low.", "sad"),
    ("This is completely unacceptable, the part was ordered wrong again!", "angry"),
    ("I'm furious that nobody told me about the schedule change.", "angry"),
    ("Why does this keep breaking? So frustrating.", "angry"),
    ("Stop assigning me tasks without asking first, this is ridiculous.", "angry"),
    ("I'm sick of redoing this because requirements keep changing.", "angry"),
    ("This vendor is infuriating, third late shipment in a row.", "angry"),
    ("Absolutely fed up with the flaky CI pipeline.", "angry"),
    ("It's maddening that the same bug keeps coming back.", "angry"),
    ("I'm annoyed we're still arguing about component naming.", "angry"),
    ("Furious that the budget got cut without warning us.", "angry"),
    ("Standup notes: reviewed PRs, updated the wiki, no blockers.", "neutral"),
    ("Meeting moved to 3pm on Thursday, same room.", "neutral"),
    ("Pushed the latest firmware build to the test branch.", "neutral"),
    ("Component field on REQ-PWR-014 updated to Power.", "neutral"),
    ("Attached the updated BOM spreadsheet for review.", "neutral"),
    ("Reminder: design review is next Tuesday at 10am.", "neutral"),
    ("Synced with the excavation subteam about the interface spec.", "neutral"),
    ("Logged today's hours against the chassis epic.", "neutral"),
    ("Updated the risk register with two new entries.", "neutral"),
    ("Transitioned C3-118 to In Review.", "neutral"),
]

BLOCKER_EXAMPLES: list[tuple[str, bool]] = [
    ("I can't proceed until Power finishes the connector spec.", True),
    ("Blocked on the vendor shipment, nothing I can do until it arrives.", True),
    ("Waiting on Systems-Architecture to approve the interface before I continue.", True),
    ("Stuck -- the test rig is broken and I have no way to validate this.", True),
    ("Can't merge until someone reviews the PR, been waiting two days.", True),
    ("Finished the wiring harness today, moving to the next task.", False),
    ("Standup update: no blockers, on track for Friday.", False),
    ("Just a heads up, meeting moved to 3pm.", False),
    ("Reviewed the BOM and everything looks fine.", False),
    ("Wrapped up testing, results attached.", False),
]


@dataclass
class Sample:
    predicted_confidence: float  # max-probability proxy used for ECE
    correct: bool


def _bin_and_ece(samples: list[Sample], n_bins: int = 10) -> tuple[float, list[dict]]:
    bins: list[list[Sample]] = [[] for _ in range(n_bins)]
    for s in samples:
        idx = min(int(s.predicted_confidence * n_bins), n_bins - 1)
        bins[idx].append(s)

    total = len(samples)
    ece = 0.0
    rows = []
    for i, bucket in enumerate(bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        if not bucket:
            rows.append({"range": f"[{lo:.1f}, {hi:.1f})", "n": 0, "acc": None, "avg_conf": None})
            continue
        acc = sum(1 for s in bucket if s.correct) / len(bucket)
        avg_conf = sum(s.predicted_confidence for s in bucket) / len(bucket)
        weight = len(bucket) / total
        ece += weight * abs(acc - avg_conf)
        rows.append(
            {"range": f"[{lo:.1f}, {hi:.1f})", "n": len(bucket), "acc": acc, "avg_conf": avg_conf}
        )
    return ece, rows


def _write_report(path: Path, ece: float, rows: list[dict], n_samples: int) -> None:
    lines = [
        "# LUNA Decision Engine calibration report (v1, soft target)",
        "",
        f"N = {n_samples} hand-labeled examples. ECE = **{ece:.4f}** "
        "(target < 0.10, not enforced in CI yet -- see test docstring).",
        "",
        "| bin | n | accuracy | avg confidence |",
        "|---|---|---|---|",
    ]
    for row in rows:
        acc = f"{row['acc']:.2f}" if row["acc"] is not None else "-"
        conf = f"{row['avg_conf']:.2f}" if row["avg_conf"] is not None else "-"
        lines.append(f"| {row['range']} | {row['n']} | {acc} | {conf} |")
    path.write_text("\n".join(lines) + "\n")


async def test_calibration_ece_on_labeled_set(tmp_path: Path) -> None:
    settings = get_settings()
    provider = LocalDecisionProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=60.0,
    )
    samples: list[Sample] = []
    try:
        for text, gold in MOOD_EXAMPLES:
            answers = await provider.decide(text, {"mood": MOOD_QUESTION})
            answer = answers["mood"]
            samples.append(
                Sample(
                    predicted_confidence=answer.probabilities[answer.choice],
                    correct=(answer.choice == gold),
                )
            )

        for text, gold in BLOCKER_EXAMPLES:
            answers = await provider.decide(text, {"blocker": BLOCKER_QUESTION})
            noul = answers["blocker"].noul
            predicted = noul >= 0.5
            samples.append(
                Sample(
                    predicted_confidence=max(noul, 1 - noul),
                    correct=(predicted == gold),
                )
            )
    finally:
        await provider.aclose()

    ece, rows = _bin_and_ece(samples)
    report_path = tmp_path / "calibration_report.md"
    _write_report(report_path, ece, rows, len(samples))

    accuracy = sum(1 for s in samples if s.correct) / len(samples)
    print(
        f"\n[calibration] N={len(samples)} accuracy={accuracy:.3f} ECE={ece:.4f} "
        f"(soft target <0.10, not enforced) report={report_path}"
    )

    # Soft target: only fail on infrastructure-level nonsense (an ECE
    # outside [0,1] would mean the binning/math itself is broken), never on
    # the calibration number failing to meet the 0.10 aspiration.
    assert 0.0 <= ece <= 1.0
