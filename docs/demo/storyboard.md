# Demonstration video — storyboard, narration and recording guide

Target: 90 seconds (60–120 s acceptable), 1920 × 1080, for GitHub, LinkedIn and a portfolio.
**Status: not recorded.** The development environment for this release had no screen-recording
capability, so no video was produced and none should be presented as existing. Record it on
Windows with the packaged build using the steps below.

Rules for the recording:

* Use the real application. Simulated data must stay visibly labelled ("Simulated telemetry").
* Do not show or imply a physical OBD-II connection unless one was actually made and tested.
  The Vehicle Connection page may be shown in its "no adapter" state or with the **mock
  adapter**, which is labelled as such.
* Use a fictional vehicle ("Demo hatchback (fictional)"); no real VIN or registration number.
* Do not claim real-world accuracy; say "trained on simulated data".

## Preparation

1. Install the release build (or run `smartdrive gui` from source) with a demo data folder:
   `SmartDrive-Guardian-AI.exe --home "%USERPROFILE%\SmartDrive demo"`.
2. Add the fictional vehicle in Garage. In Simulation Lab, run the **Normal** scenario once with
   recording on (≈ 2 min) so Trip History has a trip; add two maintenance records and a
   schedule.
3. Dark theme, window 1600 × 900, Windows notifications off (Focus Assist), clean desktop.
4. Record with Xbox Game Bar (Win + Alt + R), OBS Studio or Clipchamp; 30 fps; system audio off.
   Record the narration separately and edit in Clipchamp or DaVinci Resolve.

## Scenes

| # | Time | Screen | On-screen text | Narration |
|---|---|---|---|---|
| 1 | 0:00–0:06 | `docs/branding/social-preview.png` full screen | SmartDrive Guardian AI 2.0.0 · Intelligent Diagnostics. Smarter Maintenance. | "SmartDrive Guardian AI is an offline desktop assistant for vehicle diagnostics and maintenance." |
| 2 | 0:06–0:18 | Dashboard with simulation running: gauges, charts, banner | Simulated telemetry | "It monitors engine data in real time. Here it is running the built-in simulator, so no car or hardware is needed." |
| 3 | 0:18–0:30 | Simulation Lab → choose **Engine overheating** → Start | Documented simulation scenario | "The simulation lab reproduces documented fault scenarios, like an engine slowly overheating." |
| 4 | 0:30–0:48 | AI Diagnostics: critical coolant finding, health score, explanation chart | Rules + machine learning · trained on simulated data | "A hybrid engine combines transparent rules with machine-learning models. It explains which signals drove each prediction, and shows an experimental health score. The models were trained on simulated data, so this is a learning tool, not a certified diagnosis." |
| 5 | 0:48–1:00 | Trip History → select trip → Replay at 4×, seek | Trip replay | "Every trip can be recorded and replayed, with its diagnostic timeline." |
| 6 | 1:00–1:10 | Maintenance: schedules with an overdue reminder, cost chart | Your intervals, your currency | "Maintenance records, reminders and costs live in the same place." |
| 7 | 1:10–1:20 | Reports → Vehicle overview PDF → open the PDF | Professional PDF and CSV reports | "And it produces PDF and CSV reports, leaving out personal identifiers by default." |
| 8 | 1:20–1:30 | Start Menu entry, About page, GitHub repository page | v2.0.0 · open source (MIT) · github.com/Hiranya-Bandara/SmartDrive-Guardian-AI | "It installs without administrator rights, works fully offline, and its OBD-II support is strictly read-only. The source is on GitHub." |

Optional insert (only if true at recording time): Vehicle Connection with the mock adapter,
captioned "Mock adapter — simulated data, not a vehicle".

## Narration script (≈ 220 words)

SmartDrive Guardian AI is an offline desktop assistant for vehicle diagnostics and maintenance.

It monitors engine data in real time. Here it is running the built-in simulator, so no car or
hardware is needed. The simulation lab reproduces documented fault scenarios, like an engine
slowly overheating.

A hybrid engine combines transparent rules with machine-learning models. It explains which
signals drove each prediction and shows an experimental health score. The models were trained
on simulated data, so this is a learning tool, not a certified diagnosis.

Every trip can be recorded and replayed with its diagnostic timeline. Maintenance records,
reminders and costs live in the same place. And it produces PDF and CSV reports, leaving out
personal identifiers by default.

It installs without administrator rights, works fully offline, and its OBD-II support is
strictly read-only. The source is on GitHub.

## Export

H.264 MP4, 1080p, ≤ 50 MB for GitHub (attach to the release or link from the README),
captions burned in or as an SRT file. Add the file name and duration to the release notes only
after it exists.
