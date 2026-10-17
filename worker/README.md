# Telemetry receiver (Cloudflare Worker)

Receives the batches `clyde telemetry` sends and keeps **daily counters only** in D1. It re-checks every event against `schema.json`,
refuses the whole batch if one event is off it, never reads the sender's address or headers, and never stores an event or an install id.
An install is counted once a day through `sha256(SALT:day:id)`, kept for at most three days.

## Deploy your own

```bash
cd worker
npx wrangler login
npx wrangler d1 create clyde-telemetry          # put the printed database_id in wrangler.toml
npx wrangler d1 execute clyde-telemetry --remote --file=schema.sql
openssl rand -hex 32 | npx wrangler secret put SALT
npx wrangler deploy                             # needs a workers.dev subdomain registered on the account
```

Then point Clyde at it: `clyde telemetry endpoint https://clyde-telemetry.<your-subdomain>.workers.dev/`.

## Keep the schema in step

`schema.json` is generated from `SCHEMA` in `src/telemetry.py`. After changing the schema, run `python3 tools/export_telemetry_schema.py`
and redeploy; `tests/test_worker_schema.py` fails if the two differ.

## Read the numbers

```bash
npx wrangler d1 execute clyde-telemetry --remote --command \
  "SELECT day, event, field, value, n, total FROM counts WHERE day >= date('now','-7 day') ORDER BY day, event, field, value"
```

`n` counts events; for count fields (`turns`, `tool_calls`…) `total / n` is the average. `_install` rows count active installs per day by
version, OS, architecture, Python and RAM bucket.

## Test

```bash
node --test tests/worker.test.mjs               # from the repo root; runs the real SQL through node:sqlite
```

Anyone can still send well-formed fake events, so treat the counts as indicative. A Cloudflare rate-limit rule on the Worker's route is an
optional extra.
