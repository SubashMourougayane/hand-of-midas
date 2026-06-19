# Caddyfile change — route auth + /api/debug + /api/health to General service (5050)

After the Macro retirement (2026-06-19, commit 8246d08), `/api/auth/*`,
`/api/health`, and `/api/debug/*` had no upstream — they were all served by
Gold Macro (5053) which is now retired.

A new minimal `backend-general` service (port 5050) hosts these
cross-cutting routes. The Caddyfile must be updated to point at it.

## Find Caddyfile on VPS

```powershell
type C:\caddy\Caddyfile          # or wherever Caddy reads from
# or query the running config:
curl http://localhost:2019/config/
```

## Diff

For BOTH `midas.subashtrades.in {` and `staging.midas.subashtrades.in {`
blocks, replace these lines:

```diff
-    reverse_proxy /api/gold/* localhost:5053
-    reverse_proxy /api/auth/* localhost:5053
+    # /api/gold/* and /api/oil/* dropped 2026-06-19 (Macros retired).
+    reverse_proxy /api/auth/* localhost:5050
+    reverse_proxy /api/debug/* localhost:5050
     reverse_proxy /api/oil-micro/* localhost:5056
-    reverse_proxy /api/oil/* localhost:5054
-    reverse_proxy /api/health localhost:5053
+    reverse_proxy /api/health localhost:5050
```

Final form:

```caddy
midas.subashtrades.in {

    reverse_proxy /api/micro/* localhost:5055 {
        transport http {
            read_timeout 600s
        }
    }

    reverse_proxy /api/auth/* localhost:5050
    reverse_proxy /api/debug/* localhost:5050
    reverse_proxy /api/oil-micro/* localhost:5056
    reverse_proxy /api/health localhost:5050

    reverse_proxy /* localhost:3001
}
```

(Apply the same change to the `staging.midas.subashtrades.in` block.
Staging frontend port is 3002.)

## Reload Caddy

After editing the Caddyfile:

```powershell
# Standard Caddy reload (zero-downtime):
caddy reload --config C:\caddy\Caddyfile

# Or restart the Caddy service if reload is unavailable:
Restart-Service -Name caddy
```

## Verify

```bash
# Login should now succeed:
curl -X POST https://midas.subashtrades.in/api/auth/login \
  -H "content-type: application/json" \
  -d '{"email":"...","password":"..."}'

# Health probe:
curl https://midas.subashtrades.in/api/health
# {"ok":true,"service":"general","version":"1.0.0"}

# Aggregate debug (Macros absent — only Micros):
curl https://midas.subashtrades.in/api/debug/all-health
```

## Why a separate service vs. mounting on Gold Micro

- **Independence:** Gold Micro restarts/crashes don't kill auth/login.
- **Single source of truth:** cross-cutting concerns belong outside
  trading services.
- **Zero rewrite:** the existing `auth_router` + `build_aggregate_router`
  are imported as-is. `backend-general/main.py` is just a mount point.

## When this can be removed

If/when:
1. Auth moves to a managed identity provider (Auth0, Cognito, etc.)
2. `/api/debug/*` aggregator is replaced by a proper observability stack

Then the General service can be retired alongside the Macros.
