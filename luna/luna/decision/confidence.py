"""Our own documented confidence statistic -- explicitly NOT a Jev clone.

Honest caveat: TypeSafe never publishes Jev's confidence formula,
and the commonly-cited `(p_max - 1/K) / (1 - 1/K)` normalization does not
reproduce TypeSafe's own worked example (Choice probs {0.84, 0.159, 0.001} ->
published confidence 0.596, but that formula yields ~0.760). We do not try to
reverse-engineer or claim parity with Jev's real formula. Instead we ship a
statistic we can fully explain, and we're honest in the audit log and in
`tests/test_calibration.py` that this is *our* number, not Jev's.

## The statistic: normalized-entropy peakedness

For a probability distribution p over K >= 1 outcomes, Shannon entropy
H(p) = -sum(p_i * log(p_i)) ranges from 0 (a single outcome has all the mass
-- maximally peaked) to log(K) (uniform -- maximally flat). We define

    confidence = 1 - H(p) / log(K)          for K > 1
    confidence = 1.0                         for K == 1 (a single option is
                                              certain by construction)

This is 1.0 for a point mass, 0.0 for a uniform distribution over K options,
and monotonically decreasing as the distribution flattens -- which is what
"peakedness" should mean regardless of how many options there are (unlike
plain p_max, which is not comparable across different K). It requires no
information beyond the probabilities we already compute, so it can be
applied uniformly to Choice, Score, and (if ever needed) a 2-outcome Noul
distribution.

Known limitations (documented, not hidden):
- It is symmetric in the non-max outcomes: {0.9, 0.05, 0.05} and
  {0.9, 0.099, 0.001} get different scores (entropy does distinguish them,
  correctly rating the second as more peaked), but it does not specifically
  reward "large margin between 1st and 2nd place" the way a margin-based
  statistic would -- that's a deliberate choice, not an oversight: peakedness
  of the *whole* distribution is what we want, not just a two-outcome gap.
- It says nothing about whether the underlying probabilities are themselves
  well-calibrated (that's what test_calibration.py's ECE harness checks
  separately). A confidently-wrong model still produces a peaked, high
  "confidence" distribution here. Calibration and confidence are different
  questions; guardrails.py treats neither as a substitute for the
  proposal->confirm human gate on writes.
"""

from __future__ import annotations

import math


def normalized_entropy_confidence(probabilities: dict[str, float]) -> float:
    """Compute confidence in [0, 1] from a normalized probability map.

    `probabilities` must already sum to ~1.0 (softmax-normalized upstream).
    """
    if not probabilities:
        raise ValueError("probabilities must be non-empty")

    k = len(probabilities)
    if k == 1:
        return 1.0

    h = 0.0
    for p in probabilities.values():
        if p <= 0.0:
            continue
        h -= p * math.log(p)

    h_max = math.log(k)
    confidence = 1.0 - (h / h_max)
    # Clamp for float noise (e.g. a probability of exactly 0 after rounding).
    return max(0.0, min(1.0, confidence))
