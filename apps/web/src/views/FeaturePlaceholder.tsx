import Link from 'next/link';
import { useParams } from 'next/navigation';

import { EmptyState } from '../components/EmptyState';
import { Notice } from '../components/Panel';
import { routeParam } from '../shell/params';
import styles from '../shell/shell.module.css';

export interface FeaturePlaceholderProps {
  readonly title: string;
  
  readonly owner: string;
  readonly ownerScope: string;
  
  readonly artefact: string;
  readonly description: string;
  
  readonly featurePath: string;
}


export function FeaturePlaceholder({
  title,
  owner,
  ownerScope,
  artefact,
  description,
  featurePath,
}: FeaturePlaceholderProps) {
  const params = useParams();
  const subject =
    routeParam(params.sessionId) ?? routeParam(params.experimentId) ?? routeParam(params.rulesetId) ?? null;

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
              Until then, <Link href="/sessions">the session list</Link> shows what the control
              plane has, and <Link href="/settings">settings</Link> exercises the shared primitives
              this view will be built from.
            </p>
          }
        />
      </div>
    </>
  );
}
