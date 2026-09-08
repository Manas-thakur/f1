/**
 * The laboratory's circuit and conditions selection.
 *
 * A small view-local store, not a second source of truth: it holds only what
 * the operator has picked in the circuit panel so the scenario panel can put
 * the same two ids on `POST /sessions` (`CreateSessionRequest.track_id` and
 * `.conditions_id`, both already in the generated contract). Nothing derived
 * from a circuit package is cached here — readiness, hashes and coordinates
 * are always read from the control plane at the point of display, so a
 * recompiled package can never be shown from a stale copy.
 *
 * It is deliberately separate from `state/sessionStore`, which holds server
 * session state; a draft selection is neither server state nor session truth.
 */
import { create } from 'zustand';

export interface CircuitSelectionState {
  /** Selected circuit id, or null while none is chosen. */
  readonly trackId: string | null;
  readonly conditionsId: string | null;
  selectTrack: (trackId: string) => void;
  selectConditions: (conditionsId: string) => void;
  clear: () => void;
}

export const useCircuitSelection = create<CircuitSelectionState>((set) => ({
  trackId: null,
  conditionsId: null,
  // Changing circuit drops the tape: a tape is bound to one session at one
  // venue, so carrying it across circuits would silently mis-bind altitude
  // and wind heading.
  selectTrack: (trackId) => set({ trackId, conditionsId: null }),
  selectConditions: (conditionsId) => set({ conditionsId }),
  clear: () => set({ trackId: null, conditionsId: null }),
}));
