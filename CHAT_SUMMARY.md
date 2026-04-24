# EdTA Dashboard — Session Handoff (2026-04-24)

## What happened today

Diagnosed and fixed a 3-day data staleness in Power BI. Root cause was a Snowflake resource-monitor quota trip on 2026-04-19 that silently killed the Salesforce → Snowflake ETL. Also implemented one high-leverage cost optimization and identified more opportunities.

## The discrepancy

| Source | Thespian Troupe CY | Rows |
|---|---|---|
| Live Salesforce SOQL (today) | $84,784 | 587 |
| Snowflake (before fix) | $59,409 | 412 |
| Power BI (before fix) | $59,409 | 412 |

PBI matched Snowflake exactly — both were short 175 rows / ~$25K vs live Salesforce.

## Root cause (definitive)

**2026-04-19:** Snowflake warehouse `SYNC_WH` hit resource monitor `SYNC_WH_MONITOR`'s 100-credit monthly quota. Warehouse auto-suspended.

Evidence: Salesforce Analytics email dated 2026-04-19 5:09 PM reported:
> `SnowflakeSQLException: Warehouse 'SYNC_WH' cannot be resumed because resource monitor 'SYNC_WH_MONITOR' has exceeded its quota.`

The Contact dataflow's `syncOut` node errored with 0 rows written. Similar pattern for other objects. These emails went to Outlook's "Other" inbox and were never acted on.

Data froze in lockstep across the source tables at max `CREATEDDATE = 2026-04-21 09:37:01 UTC`. By the time we investigated, the quota had been raised at some point (used_credits was 30.97/100, down from the trip-level of 100), but Data Manager did **not** auto-retry the failed jobs — they stayed failed.

## Fix applied today

1. **Input side:** Data Manager → Input tab → SFDC_LOCAL → Run Now
2. Waited for Input jobs to complete (~8 min; NU__Membership__c was the long pole at 7+ min)
3. **Output cascaded automatically** to Snowflake — no manual Output trigger needed
4. Refreshed Power BI Desktop (which propagated to Service via PBIP-Fabric coupling)
5. User clicked Refresh in Power BI Service to update the Teams-visible version

## Verification

- Snowflake `MAX(CREATEDDATE)` on NU__ORDERITEMLINE__C: **2026-04-24 11:57:28 UTC** (fresh)
- Snowflake with PBI's filter: **$84,929 / 588 rows** for Thespian Troupe CY
- Power BI dashboard: **$84,929 / 588 rows** — matches Snowflake to the penny
- Within $145 of the user's morning SOQL (expected; live data moved during the day)

## Cost optimization (applied)

- `ALTER WAREHOUSE SYNC_WH SET AUTO_SUSPEND = 60` (was 600)
- User granted `IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO ROLE SYSADMIN` so cost queries work
- **Expected savings: $30-60/month** going forward
- Verified behaviorally: hourly credit burn during heavy work dropped from ~1 credit/hr (old) to ~0.2 credits/hr (new)

## Cost picture

- **April-to-date actual:** $244.11 (81 credits × ~$2.87/credit, Enterprise edition)
- **Historical:** $17 (Jan) / $56 (Feb) / $64 (Mar) — April is ~4× normal
- **Driver:** POWERBI_SERVICE user accounts for ~90% of warehouse execution time (648 min vs 69 min for admin). Almost none from Salesforce Data Manager loads.
- **Per-refresh cost (post-AUTO_SUSPEND fix):** ~$0.05-$0.10 (was ~$0.40 under 600s)
- **Adding refresh schedules is cheap:** 3/day ≈ $7/month, 8/day ≈ $20/month

## Deferred / proposed but NOT applied

- Raise `SYNC_WH_MONITOR` quota from 100 → 200 monthly (currently 30.97/100, low risk but vulnerable to future spikes)
- Graduated notification thresholds on the monitor (50%, 75%, 90%)
- Freshness-lag measure + KPI card in Power BI model (warn when data > 2 days stale)
- Email rule routing Salesforce Analytics "Completed With Warnings" into a flagged folder

## Architecture notes learned this session

- **PBIP (project) format couples Desktop to Service** more tightly than classic `.pbix`. Refreshing in Desktop can propagate to Service. Teams viewers still need to click Refresh to re-render cached visuals.
- **Scheduled refresh** runs daily at 04:30 UTC (≈12:30 AM Eastern) — still the right cadence for this workload.
- **Teams "Refresh" is a visual re-render, not a data refresh.** The data refresh happens in the Service dataset.

## How to detect this issue next time (30-second check)

Paste into Snowflake:
```sql
SELECT MAX(CREATEDDATE) FROM SYNC_DB.SYNCOUT.NU__ORDERITEMLINE__C;
SELECT MAX(CREATEDDATE) FROM SYNC_DB.SYNCOUT.NU__ORDERITEM__C;
SELECT MAX(CREATEDDATE) FROM SYNC_DB.SYNCOUT.NU__MEMBERSHIP__C;
```

If all three are > 24 hours old and in lockstep → Data Manager output stall. Check:
1. Quota status:
   ```sql
   SELECT NAME, CREDIT_QUOTA, USED_CREDITS, REMAINING_CREDITS
   FROM SNOWFLAKE.ACCOUNT_USAGE.RESOURCE_MONITORS
   WHERE NAME = 'SYNC_WH_MONITOR';
   ```
2. If quota is fine → go to Salesforce Data Manager → Jobs Monitor → look for recent Failed or Canceled jobs
3. Fix: Data Manager → Input tab → SFDC_LOCAL → Run Now → wait → Output cascades automatically

## Files touched / state

- Snowflake: `SYNC_WH` auto-suspend changed; SYSADMIN granted IMPORTED PRIVILEGES
- Power BI: no TMDL / measure / visual changes (DAX was correct)
- Git: this file + LESSONS_LEARNED.md committed to main

## Mistakes I made (so they don't recur)

1. **Power BI subagent initially concluded "data legitimately changed."** Wrong — live SOQL proved it was an ETL stall. Always cross-verify subagent conclusions against an independent source.
2. **Claimed Teams is architecturally independent of Desktop.** Wrong for PBIP format. User corrected me.
3. **Quoted April bill as $89 instead of $244.** Confused resource monitor period (Apr 13-24) with calendar month. Always use `USAGE_IN_CURRENCY_DAILY` for actual dollars.
4. **Quoted $0.40/refresh after AUTO_SUSPEND fix.** That was the pre-fix figure; post-fix is $0.05-$0.10.
5. **Hypothesized "expired credentials" for Output failures.** User pointed out Input jobs were running fine with same creds — credentials weren't the issue.

## Next session suggestions

- If time allows: raise `SYNC_WH_MONITOR` quota to 200, add 50%/75%/90% notifications
- If time allows: add freshness-lag measure to PBI model
- Don't touch DAX — it's correct
- Don't restructure Data Manager connector config — it's fine
