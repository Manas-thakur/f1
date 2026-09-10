export const testNav = {
  pathname: '/',
  params: {} as Record<string, string>,
};

export function setTestPath(path: string): void {
  testNav.pathname = path;
  const session = /^\/sessions\/([^/]+)/.exec(path);
  const experiment = /^\/experiments\/([^/]+)/.exec(path);
  const ruleset = /^\/rulesets\/([^/]+)/.exec(path);
  const params: Record<string, string> = {};
  if (session?.[1] !== undefined) {
    params.sessionId = session[1];
  }
  if (experiment?.[1] !== undefined) {
    params.experimentId = experiment[1];
  }
  if (ruleset?.[1] !== undefined) {
    params.rulesetId = ruleset[1];
  }
  testNav.params = params;
}

export function paramsFromRoute(route: string, path: string): Record<string, string> {
  const routeParts = route.split('/');
  const pathParts = path.split('/');
  const params: Record<string, string> = {};
  for (let i = 0; i < routeParts.length; i += 1) {
    const segment = routeParts[i] ?? '';
    if (segment.startsWith(':')) {
      params[segment.slice(1)] = decodeURIComponent(pathParts[i] ?? '');
    }
  }
  return params;
}
