# Phase 8B Live Founder Evaluation

- Date: 2026-07-19
- Save: `phase8a-live-complete.sav`
- World ID: `spb-1636440848-1049736244`
- Company: `Sim Pilot Founder Test`
- Analyzer: `company_health`
- Model/provider: none
- Model tokens: zero
- OpenTTD writes: disabled

## Live context

The analysis snapshot was complete and contained one selected company with 435 vehicles. A fresh
context capture of the same world contained 22 towns, 84 industries, 199 selected-company stations,
435 vehicles, and 101 inferred routes. Category coverage remained explicitly partial or unavailable
where the protocol does not expose competitor stations, tiles, terrain, infrastructure, native
events, complete economy detail, or path movement.

## Result

The engine produced two evidence-backed findings:

1. Informational: income `1,436,646` plus expenses `-128,334` produced a positive observed operating
   result of `1,308,312`.
2. Opportunity: 360 of 435 vehicles were road vehicles, representing 82.76% of the observed fleet.

No warning or critical company-health finding was produced. The company had no observed loan. The
result disclosed that accounting fields may cover an atypical period, concentration is not
inherently harmful, infrastructure/maintenance expenses are not separated, and company/vehicle
coverage is partial.

## Performance

A separate fresh capture benchmark produced a 1,120,757-byte canonical JSON snapshot:

| Stage | Measurement |
|---|---:|
| Live bridge collection, translation, serialization, and CLI startup | 8.13 seconds |
| Deterministic company analysis, mean of 100 runs | 0.563 milliseconds |
| Deterministic 100-run total | 0.0563 seconds |
| Traced peak during the 100 retained responses | 890,252 bytes |
| Findings per run | 2 |

The founder-observed latency is therefore snapshot-bound, not analyzer-bound. A useful interactive
surface should reuse an already fresh canonical observation when safe or make collection progress
visible; weakening freshness or silently using an old snapshot would not be acceptable.

## Founder rating

```json
{
  "manual_rating": "acceptable",
  "revealed_nonobvious_information": "partially",
  "reviewer_notes": "The financial conclusion appears correct and appropriately cautious. The fleet-concentration finding is valid, but it is not especially useful by itself because it does not connect concentration to profitability, route performance, congestion, or risk. The operating-result summary is useful confirmation rather than a new insight. An approximately 8-second runtime is also too slow for a deterministic, no-model analysis unless most of that time is unavoidable live snapshot collection. This result is trustworthy, but it does not yet demonstrate strong gameplay intelligence."
}
```

The complete structured rating is retained in
[`evaluation/phase8b-founder-results.json`](evaluation/phase8b-founder-results.json).

## Conclusion and next recommendation

Phase 8B proves the trust boundary, deterministic evidence, honest limitations, live read-only
operation, and sub-millisecond analysis. It does not yet strongly prove the product claim that Sim
Pilot regularly reveals something slower to find manually.

Phase 8C should remain read-only and focus on joined insights before adding actions:

- attribute negative profit by vehicle type and inferred route;
- distinguish profitable concentration from concentrated loss exposure;
- connect high station waiting cargo to the vehicles and routes serving that station;
- rank route inspection targets using profit, loss share, station waiting, and evidence quality;
- reuse a sufficiently fresh captured snapshot and expose collection age and progress.

Construction, vehicle mutation, autonomous execution, and predictive profit claims should remain
out of scope until those joined insights earn stronger founder ratings.

