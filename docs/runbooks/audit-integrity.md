# Runbook: audit-chain integrity failure

## Trigger

`GET /v1/releases/{id}/audit-integrity` returns `valid: false`.

## Response

1. Freeze release mutation and external rollout automation.
2. Record the reported `failed_event_id` and last valid hash without editing the database.
3. Preserve the database, policy, registry manifest, container digest and runtime logs.
4. Compare the last independently exported chain head, if available.
5. Rotate the API key and audit HMAC key if credential compromise is plausible.
6. Determine whether damage is storage corruption, operational repair, unauthorized mutation or key
   compromise.

## Recovery

Do not “repair” the chain in place and then describe it as original. Restore from a verified backup or
start a new release/store, retaining the damaged copy as incident evidence. If the HMAC key was
compromised, earlier locally verified events are not independently non-repudiable.

