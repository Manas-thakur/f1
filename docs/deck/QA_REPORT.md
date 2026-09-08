# PowerPoint QA report

Artifact: `output/AFTERLAP-final-round.pptx`

## Automated validation

- 15 slides at 16:9, 13.3333 × 7.5 inches.
- Package integrity passed with zero findings.
- Layout geometry passed with zero findings and zero warnings.
- Arial was the only observed font family across 302 checked text runs.
- First-party Artifact Tool import passed for all 15 slides.
- Slide 4 contains one editable native PowerPoint bar chart with six numeric points.
- Speaker notes are present on all 15 slides.

Validated build SHA-256: `efe242debe8e09b58026b9b38f4501ad14489748fa4152798ff7851cac19518c`.

## Visual inspection

Every delivered slide was rendered to 1600 × 900 PNG and inspected. Corrections made during QA:

- moved the circuit-length chart away from its explanatory text;
- reduced long-heading size so slides 11 and 15 fit cleanly;
- removed a connector/text intersection warning in the architecture slide;
- changed process arrows to read from source to destination.

The final montage is stored in `.build/montage-v4.png` and the individual renders are in `.build/rendered-v4/`.

## Boundary

The deck was structurally validated and rendered outside native Microsoft PowerPoint. Native PowerPoint playback, host-specific font substitution and presenter hardware were not tested.
