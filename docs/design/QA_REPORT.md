# Design package verification

Reviewed 8 September 2026. This report concerns the documentation and interactive HTML design references, not an implemented race decision engine.

## Revision 2 verification

These checks supersede the initial visual/viewport notes where stated. The shared theme, engineer hierarchy, battle-context table, landing composition and copy were revised under DESIGN_REVISION_02.

- Visually inspected the revised engineer workspace, product landing and dark driver display.
- Measured engineer CSS widths of 320, 375, 414, 768, 1024 and 1440 px after accounting for browser scaling. No document overflow or right-edge overflow among sampled panels, decision containers, buttons and navigation links. This is a geometric check, not full readability certification at every size.
- At 320 px both landing pages had no document overflow; product links and specimen also stayed within the viewport.
- Selection → communication → simulated execution still works. Injecting stale data withdraws advice. Replay End moves both cursors to x=592 and the caption to 5,200 m.
- All eight workspace routes render. Driver fixture load shows SAVE; withdrawal shows NO ADVICE. Browser error log was empty after checked interactions.
- Six external/inline JavaScript blocks passed Node syntax checks. Package links, JSON and structure passed the validator after documentation additions.

Temporary emulation/viewport changes were cleared. Full screen-reader audit, exported download validation, all child-overflow cases and physical display ergonomics remain future implementation checks. ML/RL documents and configuration were reviewed for consistency; no training or production-stack installation is claimed.

## Checks completed

| Area | Observed result |
|---|---|
| Engineer workflow | Select plan → Mark communicated → Simulate execution reaches EXECUTING, with a disabled terminal action and a visible event history. |
| Decision evidence | Evidence dialog opens, receives focus on its close button, shows provenance and unavailable metrics, and closes with Escape. |
| Stale input | Injecting a stale feed withdraws the recommendation and disables selection. A same-origin driver tab changes to NO ADVICE / WITHDRAWN. |
| Driver lifecycle | Communicated fixture appears in the driver tab. After the 30-second validity window, the display changes to EXPIRED / NO ADVICE. |
| Simulation controls | Energy slider reaches 3.80 MJ with End; opponent selection changes; start changes to pause; comparison reveals the authored reference curve and its disclaimer; reset restores fixture controls. |
| Replay | Moving the shared cursor to the end sets both SVG cursors to x=592 and updates the distance label to 5,200 m. |
| Workspace navigation | All eight routes render their corresponding headings. Browser error log was empty after the route and interaction checks. |
| Concepts | All three concept buttons switch compositions. The light notebook was visually inspected; the battle board exposes its distinct position tower and spatial emphasis. |
| Landing pages | Both pages render their intended content and local navigation. The product page was visually inspected. |
| Layout | Operating workspace, concept notebook and product landing inspected in the available browser viewport, measured at 804 CSS px. Workspace and product landing had no document-level horizontal overflow at that width. |
| Static package | Validator checks local links, HTML duplicate IDs, JSON parsing, telemetry example fields, provenance, module briefs and mockup inventory. Run the command below for the final count. |

## Corrections made during review

- Widened the desktop navigation rail and kept link labels on one line.
- Increased SVG chart/map label sizes and shortened the defence checkpoint caption.
- Removed an unused malformed SVG path.
- Updated the replay distance caption together with both chart cursors.

## Limits of this review

The browser viewport override did not change the measured viewport. Consequently, 320, 375, 414, 768 and 1440 px layouts are **not certified by this review**. Media rules are supplied; the frontend implementation agent must perform the full viewport matrix and keyboard/screen-reader audit in its production browser harness. Document-level overflow alone does not prove that every child element fits.

The export control is implemented, but downloaded-file contents were not verified through the browser. No automated accessibility certification, physical steering-wheel test, simulator calibration, model training, benchmark, rule compliance execution or backend integration was performed. Those are implementation acceptance tasks in the relevant subsystem specifications.

Cross-tab driver synchronization requires the same HTTP origin and available browser local storage. Opening separate `file:` URLs is suitable for visual inspection, but is not a reliable cross-tab integration test. Serve the package locally for the linked workflow.

## Reproduce

From `C:\Work\f1`:

```powershell
python docs/tools/validate_package.py
node --check docs/design/mockups/app.js
node --check docs/design/mockups/shared.js
python -m http.server 8765 --bind 127.0.0.1 --directory docs/design/mockups
```

Open `http://127.0.0.1:8765/`, then the workspace and driver in separate tabs. Follow the observed workflow above. All displayed data remains explicitly illustrative.
