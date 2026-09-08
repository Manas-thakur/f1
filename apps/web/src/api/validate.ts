/**
 * Runtime validation of stream envelopes against the generated JSON Schema
 * bundle.
 *
 * Every message that arrives on the WebSocket is validated here *before* it is
 * allowed anywhere near the reducer. An envelope that fails validation is
 * rejected and counted; it is never partially applied, and it never silently
 * becomes state.
 */
import Ajv2020, { type ErrorObject, type ValidateFunction } from 'ajv/dist/2020';
import schemaBundle from '@contracts/schemas.json';
import type { StreamEnvelope, SCHEMA_VERSION } from '@contracts';

export type SupportedSchemaVersion = typeof SCHEMA_VERSION;

export interface ValidationFailure {
  readonly ok: false;
  readonly reason: 'not_json' | 'not_object' | 'schema_violation' | 'unknown_schema';
  readonly message: string;
  readonly errors: readonly ErrorObject[];
}

export interface ValidationSuccess<T> {
  readonly ok: true;
  readonly value: T;
}

export type ValidationResult<T> = ValidationSuccess<T> | ValidationFailure;

/**
 * `strict: false` is required, not a shortcut: the generated bundle carries
 * OpenAPI-style `discriminator` objects emitted by Pydantic, which are not
 * JSON Schema keywords. Ajv would otherwise refuse to compile the schema it
 * was given. `oneOf` still enforces the payload union exactly.
 */
function createAjv(): Ajv2020 {
  return new Ajv2020({
    strict: false,
    allErrors: true,
    allowUnionTypes: true,
    // The bundle inlines every dependency under each definition's own $defs,
    // so no cross-schema reference resolution is needed.
    validateFormats: false,
  });
}

const ajv = createAjv();
const compiled = new Map<string, ValidateFunction>();

export function schemaNames(): readonly string[] {
  return schemaBundle.models;
}

export function bundleSchemaVersion(): string {
  return schemaBundle.schema_version;
}

/** Compile (and memoise) the validator for one generated contract model. */
export function validatorFor(modelName: string): ValidateFunction {
  const existing = compiled.get(modelName);
  if (existing !== undefined) {
    return existing;
  }
  const schema = schemaBundle.definitions[modelName];
  if (schema === undefined) {
    throw new Error(`no generated schema named ${JSON.stringify(modelName)} in the bundle`);
  }
  const fn = ajv.compile(schema);
  compiled.set(modelName, fn);
  return fn;
}

function describe(errors: readonly ErrorObject[] | null | undefined): string {
  if (!errors || errors.length === 0) {
    return 'schema violation';
  }
  return errors
    .slice(0, 4)
    .map((e) => `${e.instancePath === '' ? '<root>' : e.instancePath} ${e.message ?? 'invalid'}`)
    .join('; ');
}

/** Validate an already-parsed value against a named generated model. */
export function validateAs<T>(modelName: string, value: unknown): ValidationResult<T> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return {
      ok: false,
      reason: 'not_object',
      message: `${modelName} must be a JSON object`,
      errors: [],
    };
  }
  const validate = validatorFor(modelName);
  if (validate(value)) {
    return { ok: true, value: value as T };
  }
  const errors = (validate.errors ?? []) as ErrorObject[];
  return {
    ok: false,
    reason: 'schema_violation',
    message: describe(errors),
    errors,
  };
}

/**
 * Parse and validate one raw WebSocket frame.
 *
 * This is the only supported way to turn wire text into a `StreamEnvelope`.
 */
export function validateEnvelope(raw: unknown): ValidationResult<StreamEnvelope> {
  let parsed: unknown = raw;
  if (typeof raw === 'string') {
    try {
      parsed = JSON.parse(raw);
    } catch (error) {
      return {
        ok: false,
        reason: 'not_json',
        message: error instanceof Error ? error.message : 'frame is not JSON',
        errors: [],
      };
    }
  }
  return validateAs<StreamEnvelope>('StreamEnvelope', parsed);
}

/** Reset memoised validators. Test-only helper. */
export function _resetValidatorCache(): void {
  compiled.clear();
}
