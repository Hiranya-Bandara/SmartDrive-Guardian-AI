# Reports and exports

The **Reports** page (Ctrl+Shift+R) creates PDF reports and CSV exports from the data stored on
this computer. Generation runs on a background thread; the window stays usable. A report is
only reported as saved after the file has been written; failures (folder missing, no
permission, file in use) are shown with the reason and recorded in the export history.
Trip History and Diagnostic Codes also offer direct exports for the selected item.

Sample outputs generated from **simulated data only** are in [samples/](samples/); they are
produced by `python scripts/generate_sample_reports.py` in a throw-away database.

## PDF reports

| Report | Default sections |
|---|---|
| Vehicle diagnostic report | Vehicle, trips, findings, trouble codes, health score, charts, recommendations |
| AI diagnostic assessment report | Vehicle, findings, health score, model information, explainable AI evidence (latest analysis), charts, recommendations |
| Diagnostic trouble code report | Vehicle, trouble codes and scans, findings, recommendations |
| Trip report | Vehicle, trip statistics, sensor summaries, telemetry charts, diagnostic timeline, findings, health score |
| Vehicle maintenance history report | Vehicle, records, schedules and status, costs per currency, charts |
| Comprehensive vehicle overview | All sections |
| Model evaluation report | Model versions, synthetic test metrics per category, F1 chart |

Sections can be switched on and off, and the period limited to a date range. Every report has:
the SmartDrive name and version, a unique report ID, the generation time (UTC), the vehicle,
period, **data source label** (simulated, live vehicle (OBD-II) or replayed, with the number
of trips of each), page numbers,
and a limitations section stating that SmartDrive is not a certified vehicle safety system,
that the models were trained only on simulated data, and that distances are estimates.

Design: A4, standard PDF fonts, repeated table headers, severity shown as text marks
(`[!!] CRITICAL`, `[!] WARNING`) so it remains readable in greyscale, light backgrounds only.
Repeated records of the same finding are grouped into episodes (first and last time, count);
the CSV export lists every record.

Characters outside the standard PDF fonts are replaced with readable equivalents (for example
`≈` becomes `~`).

## CSV exports

| Dataset | Rows |
|---|---|
| Trip telemetry | One per sample of the selected trip; every sensor column with its unit, extra OBD-II values, data source |
| Recorded trips | One per trip with statistics and event counts |
| Diagnostic findings | Every stored finding with source, severity, model version and data source |
| Trouble codes | Every code record with status, first/last detection and scan provenance |
| Health score history | Every analysis with a health score |
| Maintenance records | Records with category, date, odometer, provider, cost and currency (notes excluded) |
| Notifications | Notification history |
| Model evaluation results | Per-category synthetic test metrics |

Format:

- UTF-8 with a byte-order mark (opens correctly in Excel), comma separated, RFC 4180 quoting.
- Column names include units (`speed_kph`, `coolant_temp_c`, …); timestamps are ISO 8601 UTC
  (`2026-11-20T08:30:00Z`).
- **Missing values are empty cells**, never zero. A measured zero stays `0`.
- **Formula-injection protection:** text cells beginning with `=`, `+`, `-`, `@`, tab or
  carriage return are prefixed with `'` so spreadsheet programs show them as text.
- Files are written to a temporary file in the same folder and moved into place. The save
  dialog asks before replacing an existing file; the service itself refuses to overwrite
  unless the replacement was confirmed.

## Privacy

Registration number, VIN and the vehicle's garage notes are excluded unless "Include …" is
ticked for the report (defaults in **Settings → Trips, maintenance and reports**). PDF
metadata contains no user, computer or path information. See [PRIVACY.md](../PRIVACY.md).

## Limitations

- Charts are drawn from at most 600 points per series (longer trips are down-sampled for the
  chart only; statistics use every sample).
- Report content reflects what was recorded. A report with no findings does not mean the
  vehicle has no faults.
