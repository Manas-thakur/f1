

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
