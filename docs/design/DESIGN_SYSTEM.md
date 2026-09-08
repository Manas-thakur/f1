# AFTERLAP design system

Working name, no affiliation implied. Selected direction: instrumentation workspace, revision 2. Read [DESIGN_REVISION_02.md](DESIGN_REVISION_02.md) for the current visual decisions. The operating product is an engineering application, not a literal desktop OS. It has a shared shell, modules and session context. Prototype source is `mockups/`; production implementation follows the React architecture.

## Structure

App: left module rail, top session strip, page title/action row, decision or experiment work area, contextual inspector, quiet footer status. Engineer uses action -> chart -> event hierarchy. Lab uses configuration -> branch comparison. Evidence uses table -> detail. Driver is a dedicated high-contrast screen. Marketing uses a concise product description and a wide instrument specimen; the lab landing explains the experiment workflow.

## Tokens

All colours/fonts are named CSS tokens in `mockups/tokens.css`. Light neutral engineering surfaces, dark trace plots, blue selection, purple reference series, green verified success and red failure. Neutral badges indicate fixture/proposed state. Series colour never changes its meaning across charts. Safety colour is not used for decoration. Light marketing page uses the same identity with paper/ink inverted through tokens.

Use a local-first font stack: Segoe UI/Arial for display and body, Consolas/Courier New for numeric/technical labels. There are no network font dependencies in the mockups. Production may bundle licensed fonts after review; never make a third-party font request essential to the operational screen.

Spacing uses 4/8/12/16/24/32/48/64px. App body 14px with 12px secondary labels and compact 24-29px directives. Landing display scales with clamp; keep readable at 320px. Tabular numerals for changing values. Links/buttons are focus-visible; semantic labels accompany colour. No celebratory toasts, auto-rotating carousels, chart decoration or simulated browser chrome.

## States

Interactive components: default, hover, focus, active, disabled, pending, error and success. Data components additionally distinguish empty, missing, estimated, stale and invalid. A pending command disables duplicate submission. Error text explains the failed action and recovery. Success appears in the changed object itself. Reduced motion disables nonessential transitions.

## Responsive policy

Desktop 1440+: full rail, two-column operational workspace, charts on common axis. 1024: narrower rail and stacked inspector. 768: horizontal module navigation and stacked work areas. 414/375/320: one column, readable action first, explicit scroll container for genuinely tabular content. Operational mobile is a summary; no claim of optimal race-operation ergonomics on a phone. Driver display fits a dedicated small panel and has separate simulator controls outside its visual field.

## Prototype honesty

All scenario values and traces are illustrative fixtures, not measured or model-generated outputs. Run/compare controls demonstrate UI state transitions only. Evidence results remain unmeasured. No invented win-rate claims. The driver display's local-storage demonstration is not a production communication mechanism. The known limitations and exercised interactions are recorded in `QA_REPORT.md`.
