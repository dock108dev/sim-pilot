# ADR-029: Software Inc. First Product Atlas

- Status: Accepted
- Date: 2026-07-28

## Context

After teams, office readiness, contracts, and training, the first long-lived company objective is a
small game engine named Atlas. Product setup combines strategy choices, version-sensitive catalog
facts, multiple reversible configuration pages, team assignment, operating-system selection,
price, reviews, long game-time progression, irreversible stage transitions, and solvency risk.
Older guide ordering is not sufficient authority for Software Inc. 1.8.41.

The semantic bridge must remain read only. Product mutations must remain visible and attributable
to current-frame UI gestures. No autonomous loop may run game time or promote merely because a
progress percentage changed.

## Decision

Extend the read-only adapter to `software-inc-readonly-v10` with complete `product_catalog` and
`product_ui` surfaces, individual released-product entities, and current lifecycle fields on work
items. Read current public catalog, `DesignDocumentWindow`, team picker, product, and work-item state
only on Unity's main thread. Keep `gameplay_actions=[]` and never invoke design, work-item, review,
promotion, or UI callbacks from the bridge.

Support exactly Atlas as a Game Engine assigned to Core. Treat the exact visible feature, OS,
category, price, and team selection as the proposal. Require current unlock/prerequisite evidence,
an idle team with observed Programmer and Designer skill, no unresolved game team warning, and no
unsupported server requirement. Recommendations are deterministic, explain material unknowns, and
remain advice rather than strategy fact.

Calculate a conservative reserve bound using current cash minus all observed monthly payroll and
infrastructure cost for at least the rounded-up selected-feature development duration, plus known
one-time cost. Count no forecast revenue. Reject when projected cash falls below the caller's
reserve, including before every irreversible stage transition.

Persist one owner-only Software Inc.-specific Atlas workflow per save until the generic task
runtime composes these capabilities. Bind it to exact save/session identity, configuration,
financial policy, work identity, stage, progress, iteration, hold state, approval, fingerprint, and
increasing bridge sequence. Reconcile known duplicate creation without input; reject unowned Atlas
work rather than silently adopt it.

Use visible UI only and send at most one current-frame gesture before re-observation. Reversible
configuration may precede approval, but the final design click, review charge, iteration, and each
promotion require a new exact default-no approval followed by complete rebinding. Verify creation,
linked review, increased iteration, hold state, cash and reserve, and Design→Alpha→Beta semantic
stage after each applicable input. Never retry sent-but-unverified input.

Advance time only in caller-selected intervals no longer than 30 real seconds and use shielded
cleanup to guarantee pause. Stop the Prompt 7 workflow at verified Beta. Release, marketing,
support, distribution, loans, and revenue policy are excluded.

## Consequences

- Current Software Inc. catalog and design state, rather than guide memory, control feasibility.
- Subjective configuration remains an explainable recommendation and explicit commitment.
- The reserve can reject Atlas even when the current cash balance itself exceeds $50,000; this is
  the intended conservative policy.
- The bridge gains observation breadth without gameplay-write authority.
- Long development requires repeated bounded operator cycles and cannot progress unattended.
- A live creation proof does not prove Alpha or Beta; each stage requires its own current evidence
  and approval.
- Release readiness, marketing, support, and financial-result verification were left to a separate
  future decision. ADR-030 freezes the Software Inc. roadmap and does not authorize that work.
