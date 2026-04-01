# API Gateway 503 / Upstream Failure Runbook

This runbook handles elevated `503 Service Unavailable` responses at `api-gateway` caused by degraded upstream services. In SentinelOps simulations, gateway 503 spikes commonly follow payment dependency failures and database latency cascades. The primary goal is to restore reliable request routing while minimizing user-visible disruption.

## Symptoms and confirmation

Begin by confirming that the gateway is failing due to upstream dependency errors rather than gateway process failure. Compare gateway CPU, memory, and event loop health with upstream timeout/error rates. If gateway resources are healthy but upstream failures are high, classify as upstream-induced 503 incident.

Observe these signals:

- increased 503 ratio on payment-related routes
- upstream connection timeout or reset events
- healthy gateway process but failing upstream checks
- retry amplification from clients increasing inbound load
- uneven error distribution across target pools

## Upstream dependency health checks

Check health endpoints and latency for `payment-service` and `auth-service` first. If payment path is failing while auth remains stable, apply targeted routing policy rather than broad failover. Validate that upstream error budgets are breached before making aggressive traffic shifts.

Correlate timestamps with root cause report path. If path includes `db-primary -> payment-service -> api-gateway`, prioritize remediations aligned to dependency stabilization.

## Load balancer and target pool status

Inspect load balancer target health and outlier ejection behavior. Confirm unhealthy instances are not still receiving production traffic. Verify connection draining and keepalive settings to avoid stale upstream sockets.

Immediate mitigation options:

1. drain clearly unhealthy upstream targets
2. increase health check frequency temporarily
3. reduce request timeout mismatch between gateway and upstream
4. ensure retries respect idempotency and budget limits

## Traffic rerouting and safe reduction

Use controlled rerouting to preserve core endpoints:

- prioritize critical user flows
- apply temporary route-level throttles to non-critical endpoints
- shift traffic to healthier regions or pools if available
- enable cached fallback responses where policy allows

Do not route all traffic to a single remaining pool without capacity validation. That can trigger cascading failures in otherwise healthy services.

## Timeout and retry configuration review

Review gateway upstream timeout settings relative to service SLOs. If timeout is too low, false failures increase; too high, connections saturate under slow dependencies. Validate retry settings: retries should be limited, exponential, and avoid retry storms on non-idempotent operations.

For emergency tuning:

- lower concurrent upstream attempts per request
- add retry jitter and cap retries
- enforce per-route timeout budget
- disable optional expensive middleware during incident

## Rollback to last known good config

If incident begins immediately after gateway config or route policy deployment, execute rollback procedure:

1. confirm rollback candidate integrity
2. notify incident channel before rollout
3. apply rollback gradually if platform supports canary
4. validate 503 rate and upstream latency after rollback

Keep synthetic probes running to verify recovery across all primary routes.

## Escalation criteria

Escalate when any condition is met:

- gateway 503 exceeds threshold for 10+ minutes
- no healthy upstream targets for critical routes
- traffic rerouting worsens latency or failure rates
- uncertainty around safe rollback path

Provide escalation package including route-level error heatmap, upstream health timeline, and mitigation attempts already completed.

## Post-stabilization checklist

After 503 rates normalize, keep heightened monitoring for at least 30 minutes. Confirm no hidden queue growth or delayed upstream failures remain. Capture all config changes and command actions for post-incident review to improve future automatic safeguards.
