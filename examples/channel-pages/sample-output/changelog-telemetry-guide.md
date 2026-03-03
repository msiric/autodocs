# telemetry-guide.md — Changelog

## Known Channel Pages Failure Patterns

### 2026-03-03 — Kusto telemetry anomaly (no PR)
**Changed:** Three new Fluid framework error patterns detected in production but not documented in the known failure patterns table: `0x8e4` (new, 1 occurrence in `fluid_load_channel_page`), `Error parsing snapshot response: Invalid code: 101` (persisting, 1 occurrence), and `Entry point of loaded package not a Fluid module` (persisting, 1 occurrence each in load + create).
**Why:** Automated telemetry scanning found error strings in `Scenario_Messaging_View.reason` that do not match any row in the known patterns table. All are low-volume and Fluid-framework-level. Suggested adding as "Unknown" root cause entries to prevent repeated triage.

---
