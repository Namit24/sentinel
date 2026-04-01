# Auth Service Outage Runbook

This runbook covers outage conditions in `auth-service` affecting token validation and session workflows. In SentinelOps, auth failures can cascade into gateway denial patterns and customer login disruption. The response objective is to restore secure authentication pathways while preserving auditability.

## Symptoms and initial confirmation

Confirm outage scope by measuring authentication error rates, token validation latency, and login success percentage. Validate whether issue is localized to one dependency (cache, database, identity provider) or broad service degradation.

Common indicators:

- login requests failing with timeout or 5xx responses
- token introspection or signature checks timing out
- session lookup failures and cache misses increasing
- increased gateway 401/503 mix with auth traces
- replica lag or database read errors on auth queries

Correlate with deployment timeline and dependency alerts before deciding mitigation sequence.

## Token validation fallback

If external validation backend is slow but available, apply bounded fallback mode:

1. prefer cached token metadata for short grace interval
2. validate token signature locally when key material is fresh
3. reject tokens that exceed grace policy or lack required claims
4. log all fallback validations for post-incident audit

Never disable signature verification entirely. Security controls remain mandatory during incident mode.

## Session cache dependency checks

Inspect session cache health and hit ratio. If cache is unstable, reduce expensive session refresh operations and prioritize active-session validation for critical routes. Confirm cache TTL and eviction behavior; aggressive eviction can simulate auth outage even when service processes are healthy.

If cache miss storm occurs, coordinate with cache runbook procedures and protect auth database with fallback request limits.

## DB read replica failover

If primary auth data reads are degraded, evaluate read replica failover:

- confirm replica freshness is within acceptable staleness
- route read-only token/session lookups to healthy replica
- keep write-path controls on primary to avoid divergence
- monitor failover impact on latency and error rates

Do not switch blindly without validating replica lag. Stale identity state can cause inconsistent access decisions.

## Emergency bypass procedure

Emergency bypass is high-risk and must be tightly scoped. Use only with incident commander approval and security lead awareness.

Bypass guardrails:

- allowlist only minimal internal operations required for recovery
- enforce strict time window and automatic expiry
- preserve full request identity logging
- document every bypass decision in incident timeline

Bypass must never grant broad privileged access to external user traffic.

## Audit log preservation

During outage mitigation, preserve security and compliance evidence:

- record all authentication decision outcomes
- capture fallback mode activation/deactivation times
- store actor identity and reason for manual overrides
- retain raw error fingerprints for forensic analysis

Ensure log pipeline is healthy; if centralized logging lags, spool locally with integrity protections and backfill after recovery.

## Escalation criteria

Escalate immediately if:

- authentication success rate remains below threshold for 10+ minutes
- token validation safety guarantees cannot be maintained
- replica failover cannot meet staleness policy
- emergency bypass requests expand beyond defined blast radius

Escalation packet should include customer impact, current mitigations, security posture, and pending approval decisions.

## Recovery and closure

After service restoration, disable emergency modes in reverse order, confirm normal token and session paths, and run synthetic login checks across critical user journeys. Keep incident open until metrics remain stable and audit logging completeness is confirmed.
