import { Link, useParams } from 'react-router';

import { EmptyState } from '../components/EmptyState';
import { Notice } from '../components/Panel';
import styles from '../app/shell.module.css';

export interface FeaturePlaceholderProps {
  readonly title: string;
  /** The agent that owns this route's feature directory. */
  readonly owner: string;
  readonly ownerScope: string;
  /** The artefact the route will render once the owner lands it. */
  readonly artefact: string;
  readonly description: string;
  /** Where the feature code will live, so the owner has an exact target. */
  readonly featurePath: string;
}

/**
 * A route slot owned by another agent.
 *
 * This exists so the router is complete and A09/A10/A11 only have to add their
 * feature directory and swap one element. It renders a real empty state that
 * names the missing artefact — never a fake chart, a skeleton pretending to
 * load, or a placeholder metric.
 */
export function FeaturePlaceholder({
  title,
  owner,
  ownerScope,
  artefact,
  description,
  featurePath,
}: FeaturePlaceholderProps) {
  const { sessionId, experimentId, rulesetId } = useParams();
  const subject = sessionId ?? experimentId ?? rulesetId ?? null;

  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>

      <div className={styles.workAreaSingle}>
        <Notice tone="attention">
          Route slot only. This view is owned by <strong>{owner}</strong> ({ownerScope}) and has
          not been implemented yet. The shell, router, shared state and primitives it will use
          are in place.
        </Notice>

        <EmptyState
          artefact={artefact}
          heading={`${title} is not implemented in this build`}
          reason={
            subject === null
              ? `${owner} implements this view in ${featurePath}.`
              : `${owner} implements this view in ${featurePath}. The route resolved subject "${subject}".`
          }
          action={
            <p>
              Until then, <Link to="/sessions">the session list</Link> shows what the control
              plane has, and <Link to="/settings">settings</Link> exercises the shared primitives
              this view will be built from.
            </p>
          }
        />
      </div>
    </>
  );
}
