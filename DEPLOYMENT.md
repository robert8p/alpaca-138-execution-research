# Simple deployment — completely separate app

## 0. Confirm the two required market-data entitlements

1. Confirm Alpaca Algo Trader Plus is active and gives historical `sip` access.
2. Confirm Massive Stocks Starter or a higher Stocks plan is active. The free Basic plan exposes only two years of split history and is not sufficient for the January 2024 start of this locked study.
3. During Render setup, enter `true` for both `ALPACA_SIP_CONFIRMED` and `MASSIVE_ALL_HISTORY_CONFIRMED` only after those checks.

## 1. Create a new Supabase project

1. In Supabase, select **New project**.
2. Use a name such as `alpaca-138-research`.
3. Choose the Frankfurt region and a strong database password.
4. Wait for the project to finish provisioning.
5. Open **Project Settings → Data API** and copy the project URL and `service_role` key.
6. Open **Connect → ORMs** and copy the transaction-pooler PostgreSQL URL.

Do not use the market-data-miner Supabase project. The web pre-deploy command applies the supplied migration automatically.

## 2. Create a new private GitHub repository

1. In GitHub, select **New repository**.
2. Name it `alpaca-138-execution-research`.
3. Select **Private**.
4. Do not initialise it with a README.
5. Extract this package and upload everything inside the extracted folder.
6. Confirm `render.yaml`, `Dockerfile`, `app`, `migrations` and `tests` are at the repository root.
7. Commit the files.

## 3. Create a new Render Blueprint

1. In Render, select **New → Blueprint**.
2. Connect the new GitHub repository.
3. Render should propose exactly:
   - `alpaca-138-research-web`;
   - `alpaca-138-research-worker`.
4. Enter the new Supabase values separately for both services when prompted.
5. For the web service, enter `APP_PASSWORD`.
6. For the worker, enter the Alpaca and Massive API keys.
7. Enter `true` for `ALPACA_SIP_CONFIRMED` and `MASSIVE_ALL_HISTORY_CONFIRMED`.
8. Select **Apply**.

No values from the market-data-miner Render services are linked automatically.

## 4. Verify the deployment

Open the web service's `/health` URL. Success looks like:

```json
{
  "status": "ok",
  "version": "1.0.0",
  "role": "research_only_no_trading"
}
```

The latest migration should be `001_initial.sql`. The worker logs should say `Research worker started`.

## 5. Run the smoke test

1. Open the web application.
2. Sign in with username `rob` and the password supplied to Render.
3. Select **Run smoke test** once.
4. Leave the browser open or close it; the worker continues independently.
5. The run should progress through catalogue, reference data, calendar, splits, daily bars, decision snapshots, exact verification, selection, raw collection, simulation and report.
6. Download the smoke report when complete.

A smoke result is an infrastructure test, not evidence about the strategy.

## 6. Start the full study

1. Select **Start full research run** once.
2. Do not create another full run—the database intentionally permits only one.
3. Leave the Render worker running.
4. A failed API page or restart retries automatically.
5. If the run reaches `failed`, select **Retry and resume** on that same run.

## 7. Open confirmation only after a pass

The dashboard exposes **Open locked confirmation period** only when:

- the 2024–2025 primary report is complete;
- every frozen gate passed;
- the protocol hash is unchanged.

Opening confirmation queues 1 January–19 April 2026. Do not alter code or environment research settings between phases.

## 8. Share the result

Download the phase ZIP from the dashboard and upload it to ChatGPT. The final confirmation classification can justify paper testing only, never direct live deployment. Regulatory fee schedules are code-locked; there is no fee environment variable to retune after results are seen.

## Common recovery actions

- **Missing relation/table:** deploy the web service first and confirm its pre-deploy migration succeeded.
- **HTTP 429:** reduce the relevant requests-per-minute variable and redeploy the worker; resume the same run.
- **Worker restart or memory event:** do nothing initially; stale partitions are reclaimed automatically.
- **Permanent failed partition:** select **Retry and resume**; completed pages and dates are skipped.
- **Supabase Storage error:** confirm the service-role key is correct. The worker creates the private bucket automatically.
- **Protocol hash mismatch:** do not open confirmation. Restore the original package and rerun the primary study from a new, clean project if necessary.
