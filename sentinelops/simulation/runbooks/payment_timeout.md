# Payment Service Timeout Runbook

This runbook is used when `payment-service` reports request timeouts or dependency deadline exceeded errors. In the SentinelOps environment, payment timeout storms are often secondary symptoms caused by `db-primary` latency, connection exhaustion, or retry amplification from upstream callers. The objective is to reduce customer impact rapidly while preserving transactional correctness.

## Symptoms and detection

Confirm the timeout pattern and scope. Review timeout rate by endpoint, operation type, and tenant segment. Determine whether failures are concentrated in authorization, capture, settlement, or reconciliation flows. Compare timeout rate with success latency and in-flight request count.

Watch for the following indicators:

- timeout errors rising faster than raw request volume
- queue backlog growing for payment workers
- elevated dependency latency to `db-primary`
- circuit breaker opening frequently for database calls
- repeated retries from gateway or client SDKs

Correlate with `api-gateway` 503 events and root cause candidates. If `db-primary` is already ranked as top cause, prioritize dependency stabilization before payment-only tuning.

## Dependency health check on db-primary

First validate database health because payment relies heavily on transactional writes and reads. Check query latency, lock contention, and pool wait time. If p95 query latency has doubled and payment timeout count follows the same timeline, classify as dependency-driven incident.

If database health looks normal, investigate payment internals next: thread pools, connection pools, and saturation in async workers.

## Circuit breaker and retry policy review

Verify that circuit breaker thresholds are configured to fail fast when dependency latency spikes. If breaker remains closed despite clear dependency failure, adjust threshold temporarily to protect resources. Retry policy should include exponential backoff with jitter and bounded retry attempts. Unlimited or immediate retries can create self-inflicted outages.

Apply temporary emergency settings if needed:

1. reduce max retries for non-critical operations
2. increase backoff interval with jitter
3. prioritize idempotent operations over expensive reconciliations
4. disable non-essential sync jobs

## Queue backlog and worker health

Inspect processing queues for lag and stuck jobs. If backlog growth is linear and workers are healthy, bottleneck is likely dependency latency. If workers are blocked or crashing, inspect application logs for serialization errors, lock timeouts, or thread starvation.

Use a controlled drain strategy:

- stop new non-critical producers
- let high-priority payment jobs continue
- monitor dequeue latency and dead-letter count
- avoid full queue purge without incident commander approval

## Safe degradation steps

When dependency issues persist, move to safe degradation mode to protect customer trust:

- continue reading payment status where possible
- defer non-critical write-heavy updates
- return clear retryable responses for affected operations
- preserve idempotency keys for replay after recovery

Never bypass core ledger integrity checks. It is safer to fail closed than to commit ambiguous financial state.

## Customer impact assessment

Estimate impact with concrete metrics: failed payment attempts, affected users, revenue at risk, and expected recovery window. Provide updates every 15 minutes with trends, not only snapshots. Coordinate with support and communications teams so user-facing channels provide consistent guidance.

## Recovery and rollback

If the incident aligns with recent deployment, roll back payment query-path changes after verifying artifact health. Validate post-rollback behavior:

- timeout rate declines within two metric intervals
- queue backlog begins draining
- dependency latency stable enough for normal retries

After stabilization, keep elevated monitoring for at least 30 minutes and verify no hidden backlog remains.

## Escalation criteria

Escalate to platform owner and incident commander when:

- timeout rate remains above threshold for 15 minutes
- queue lag continues to grow despite degradation mode
- circuit breaker behavior remains inconsistent
- duplicate or inconsistent payment states are suspected

Capture all evidence for post-incident review: timeout traces, queue statistics, breaker state timeline, and mitigation actions taken.
