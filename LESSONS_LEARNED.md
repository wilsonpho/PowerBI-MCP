# EdTA Revenue Dashboard — Lessons Learned

## What got built this session (2026-04-22 → 2026-04-23)

Added a 4th YoY chart ("Revenue by Membership YoY") breaking down membership revenue by product type (Thespian, Junior Thespian, Thespian Troupe, Professional, Honorary Thespian, Associate Troupe Director, Emeritus, Pre-Professional, Troupe Director). Reshuffled the 4 charts into a 2×2 grid, expanded the Products matrix from 5 rows to 13 rows, added a light-blue KPI banner, unified card colors.

### Visual types used
- **All 4 YoY charts are the same type: `clusteredBarChart`.** The new "Revenue by Membership YoY" matches the existing three (Membership Revenue YoY, Joins & New Troupes YoY, Other Revenue Buckets YoY). Initially tried a `pivotTable` (matrix) for the new visual — user corrected that, wanted a chart matching the others.
- Products breakdown (bottom of page) is a `pivotTable` (matrix) — unchanged type, just expanded rows.
- KPI banner is a `textbox` with `visualContainerObjects.background.color` set to light blue.

---

## Key technical lessons

### 1. `KEEPFILTERS` is required when a `CALCULATE` filter references a column that's also in the visual's row context

**Bug symptom:** `Membership Revenue CY` returned `$893,307` for every `PRODUCT_NAME` row instead of per-product values.

**Root cause:** When a CALCULATE filter argument references a column, DAX implicitly wraps it in `FILTER(ALL(column), ...)` — which **replaces** any existing filter on that column from the row context.

```dax
-- BROKEN: NOT(PRODUCT_NAME IN _Excluded) wipes PRODUCT_NAME row filter
CALCULATE(SUM(...), NOT(PRODUCT_NAME IN _Excluded), ...)

-- FIXED: KEEPFILTERS composes with existing filter instead of replacing
CALCULATE(SUM(...), KEEPFILTERS(NOT(PRODUCT_NAME IN _Excluded)), ...)
```

**Rule of thumb:** if a measure filters column X, and the measure will ever be used in a visual that also slices by column X, wrap the filter in `KEEPFILTERS`.

### 2. Reusable measures + row context beat hardcoded SWITCH branches — usually

For the per-bucket totals on `RevenueBuckets`, we use `SUMX(VALUES(Item), SWITCH(Item, "Thespian", ..., ...))` with 13 branches. This works but is verbose.

Cleaner long-term: add a calculated column `Bucket` on `SnF_OrderItemLines` classifying each line (Membership / Shipping / Rush / etc.), then measures become simple `CALCULATE(SUM(TOTAL_PRICE), date filters)` with the Bucket column as the row dimension. Filed as future refactor.

### 3. PBIP visual.json JSON for card backgrounds — know the three layers

Power BI cards have **three** separate "background" properties and they map to different places in Format pane:

| PBIP JSON path                        | Format pane location                                   |
|---------------------------------------|--------------------------------------------------------|
| `visualContainerObjects.background`   | **General tab → Effects → Background** (outer frame) |
| `objects.background`                  | Inner card area on some visual types                  |
| `objects.cards[0].properties.background` | **Visual tab → Cards → Background** (card fill) ← the one that actually colors the card body |

Spent several iterations discovering that the "white square" behind each card was the **Visual tab → Cards → Background**, not the container background. Not well-documented in PBIP schema — easiest to configure via UI and inspect the resulting JSON.

### 4. Z-order matters when adding background shapes

When user adds a decorative shape via PBI Desktop ("Insert → Shape"), it gets assigned a **high z** (in this case 11000) and lands on top of cards. Cards stayed hidden until panel was sent to back.

**Quick fix in JSON:** set panel `position.z` to low value (e.g., 50) and ensure any card with `z=0` is bumped up (PBI assigns z=0 to one card arbitrarily).

**Quick fix in UI:** right-click the shape → **Order → Send to back**.

### 5. Snowflake ETL lag vs DAX bug — always verify with parallel source query

When numbers looked wrong, the first diagnostic was running the same logic directly against Salesforce (via SOQL) and comparing. Every PBI row was lower than SF by a consistent ~1 day's worth of transactions → ETL lag, not a measure bug. Running the same logic in parallel sources is the fastest way to isolate "is my DAX wrong" vs "is my source stale."

### 6. PBI Desktop locks TMDL files — always close before editing

Any save in PBI Desktop (explicit Ctrl+S or auto-save) silently overwrites external TMDL edits. Workflow:
1. Close PBI Desktop fully
2. Edit TMDL via external tool
3. Reopen PBIP — the linter will reformat (property order, whitespace, add `isNameInferred`) but content survives

### 7. KPI card colors — one fontColor property, multiple ways to set it

Each card had `value[0].properties.fontColor` using `ThemeDataColor` with different `ColorId` (4, 5, 6, 7, 8) → 5 different auto-assigned theme colors. Replacing with a literal hex (`#012169`) unified them.

```json
"fontColor": {
  "solid": {
    "color": {
      "expr": {
        "Literal": { "Value": "'#012169'" }
      }
    }
  }
}
```

---

## Filter patterns that worked vs. didn't

| Approach                                                      | Worked? |
|---------------------------------------------------------------|---------|
| Visual-level filter: `ORDER_ITEM_RECORD_TYPE_ID = "<id>"` + exclude 3 discount products | ❌ PBI rendered all product names anyway (filter silently ignored) |
| Visual-level filter: explicit whitelist of 9 `PRODUCT_NAME` values | ✅ Reliable, every time |

When filtering by membership type, prefer **explicit whitelist** over implicit `record type + exclusions`.

---

## For next session
- ETL escalation still pending — data is ~1 day stale
- Consider adding the `Bucket` calculated column on SnF_OrderItemLines to simplify RevenueBuckets measures
- Delete orphan `~/Desktop/EdTA Revenue.pbix` once PBIP confirmed stable

---

# Session 2026-04-24 — ETL stall diagnosis + cost optimization

## What happened

Diagnosed a 3-day data staleness in Power BI. Thespian Troupe CY showed $59,409 when live Salesforce showed $84,784. Traced to a Snowflake resource-monitor quota trip on 2026-04-19 that silently killed the ETL. Fixed by manually triggering Data Manager's Input Run Now, which cascaded automatically to the Snowflake Output connector. Also applied one cost optimization: dropped `AUTO_SUSPEND` on `SYNC_WH` from 600s → 60s, projected to save $30-60/month.

---

## Key technical lessons

### 1. Three-table freshness lockstep is the signature of a Data Manager output stall

When `NU__ORDERITEMLINE__C`, `NU__ORDERITEM__C`, and `NU__MEMBERSHIP__C` all freeze at the same `MAX(CREATEDDATE)`, the problem is not Power BI, not DAX, not the Snowflake connector — it's the Salesforce-side dataflow failing to push to Snowflake. Always the first diagnostic when numbers look low.

### 2. Snowflake quota trips fail silently

2026-04-19: `SYNC_WH_MONITOR` hit its 100-credit monthly quota. Warehouse was auto-suspended. Data Manager syncOut began erroring with "Warehouse cannot be resumed because resource monitor has exceeded its quota." Salesforce Analytics emailed a "Completed With Warnings" notification — which went to Outlook's "Other" inbox and was never read.

**Mitigations to put in place:**
- Email filter rule: route `noreply@salesforce.com` "Completed With Warnings" messages to a flagged folder
- Raise quota with headroom (100 → 200 credits)
- Add graduated notification thresholds (50%, 75%, 90%) before suspend (100%)

### 3. Raising the quota does NOT auto-retry failed jobs

Someone raised the quota sometime between Apr 19 and Apr 24 (monitor usage dropped from ~100 trip-level to 30.97). But the failed Data Manager Output jobs were not automatically retried. Manual trigger was required: Input → SFDC_LOCAL → Run Now → Output cascades.

Never assume "quota fixed → data catches up." Always verify with a `MAX(CREATEDDATE)` query after any ETL incident.

### 4. Power BI drives ~90% of Snowflake cost

April breakdown on `SYNC_WH`:

| User | Queries | Exec time | Share |
|---|---|---|---|
| POWERBI_SERVICE | 214,072 | 648 min | ~90% |
| WIL_NONHUMAN2 (admin) | 10,033 | 69 min | ~10% |
| Salesforce Data Manager loads | — | ~4 min | <1% |

Salesforce → Snowflake ingests are compute-light (`COPY INTO` operations). The cost is dominantly Power BI query activity.

### 5. `AUTO_SUSPEND` is the single highest-leverage cost setting

Default is 600s (10 min). For a dashboard workload with bursty query patterns (PBI fires queries every few minutes during iteration), 600s means the warehouse rarely suspends — it runs nearly continuously during work sessions.

On 2026-04-23, `SYNC_WH` ran ~1 credit/hour for **10 straight hours** (8 AM to 6 PM PDT) → 10 credits → ~$28 for one day. Set to 60s and observed hourly burn dropped to ~0.2 credits/hr during active work.

**Projected monthly savings from `AUTO_SUSPEND 600 → 60`: $30-$60.**

### 6. Per-refresh cost dropped dramatically post-fix

| Setting | AUTO_SUSPEND | Cost per refresh |
|---|---|---|
| Before (600s tail) | 10-min idle after refresh | ~$0.40 |
| After (60s tail) | 1-min idle after refresh | ~$0.05-$0.10 |

So adding scheduled refresh slots in Power BI Service got cheap: 3/day ≈ $7/month, 8/day ≈ $20/month. Easy to add if viewers need fresher data without clicking Refresh manually.

### 7. PBIP format couples Desktop to Service

Unlike classic `.pbix` (fully isolated), the PBIP (project) format lets Desktop refreshes propagate to the Service-hosted dataset. Teams viewers still need to click Refresh to re-render cached visuals, but the underlying data is updated.

This changes the workflow from: "Refresh Desktop → also refresh Service" to just: "Refresh Desktop."

### 8. Teams Refresh is a visual re-render, not a data refresh

Pattern:
- **Dataset refresh** (scheduled or manual in Service) → updates underlying data
- **Teams/Service "Refresh" click** → re-renders visuals against the current dataset
- **Viewer opening Teams fresh** → sees current dataset state, no click needed

So the nightly scheduled refresh at 04:30 UTC handles the common case: viewers opening in the morning see current data. Click is only needed for already-open tabs or for intra-day updates.

### 9. Resource monitor period ≠ calendar month

`SYNC_WH_MONITOR`'s current period started 2026-04-13 (whenever the monitor was last altered). So `USED_CREDITS` on the monitor covers only Apr 13-present, not the calendar month.

For actual dollar costs, query:
```sql
SELECT ROUND(SUM(USAGE_IN_CURRENCY), 2) AS dollars
FROM SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY
WHERE USAGE_DATE >= DATE_TRUNC('MONTH', CURRENT_DATE());
```

Don't use resource-monitor `USED_CREDITS` as a proxy for monthly spend.

### 10. Cross-verify subagent conclusions against independent sources

A research subagent concluded "Power BI values changed legitimately because new data arrived in Snowflake between Apr 22-24." Sounded plausible and internally consistent. But live SOQL at the same time showed $84,784 — meaning Snowflake was missing 175 rows, not that data legitimately moved. The subagent's story was wrong.

Takeaway: when a subagent returns a tidy narrative, cross-check against at least one independent source (SOQL run by the user, a different tool's output, etc.) before accepting.

---

## Snowflake admin snippets worth saving

**Freshness check (30 seconds):**
```sql
SELECT 'OIL' tbl, MAX(CREATEDDATE) FROM SYNC_DB.SYNCOUT.NU__ORDERITEMLINE__C;
SELECT 'OI'  tbl, MAX(CREATEDDATE) FROM SYNC_DB.SYNCOUT.NU__ORDERITEM__C;
SELECT 'M'   tbl, MAX(CREATEDDATE) FROM SYNC_DB.SYNCOUT.NU__MEMBERSHIP__C;
```

**Quota status:**
```sql
SELECT NAME, CREDIT_QUOTA, USED_CREDITS, REMAINING_CREDITS
FROM SNOWFLAKE.ACCOUNT_USAGE.RESOURCE_MONITORS
WHERE NAME = 'SYNC_WH_MONITOR';
```

**Actual month-to-date dollars:**
```sql
SELECT ROUND(SUM(USAGE_IN_CURRENCY), 2) AS dollars
FROM SNOWFLAKE.ORGANIZATION_USAGE.USAGE_IN_CURRENCY_DAILY
WHERE USAGE_DATE >= DATE_TRUNC('MONTH', CURRENT_DATE());
```

**Hourly burn pattern (to spot warehouse-left-running issues):**
```sql
SELECT DATE_TRUNC('HOUR', START_TIME) AS hr, ROUND(SUM(CREDITS_USED), 3) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE WAREHOUSE_NAME = 'SYNC_WH'
  AND START_TIME >= DATEADD('DAY', -3, CURRENT_DATE())
GROUP BY 1
ORDER BY 1 DESC;
```

**Who's using the warehouse:**
```sql
SELECT USER_NAME, COUNT(*) AS queries, ROUND(SUM(EXECUTION_TIME)/1000/60, 2) AS total_min
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE WAREHOUSE_NAME = 'SYNC_WH'
  AND START_TIME >= DATEADD('DAY', -7, CURRENT_DATE())
GROUP BY 1
ORDER BY 3 DESC;
```

---

## For next session

- Raise `SYNC_WH_MONITOR` quota to 200 monthly + add 50/75/90 notification thresholds (cheap insurance; no direct cost unless actually consumed)
- Add a freshness-lag KPI to the Power BI dashboard
- Set up Outlook rule for `noreply@salesforce.com` "Warning" messages
- Continue monitoring April's spend vs May (expected May to be ~$70-$120 with the AUTO_SUSPEND optimization in place)
