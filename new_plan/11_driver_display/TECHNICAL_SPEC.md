# Driver display — simulator only

## Boundary

Implement `apps/web/src/features/driver/` at `/sessions/:id/driver` for simulation sessions. The real-F1 product path is engineer voice communication. This connected display is not a claim of approved onboard F1 integration. Server-side mode enforcement is mandatory even if someone manually opens the URL.

## Layout

One primary instruction, trigger/end checkpoint, energy-target status and mode/eligibility. Keep gear/speed and safety state in stable regions. No probability, chat, scrolling telemetry chart or paragraph. Text and shape carry meaning alongside colour. Use large tabular numerals and a small number of high-contrast states. See [mockup](../12_design/mockups/driver.html).

## Input and execution

Display the engineer-selected/communicated instruction, not every planner proposal. In the simulator a deliberate driver input selects a profile; this creates an ExecutionEvent. Acknowledge is not the same as executing a mode. The display listens for backend invalidation/expiry and clears advice. A local watchdog independently clears the instruction if the stream stops; clock mapping uses the session clock and known last-observation age.

The mockup demonstrates a same-browser display via local storage with a visible fixture label; production uses authenticated session streams and explicit driver action endpoints. Never carry local-storage authority into production. Simulator controls can stand beside the display for testing but must not become tiny driving-time touch targets.

## States and precedence

Safety/withdrawal > stale/unavailable > active instruction > completed/neutral. An invalidation interrupts an instruction immediately. Pending engineer selection does not appear as approved driver advice. Disconnection retains essential static vehicle context only if clearly aged; it cannot retain an imperative action indefinitely.

## Validation

Browser tests for large/small viewports, keyboard-only simulator input, contrast and long translated checkpoint names. Lifecycle tests: proposal invisible, selection visible only under the defined workflow, actual execution reported separately, expiry cleared, network lost cleared, rule update cleared, wrong session ignored and live-team endpoint rejected. Human testing should measure recognition time and missed/incorrect mode selection; no usability performance claim before that study.
