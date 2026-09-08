# AFTERLAP final-round presentation

Open [AFTERLAP-final-round.pptx](output/AFTERLAP-final-round.pptx) for the editable PowerPoint. The deck covers the 2026 rules context, real circuits, condition modelling, hybrid RL/MPC architecture, validation, product surfaces and USP.

Contents:

- `build-deck.mjs`: reproducible deck source using the bundled artifact runtime.
- `assets/energy-circuit-cover.png`: generated abstract cover artwork. It does not depict a real circuit.
- [speaker notes](SPEAKER_NOTES.md): presentation script aligned to slide numbers.
- [demo and judge Q&A](DEMO_AND_QA.md): live sequence, fallback sequence and concise answers to predictable technical questions.
- [QA report](QA_REPORT.md): structural, layout and rendered-slide checks for the delivered deck.
- [sources](SOURCES.md): web and project references.
- `output/`: deliverable deck only.
- `.build/`: private draft, rendered previews and validation records.

The deck intentionally leaves performance gains unmeasured. Replace the evaluation placeholders only after the benchmark pipeline produces a hash-linked report. Update the 2026 schedule and FIA event documents before presenting at a later date.

## Rebuild

Use the bundled presentation runtime described in the local presentation skill. The source expects `SKILL_DIR`, `TMP_DIR`, `RUNTIME_PYTHON` and `RUNTIME_NODE_MODULES`; link `.build/node_modules` to the bundled modules before running. Do not substitute python-pptx.

The generated cover prompt requested a restrained abstract circuit/energy/weather composition with no real track, logos, cars or text. It was produced with the built-in image-generation tool and copied into this folder.
