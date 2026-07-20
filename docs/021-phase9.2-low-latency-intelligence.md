# Phase 9.2: Low-Latency Live Intelligence

## Decision

Routine analysis uses a bounded, on-disk snapshot cache plus a lightweight live bridge identity probe. It does not use a long-running collector.

The pre-change live baseline was 7.67 seconds for a cold full collection and 7.66 seconds for an immediate repeated full collection. Orders (about 3.18 seconds), vehicles (about 1.6 seconds), cargo (about 0.99 seconds), and stations (about 0.73 seconds) account for most collection time. The recorded input and results are in `docs/evaluation/phase9_2-latency-baseline.json`; reproduce them with:

```shell
set -a
source /Users/michaelfuscoletti/Documents/OpenTTD/sim-pilot.env
set +a
SIM_PILOT_OPENTTD_ALLOW_WRITES=0 \
SIM_PILOT_OPENTTD_GS_ALLOW_WRITES=0 \
uv run python scripts/profile_phase9_2_latency.py
```

Because repeated full collection showed no meaningful improvement, request-local query optimization alone cannot meet the two-second target. A cache hit avoids all paginated collections and inferred-route reconstruction, while a correlated bridge probe still verifies the active identity before reuse. This is the smallest architecture justified by the measurements.

The post-implementation live gate collected fresh state in 7.677 seconds, then returned the same
identity-bound snapshot in 0.077 seconds at an age of 0.133 seconds. The bridge state was
`identity_verified`, the live save generation was 438, and both write flags were `0`.

## Freshness and compatibility policy

The default maximum reusable age is five seconds. `--max-snapshot-age SECONDS` selects a stricter or looser caller policy, bounded by the cache's 30-second safety ceiling. `--fresh`, `--live`, and a maximum age of zero force a complete collection.

A cached snapshot is returned only after the live probe exactly matches:

- bridge script instance/world identity;
- save generation;
- capability fingerprint;
- observer company identity; and
- active bridge company context.

Missing, partial, expired, corrupt, unverified, or incompatible entries are never returned. Concurrent CLI requests serialize the cache check, probe, and refresh so only one request performs a needed full collection.

The canonical response records snapshot age, source, caller freshness policy, full-collection duration, in-game collection interval, world and company identity, save generation, capability fingerprint, snapshot sequence, verification sequence/time, and bridge synchronization state. JSON always includes this data; `--detailed` renders it. Compact output remains unchanged.

## Safety and authority

Both identity probes and full collections are read-only. The cache introduces no game action, camera control, background monitoring, API, model authority, or persistent collector. Deterministic analyzers remain authoritative, and contextual follow-ups continue to use the retained canonical snapshot.
