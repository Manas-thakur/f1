'use client';

import { useRace } from './Connection';
import styles from './race.module.css';

function percent(value: number) {
  return `${(value * 100).toFixed(0)}%`;
}

function chartPoints(values: number[], width: number, height: number) {
  if (!values.length) {
    return [];
  }
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = Math.max(1e-9, high - low);
  return values.map((value, index) => ({
    x: values.length === 1 ? width / 2 : index / (values.length - 1) * width,
    y: height - (value - low) / span * (height - 10) - 5,
  }));
}

function chartPath(points: { x: number; y: number }[]) {
  return points.map((point, index) => {
    return `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
  }).join(' ');
}

export function DecisionTelemetry() {
  const { frame, selected, send, connected } = useRace();
  const recommendation = frame?.recommendations[selected];
  const metrics = frame?.training_metrics;
  const history = metrics?.history ?? [];
  const rewardPoints = chartPoints(history.map((cycle) => cycle.mean_reward), 300, 75);
  const recallPoints = chartPoints(history.map((cycle) => cycle.overtake_opportunity_recall), 300, 75);
  const rewardPath = chartPath(rewardPoints);
  const recallPath = chartPath(recallPoints);
  return <section className={`${styles.panel} ${styles.decisionPanel}`}>
    <h2>Energy decision engine</h2>
    <div className={styles.recommendationHeader}>
      <span>RECOMMENDED</span>
      <strong>{recommendation?.mode.toUpperCase() ?? 'UNAVAILABLE'}</strong>
      <em data-available={recommendation?.boost_available ?? false}>
        {recommendation?.boost_available ? 'BOOST READY' : 'BOOST HELD'}
      </em>
    </div>
    <p>{recommendation?.reason ?? 'Waiting for delayed telemetry.'}</p>
    <dl className={styles.telemetryGrid}>
      <dt>Policy source</dt><dd>{recommendation?.source === 'ppo' ? 'PPO policy' : 'Rules baseline'}</dd>
      <dt>Policy confidence</dt><dd>{recommendation?.confidence === null
        || recommendation?.confidence === undefined ? 'Unavailable' : percent(recommendation.confidence)}</dd>
      <dt>Overtake target</dt><dd>{recommendation?.target_car_id ?? 'None'}</dd>
      <dt>Gap ahead</dt><dd>{recommendation?.gap_ahead_s === null
        || recommendation?.gap_ahead_s === undefined ? 'Unavailable' : `${recommendation.gap_ahead_s.toFixed(2)} s`}</dd>
      <dt>Reward score</dt><dd>{recommendation ? percent(recommendation.reward_score) : 'Unavailable'}</dd>
      <dt>Risk score</dt><dd>{recommendation ? percent(recommendation.risk_score) : 'Unavailable'}</dd>
      <dt>Reward / risk</dt><dd>{recommendation?.risk_reward_ratio === null
        || recommendation?.risk_reward_ratio === undefined ? 'Unavailable' : recommendation.risk_reward_ratio.toFixed(2)}</dd>
      <dt>Overtake authorization</dt><dd>{recommendation?.overtake_available ? 'Activated' : 'Unavailable'}</dd>
    </dl>
    <div className={styles.decisionBars}>
      <label>Reward<progress max={1} value={recommendation?.reward_score ?? 0} /></label>
      <label>Risk<progress max={1} value={recommendation?.risk_score ?? 0} /></label>
    </div>
    <div className={styles.actions}>
      <button type="button" className={styles.primary}
        disabled={!connected || !recommendation?.can_apply}
        onClick={() => send('boost', { car_id: selected })}>
        Apply boost
      </button>
      <button type="button" disabled={!connected}
        onClick={() => send('boost', { car_id: selected, enabled: false })}>
        Return to automatic
      </button>
    </div>
    <p className={styles.caption}>{recommendation?.regulation_basis}</p>
    <details className={styles.trainingMetrics} open={Boolean(metrics)}>
      <summary>Training cycles and evaluation</summary>
      {!metrics ? <p>No metrics artifact loaded. Start the stack with a policy and its metrics file.</p> : <>
        <div className={styles.trainingSummary}>
          <span><b>{metrics.total_timesteps}</b> steps</span>
          <span><b>{metrics.cycles}</b> cycles</span>
          <span><b>{metrics.optimizer_epochs_per_cycle}</b> epochs / cycle</span>
          <span><b>{metrics.best_cycle}</b> best cycle</span>
        </div>
        <svg viewBox="0 0 300 90" role="img" aria-label="Evaluation reward and overtake opportunity recall by training cycle">
          <path d={rewardPath} className={styles.rewardLine} />
          <path d={recallPath} className={styles.recallLine} />
          {rewardPoints.map((point, index) => <circle key={`reward-${index}`}
            cx={point.x} cy={point.y} r="2.5" className={styles.rewardPoint} />)}
          {recallPoints.map((point, index) => <circle key={`recall-${index}`}
            cx={point.x} cy={point.y} r="2.5" className={styles.recallPoint} />)}
          <text x="5" y="12">reward</text><text x="245" y="12">recall</text>
        </svg>
        <dl className={styles.telemetryGrid}>
          <dt>Latest eval reward</dt><dd>{history.at(-1)?.mean_reward.toFixed(2) ?? 'Unavailable'}</dd>
          <dt>Baseline reward</dt><dd>{metrics.baseline.mean_reward.toFixed(2)}</dd>
          <dt>Opportunity recall</dt><dd>{percent(history.at(-1)?.overtake_opportunity_recall ?? 0)}</dd>
          <dt>Failure rate</dt><dd>{percent(history.at(-1)?.failure_rate ?? 0)}</dd>
          <dt>Mean deployed energy</dt><dd>{history.at(-1)?.mean_deployed_mj.toFixed(2) ?? 'Unavailable'} MJ</dd>
          <dt>Promotion candidate</dt><dd>{metrics.promotion.candidate ? 'Review' : 'No'}</dd>
        </dl>
        <p>{metrics.promotion.reason}</p>
        <p>{metrics.provenance}</p>
      </>}
    </details>
  </section>;
}
