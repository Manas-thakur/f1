import { create } from 'zustand';

export interface CircuitSelectionState {
  readonly trackId: string | null;
  readonly conditionsId: string | null;
  selectTrack: (trackId: string) => void;
  selectConditions: (conditionsId: string) => void;
  clear: () => void;
}

export const useCircuitSelection = create<CircuitSelectionState>((set) => ({
  trackId: null,
  conditionsId: null,
  selectTrack: (trackId) => set({ trackId, conditionsId: null }),
  selectConditions: (conditionsId) => set({ conditionsId }),
  clear: () => set({ trackId: null, conditionsId: null }),
}));
