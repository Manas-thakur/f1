import { Link, useLocation } from 'react-router';

import { EmptyState } from '../components/EmptyState';
import styles from '../app/shell.module.css';

export function NotFoundPage() {
  const location = useLocation();
  return (
    <>
      <div className={styles.pageHead}>
        <div>
          <h1>No such route</h1>
        </div>
      </div>
      <div className={styles.workAreaSingle}>
        <EmptyState
          artefact="route"
          heading="This address does not match a route in this build"
          reason={`Requested ${location.pathname}.`}
          action={<Link to="/sessions">Go to the session list</Link>}
        />
      </div>
    </>
  );
}
