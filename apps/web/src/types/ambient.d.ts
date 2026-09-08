/// <reference types="vite/client" />

/**
 * The generated JSON Schema bundle is imported for runtime Ajv validation.
 *
 * It is deliberately declared as an opaque shape rather than resolved with
 * `resolveJsonModule`: the bundle is ~500 kB and letting TypeScript infer the
 * full literal type makes every typecheck run pathologically slow without
 * buying any safety we do not already get from `contracts.ts`.
 */
declare module '@contracts/schemas.json' {
  const bundle: {
    $schema: string;
    title: string;
    schema_version: string;
    models: string[];
    definitions: Record<string, Record<string, unknown>>;
  };
  export default bundle;
}

declare module '*.module.css' {
  const classes: Readonly<Record<string, string>>;
  export default classes;
}

declare module '*.css' {
  const content: string;
  export default content;
}
