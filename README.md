# APEX — one-shot second container memory-limit observation

This utility is **not an APEX patch**. It performs a read-only GET on the existing `/health` endpoint, or compares an exported health JSON file, against the bundled November 12, 2026 10:31 AM ET baseline.

Run from a machine that can access your APEX endpoint:

```bash
python collect_observation.py --out apex_second_memory_observation.json
```

Or if you have copied the next full `/health` JSON to a file:

```bash
python collect_observation.py --file next_health.json --out apex_second_memory_observation.json
```

The report is **incomparable** if the web worker PID, process start time, cgroup identity verification, counter monotonicity, or observation chronology do not match. This is intentionally conservative; an APEX deployment may reset the baseline. The script makes one GET request, adds no instrumentation, and never touches trading logic or database storage. A second response from the same APEX web worker is needed to interpret per-worker `sample_count` and event intervals; the script does not poll repeatedly.

*Source baseline*: `/health` user-provided snapshot at 2026-11-12T15:31:10Z, worker PID 200, cumulative max/oom/oom_kill all 0. No later production measurement was accessible from this execution environment.
