# Cache Stampede / Miss Storm Runbook

This runbook addresses cache miss storms and stampede behavior in `cache-service` or dependent clients. A stampede occurs when many requests simultaneously miss cache and overwhelm origin systems. In SentinelOps, cache incidents can amplify database load and indirectly affect payment and authentication paths.

## Symptoms and detection

Identify stampede early by correlating cache hit ratio decline with request surge and origin latency increase. Typical pattern: hit ratio drops, backend reads spike, and p95 latency rises across services that share cache keys.

Key indicators:

- cache hit ratio falls below baseline threshold rapidly
- read traffic to `db-primary` increases unexpectedly
- identical key fetches repeated in short windows
- lock contention around hot keys or invalidation jobs
- elevated timeout rates in dependent services

Distinguish true cache failure from expected miss bursts after deployment. Planned cache invalidations can produce short miss periods without sustained incident impact.

## Initial triage

1. verify cache cluster health, node availability, and memory pressure
2. check eviction rate and key churn trends
3. identify top hot keys and noisy consumers
4. inspect invalidation jobs and deployment events

If cache nodes are healthy but misses remain high, issue is likely application access pattern or TTL strategy.

## Stampede detection and guardrails

Look for repeated concurrent requests for the same expensive key. Enable request coalescing and single-flight locks where available so only one request computes a missing value while others wait. If lock mechanism is absent, apply temporary per-key rate limiting in caller services.

Avoid broad cache disablement as first response. Sudden bypass can overload database and trigger larger incident.

## Lock-based warming and controlled refill

For hot keys, execute controlled warmup:

- select top critical keys by traffic impact
- refresh using one worker per key group
- stagger warmup intervals to avoid synchronized refill
- monitor origin latency while warming

If warmup causes backend pressure, reduce warmup concurrency and extend intervals.

## TTL adjustment strategy

Review TTL values for hot datasets. Very short TTL can trigger repeated recomputation. Increase TTL cautiously for stable data and apply jitter to avoid synchronized expiration. For volatile data, prefer soft TTL plus background refresh instead of hard expiration.

Recommended emergency actions:

1. add random TTL jitter for hot key families
2. increase TTL for non-critical but high-frequency keys
3. enable stale-while-revalidate behavior where safe
4. protect origin with request budgets during refill

## Fallback to database under cache failure

If cache becomes unavailable, enter controlled fallback mode:

- cap fallback QPS to protect `db-primary`
- prioritize critical read paths
- defer non-critical expensive reads
- enable temporary response caching at gateway if possible

Do not allow unrestricted fallback reads. Unbounded fallback can convert cache incident into database outage.

## Escalation criteria

Escalate when:

- hit ratio remains below threshold for 15+ minutes
- origin latency keeps increasing after mitigations
- hot key lock strategy fails to reduce duplicate work
- cache node instability persists across failovers

Include metrics and evidence: key-level miss rates, origin amplification factor, mitigation timeline, and customer impact summary.

## Recovery validation

Confirm recovery by tracking hit ratio normalization, origin read reduction, and latency stabilization. Keep monitoring elevated for at least 30 minutes and ensure no recurring synchronized expiry pattern appears.
