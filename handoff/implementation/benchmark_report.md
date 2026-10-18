# Local benchmark report

Source ingestion/audit was performed once and reused for subset runs. Benchmark wall time below includes selection, weather, model, reconciliation and streamed exports; source import/audit timing and full process RSS are recorded separately. Preloaded runs retain the source table, so their peak RSS includes that table. RSS sampling interval is 20 ms. JIT initialization is visible in the smoke measurements; warm times are labeled. Reference cProfile timings include instrumentation overhead. No full production run was performed.

 customers   bills  model_customers  model_bills  allocated_interval_days  model_interval_days  wall_seconds  peak_rss_bytes  import_audit_seconds  population_seconds  weather_seconds  model_seconds  export_seconds sample_scope  source_import_reused
     100.0   130.0             27.0         52.0                   6490.0               2623.0      1.639877     608473088.0          5.999973e-07            1.391534         0.019582       0.024479        0.139536     universe                  True
     500.0   708.0            195.0        382.0                  35472.0              19292.0      2.254596     623280128.0          5.999973e-07            1.417326         0.013633       0.039647        0.726596     universe                  True
    2000.0  2841.0            785.0       1531.0                 142087.0              77400.0      4.420270     642166784.0          3.000023e-07            1.439655         0.013434       0.138222        2.763381     universe                  True
   10000.0 14148.0           3964.0       7651.0                 710687.0             390811.0     17.186382     810086400.0          1.999979e-07            1.479350         0.014951       1.529841       14.040978     universe                  True
   10000.0 19320.0          10000.0      19320.0                 986415.0             986415.0     18.964672     824832000.0          6.000009e-07            1.092994         0.014694       3.232204       14.452689       cohort                  True

The initial profiles are preserved. Optimizations keep canonical sequential updates and one global aggregate; batching only affects storage. Review the profile and equivalence JSON for measured evidence. All actual solver runs use complete selected bill intervals. Timing does not imply validated daily accuracy.

The separately measured cold IDE entry point and its stage timings are in benchmark_with_cold_ide.csv. Full balanced-cohort structural bill count, H_cohort, volumes and support are in full_cohort_structural_diagnostics.json and full_cohort_support.csv; this scan did not model or allocate the full population. See optimization_record.md for measured changes and the rejected numerical comparison.
