# DB Primary Latency Spike Runbook

This runbook describes the response process for sustained latency on the primary transactional database in the SentinelOps synthetic environment. Use this document when p95 and p99 query latency increase, transaction times drift from baseline, and dependent services begin emitting timeout errors. Typical leading indicators include elevated connection wait time, lock contention growth, and increasing retries in `payment-service` and `auth-service`.

## Symptoms and detection

Confirm the event is real before taking remediation action. Compare the current latency profile to the trailing one hour baseline and validate that multiple query classes are impacted, not only one endpoint. Check dashboard panels for query duration, active sessions, deadlocks, and pool saturation. Correlate the timeline with upstream incidents so the team can distinguish cause from impact. If latency appears only on one shard or one index path, classify as a targeted performance issue. If all write-heavy workflows degrade simultaneously, classify as broad primary pressure.

Track these signs:

- p95 query latency > 2x baseline for at least 10 minutes
- p99 query latency rising while throughput remains flat
- CPU stable but I/O wait elevated (storage pressure likely)
- Connection pool wait time > 1 second in dependent services
- lock wait events and row-level contention spikes

## Immediate triage steps

1. Stabilize the system before deep diagnosis. Temporarily reduce non-critical background jobs and bulk sync workloads.
2. Enable a short observation window of slow query logging if it is currently disabled.
3. Confirm no planned migration or heavy analytical query started recently.
4. Verify that read-heavy traffic is routed to replicas where safe.
5. Communicate current status to incident channel with timestamps and confidence.

Do not restart the primary as a first action unless the database is unresponsive and approved by incident commander. Restarts can hide root cause and increase customer impact during recovery.

## Query analysis commands and checks

Use safe, read-only commands first. Review top latency contributors and repeated expensive patterns.

- Inspect top slow statements by mean and total execution time.
- Check plans for sudden sequential scans after a release.
- Review bloated indexes and autovacuum lag indicators.
- Verify prepared statement cache behavior in clients.

When querying system views, capture snapshots at least twice, five minutes apart, to avoid chasing transient spikes. Focus on statements tied to `payment-service` and `auth-service` paths during the same interval as gateway errors.

## Connection pool and client behavior

Validate that application connection pools are not over-provisioned relative to database limits. Excessive pool sizes can degrade overall performance by amplifying contention. Confirm timeout configuration is sane: connect timeout, read timeout, retry backoff, and max retry count should prevent retry storms. If clients retry aggressively without jitter, apply temporary backoff increase.

Check for leaked idle-in-transaction sessions. If present, identify owner service and patch quickly; these sessions can block cleanup and worsen lock pressure.

## Index health and storage checks

Confirm critical indexes are valid and not heavily bloated. Review table churn, vacuum lag, and long-running transactions that prevent cleanup. If one table dominates contention, evaluate temporary mitigation such as reducing write parallelism or deferring non-urgent writes. Ensure storage latency metrics are included; database CPU alone can look healthy while disk queue depth causes delay.

## Safe rollback procedure

If latency regression started right after deployment or configuration change, prepare rollback to last known good release:

1. Confirm rollback artifact integrity.
2. Coordinate rollback window with on-call app owners.
3. Roll back gateway and dependent service query-path changes first.
4. Re-check query latency and lock profile after rollback.
5. Keep enhanced monitoring enabled for 30 minutes after stabilization.

Rollback does not end the incident automatically. Keep incident open until metrics remain stable and error rates normalize.

## Escalation criteria

Escalate to database platform owner immediately when any of these occur:

- sustained p99 > 5x baseline for 15 minutes
- write queue backlog growing while retries increase
- deadlocks recurring across multiple business transactions
- customer-visible payment failures above agreed threshold
- uncertainty about safe rollback path

During escalation, include a concise timeline: first detection, mitigation attempts, current status, and requested decision. Preserve query samples, metric screenshots, and change references for post-incident review.
