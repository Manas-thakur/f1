import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { EmptyState } from '../components/EmptyState';
import styles from '../shell/shell.module.css';

export function NotFoundPage() {
  const pathname = usePathname();
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
          reason={`Requested ${pathname}.`}
          action={<Link href="/sessions">Go to the session list</Link>}
        />
      </div>
    </>
  );
}
