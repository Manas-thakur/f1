/**
 * Standing notices. These are product statements, not decoration, and they are
 * shown wherever the values on screen could otherwise be mistaken for measured
 * race data.
 */
export const SYNTHETIC_DATA_NOTICE =
  'Synthetic data: every scenario, trace and result shown in this product is simulated. Nothing here is measured race telemetry.';

export const SPECIMEN_NOTICE =
  'Illustrative specimen. The values below are an authored fixture, not a simulator or model output.';

export const EVIDENCE_BOUNDARY = [
  'A recommendation is a proposal for a human race engineer. Selecting one records a decision; it never actuates a car.',
  'Rule checks cover only the conditions listed in the loaded ruleset manifest. An unlisted condition is reported as unknown, not as passing.',
  'Probabilities are reported with their calibration status. An uncalibrated probability is labelled uncalibrated and carries no coverage claim.',
  'Benchmarks compare controllers on synthetic scenarios with recorded seeds. They establish nothing about on-track performance.',
  'A healthy data feed establishes that data arrived, not that the data is correct or that the decision is legal.',
] as const;
