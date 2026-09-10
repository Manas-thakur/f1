export function routeParam(value: string | string[] | undefined): string | undefined {
  return typeof value === 'string' ? value : undefined;
}
