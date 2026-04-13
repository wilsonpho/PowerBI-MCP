# CLAUDE.md

## Purpose
This repository contains a Power BI project. Your job is to help safely analyze, modify, and validate the semantic model and related artifacts with minimal risk of corruption.

## Core operating rules
- Be precise, conservative, and evidence-first.
- Prefer small, reviewable changes over broad rewrites.
- Before making changes, explain the plan briefly.
- After making changes, summarize exactly what changed and how it was validated.
- Do not invent model objects, business rules, or source-system meanings. If something is unclear, infer cautiously from the project files and call out uncertainty.

## Source of truth
- The Power BI project files in this repo are the source of truth for structure and intent.
- Treat `.pbip`, TMDL, model metadata, report metadata, and local documentation as authoritative over assumptions.
- If project docs conflict with code/artifacts, call out the conflict explicitly.

## Read vs write behavior
### Read operations
- For understanding the model, prefer reading TMDL / PBIP project files first.
- When analyzing measures, relationships, perspectives, roles, tables, columns, hierarchies, calculation groups, and metadata, inspect the project files directly.
- Build an internal understanding of:
  - tables
  - columns
  - measures
  - relationships
  - calculation groups
  - hierarchies
  - roles / RLS
  - perspectives
  - naming conventions
  - common DAX patterns

### Write operations
- For model changes, prefer the Power BI Modeling MCP server when available.
- Do NOT make semantic model changes through ad hoc text edits if MCP is available for the same task.
- Use MCP for:
  - creating or editing measures
  - adding/removing columns or tables
  - changing relationships
  - editing calculation groups
  - changing model properties
  - validating DAX behavior
- Only fall back to direct file edits when:
  - MCP is unavailable, or
  - the change is clearly limited to documentation or non-model project files.
- If using direct file edits for model-related artifacts, be extra conservative and validate thoroughly.

## Safety rules
- Never delete or rename major model objects unless explicitly asked or clearly required by the task.
- Never make destructive changes to many objects at once without a clear rationale.
- Flag potentially breaking changes before executing them, especially:
  - renamed measures
  - changed relationship cardinality
  - changed filter direction
  - changed data types
  - changed format strings
  - changed RLS
  - changed calculation logic
- Assume the model may be business-critical.

## Preferred workflow
1. Inspect the relevant project files and identify affected objects.
2. Produce a short implementation plan.
3. Make the smallest correct change.
4. Validate using available tooling.
5. Report:
   - files/objects changed
   - DAX or model logic changed
   - risks
   - validation performed
   - follow-up recommendations

## DAX standards
- Prefer readable, maintainable DAX over clever DAX.
- Use variables (`VAR`) when they improve clarity.
- Keep measure names business-friendly and consistent with existing conventions.
- Reuse existing base measures where appropriate.
- Do not duplicate logic that should live in a reusable measure.
- Preserve existing filter semantics unless intentionally changing them.
- For time intelligence, verify the date table assumptions before implementing.
- For performance-sensitive measures, avoid unnecessary iterators and repeated context transitions.
- **Never output DAX with uncertain syntax.** If unsure whether a pattern is valid (e.g., `NOT(... IN {...})` vs table constructor syntax), use a known-good alternative. Do not deliver DAX you would flag as "might not work."
- **Prior YTD comparisons must handle leap years.** Use `MIN(DAY(TODAY()), DAY(EOMONTH(...)))` or `DAYOFYEAR`-based logic so Feb 29 maps to Feb 28 in non-leap years, not March 1.
- For exclusion lists, use `VAR` with a table constructor (`{ "val1", "val2" }`) and `NOT(column IN _variable)` — this is valid DAX and keeps the list maintainable in one place.

## Snowflake integration
- Data flows Salesforce → Snowflake → Power BI.
- Snowflake tables use the same object names as Salesforce (e.g., `NU__MEMBERSHIP__C`).
- **Do not assume normalized lookup tables exist.** Most SF-to-Snowflake replication tools (Fivetran, CData, Stitch) denormalize relationship fields as columns on the source table (e.g., `NU__MEMBERSHIPTYPE2__R__NAME`). Write SQL against denormalized columns unless the schema has been verified.
- Column naming conventions vary by replication tool. Always verify actual column names before running queries.
- Snowflake stores timestamps in UTC. Power BI `TODAY()` uses the service timezone. For daily KPIs this is acceptable; for sub-day precision, handle timezone conversion in the SQL layer.

## Modeling standards
- Respect star-schema principles where possible.
- Prefer explicit naming and consistent display folders.
- Keep fact/dimension responsibilities clear.
- Be cautious with bi-directional filtering; justify it if introduced.
- Avoid adding calculated columns when a measure or upstream transformation is more appropriate.
- Call out modeling smells such as:
  - many-to-many relationships without clear need
  - ambiguous filter paths
  - oversized fact tables with mixed grain
  - inconsistent keys
  - hidden logic duplicated across measures

## Validation requirements
Whenever you modify model logic, validate as many of the following as possible:
- DAX syntax validity
- object references remain valid
- dependencies are not broken
- relationship intent still makes sense
- naming conventions remain consistent
- formatting / display folders remain coherent
- no obvious regressions in dependent measures

If validation cannot be completed, say so explicitly.

## Documentation behavior
- When adding a non-trivial measure or modeling change, include a brief explanation in comments or companion docs if the repo already follows that pattern.
- Preserve existing comments unless they are clearly incorrect.
- Do not generate excessive documentation for trivial edits.

## Output expectations
When completing a task, provide:
- what you changed
- why you changed it
- how you validated it
- any risks or assumptions
- recommended next steps, if relevant

## Project-specific preferences
- Prefer PBIP/TMDL-native workflows.
- Prefer semantic model correctness over speed.
- Prefer maintainability over micro-optimizations unless the task is explicitly performance-focused.
- If asked for performance optimization, identify the likely bottleneck first before changing logic.

## When uncertain
- Stop short of guessing.
- Surface the uncertainty.
- Offer the safest next action based on the files and tools available.
