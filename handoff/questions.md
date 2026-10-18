# Questions before solver design or data correction

1. Does the utility define FromDate and ToDate as inclusive calendar days? What do meter-reading dates mean? Adjacent +1-day evidence supports but cannot establish inclusion.
2. What are Consumption units and scaling, and does it represent a corrected bill total? Are zero bills true zero usage, vacant properties, estimated reads or missing readings?
3. What do ConsumptionType code 40, UnitCount and Capacity mean? What are Capacity units? How should time-varying customer attributes be treated?
4. For duplicate/conflicting/overlapping records, which source authority determines corrections? Do gaps represent absent bills, service breaks or extract restrictions? Audit does not correct them.
5. Is bill_1403 the intended complete population? Why was the top_10000 extract selected, and how are customer IDs allocated? An ordered prefix cannot establish a representative pilot.
6. Are the observed ISO dates Gregorian and local to Asia/Tehran? Confirm billing day boundaries and any partial-day interpretation.
7. Current weather covers the full observed bill envelope and all required UTC brackets. If additional bills extend that envelope, can weather be re-exported to cover their full intervals? Missing boundary values must not be extrapolated silently.
8. What Open-Meteo endpoint/model, retrieval time, variables and timestamp observation/aggregation semantics produced this export? Are Celsius and km/h header units accurate? Are temperatures point observations or hourly averages?
9. Is the single point near 34.411247 N, 50.490566 E, elevation 1435m suitable for all customers? No customer locations were supplied.
10. Which customers should be eligible for the 2025-01-20 to 2025-03-20 target? Should partial coverage be excluded, reported separately or supported with additional bills? Coverage is not consumption-quality eligibility.
11. Confirm heating-degree base temperature, daily aggregation convention, and policy for missing weather. No consumption-unit, type-label or Capacity assumptions have been made.

Current provisional decisions: inclusive endpoints; timezone UTC from GMT metadata then Asia/Tehran; coverage from valid interval unions; no raw records altered. Alternative end-exclusive coverage is reported for sensitivity. Solver implementation is intentionally deferred.
