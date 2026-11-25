# Performance evaluation — version 2.0.0

All figures below were **measured** with `scripts/benchmark.py` on the date shown, on the
environment shown. Raw results: [performance/results-linux-sandbox.json](performance/results-linux-sandbox.json).
They describe the source build on a Linux development container with Qt's `offscreen` platform —
**not** the packaged application on Windows, which has not been measured yet. Rerun the script
on Windows to obtain those numbers:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark.py --sustained-minutes 20 --output docs\performance\results-windows.json
```

## Environment

| Item | Value |
|---|---|
| Measured | 25 November 2026, 17:40 UTC |
| Operating system | Linux 6.18 (container), glibc 2.39 |
| CPU | Intel Xeon @ 2.10 GHz, 2 logical CPUs (virtualised) |
| RAM | 7.8 GiB |
| Python / Qt platform | CPython 3.12.3 / `offscreen` (no GPU, no real display) |
| Application / models | 2.0.0 (source, not frozen) / fault_classifier 1.1.0, anomaly_detector 1.1.0, scikit-learn 1.9.1 |
| Data | Simulated only. Database benchmarks: 20 trips × 2,000 samples (40,000 telemetry rows). |

Light documentation editing and a dependency audit ran on the same machine during the sustained
run; figures may include that noise.

## Start-up and shutdown

Each launch is a separate Python process: imports, bootstrap (settings, logging, database
migration check), construction of the main window with all 13 pages, and the first paint.

| Measurement | First launch (new data folder) | Repeat launches (median of 5, p95) |
|---|---|---|
| Imports | 2.30 s | 2.26 s (2.51 s) |
| Bootstrap (settings, logging, migrations) | 0.17 s | 0.04 s (0.04 s) |
| Main window built and shown | 1.18 s | 1.11 s (1.23 s) |
| **Process start to visible window** | **3.64 s** | **3.39 s (3.64 s)** |
| Memory (RSS) after start-up | 441 MB | 435 MB |
| Shutdown (idle) | 0.22 s | 0.17 s (0.23 s) |
| Whole process, start to exit | 4.45 s | 4.03 s (4.31 s) |

"First launch" creates and migrates the database but does not clear operating-system file
caches, so it is not a cold-boot figure. Models are loaded in the background after the window
appears (134 ms measured separately).

## Sustained monitoring (20 minutes)

Simulated "multiple faults" scenario at real time (1 frame per second), trip recording on,
diagnostic inference every 2 s, all pages built, one window 1366 × 768.

| Measurement | Result |
|---|---|
| Duration / frames received | 1,200 s / 1,204 |
| Memory after start-up → during monitoring, inference and recording | 387 MB → median 394 MB, max 394.3 MB |
| Memory change from minute 1 to minute 19 | +0.9 MB (393.4 → 394.3 MB; ≈ 3 MB per hour if it continued linearly) |
| CPU | 12.4 % of one core (average) |
| GUI event-loop lateness (50 ms probe timer) | median 1.3 ms, p95 4.1 ms, max 153 ms (n = 23,953) |
| Native threads (sampled every minute) | 7 throughout (9 at start-up, before the model loader finished) |
| Python threads | 3 throughout |
| Qt timers owned by the window and controllers | 9 throughout |
| Notifications stored | 11 (de-duplicated alerts from the developing faults) |
| Stop monitoring (flush recording) | 0.07 s |
| Shutdown with a replay and a background job running | 0.36 s |

**Leak checks.** Threads and timers did not accumulate. Memory grew by under 1 MB, while the
chart buffer grew by 1,140 points (one per frame) and 11 notifications were stored; the run is
too short to rule out a very slow leak. The display buffer is capped at 3,000 points for the
default 300-second chart history (`buffer_capacity`, upper limit 36,000); at 1 frame per second
that cap is reached after 50 minutes, so this run did **not** reach it. The cap itself is covered
by unit tests. The notification list is read from the database on demand; nothing accumulates in
memory.

## Components

| Measurement | Median | p95 | n |
|---|---|---|---|
| Load and verify both models (SHA-256, schema) | 134 ms | — | 1 |
| Build a 60-second telemetry window | 0.11 ms | 0.14 ms | 200 |
| **Full AI assessment of one window** (rules, Random Forest, Isolation Forest, explanations, health score) | **48 ms** | **77 ms** (max 124 ms) | 170 |
| Database write (batched inserts) | 66,000 samples/s | 85,500 samples/s | 20 batches of 2,000 |
| Trip list query (20 trips) | 3.6 ms | 3.8 ms | 30 |
| Trip detail query | 0.9 ms | 1.2 ms | 30 |
| Load one trip's 2,000 samples | 30 ms | 120 ms | 10 |
| Prepare a replay of 2,000 samples | 0.28 ms | 0.33 ms | 20 |
| Seek within a replay | < 0.01 ms | < 0.01 ms | 200 |
| PDF: trip report | 70 ms | 103 ms | 5 |
| PDF: vehicle overview | 52 ms | 62 ms | 5 |
| PDF: model evaluation | 19 ms | 19 ms | 5 |
| CSV: 2,000 telemetry rows | 61 ms | 140 ms | 5 |

Inference runs on its own thread every 2 s by default, so a 48–77 ms assessment uses a few
percent of one core and never blocks the interface. Reports, trip summaries and replay loading
run on the background job thread.

## Distribution size

| Build | Files | Size |
|---|---|---|
| PyInstaller one-folder, **Linux** (final spec validation build) | 955 (43 of them symlinks) | 481 MiB counted by file size; 347 MiB on disk (`du`, symlinked Qt libraries counted once) |
| PyInstaller one-folder, Windows | not built yet | — |
| Installer, portable ZIP | not built yet | — |

The figure in the JSON results (485 MiB, 989 files) is from an earlier build that still contained
build-tool packages; they are now excluded. The Windows sizes will differ (different Qt and BLAS
libraries); `build-windows.ps1` prints them.

## Optimisations already in place

Models load in the background after the first paint; telemetry is persisted in batches on a
worker thread; chart buffers are bounded; inference requests are latest-only (stale results
are discarded); refresh rate and inference interval are configurable; reports are generated on
the job thread. No change in this release traded diagnostic correctness for speed.

## Not measured

Windows packaged start-up (including antivirus scanning of a new executable), memory on Windows,
GPU-accelerated rendering, real OBD-II polling rates, and runs longer than 20 minutes.
