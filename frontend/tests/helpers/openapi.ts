import Ajv2020, { type ValidateFunction } from "ajv/dist/2020";
import addFormats from "ajv-formats";

import snapshot from "@/contract/openapi.json";

/** A trimmed view of the parts of an OpenAPI 3.1 document the contract tests read. */
interface Operation {
  parameters?: { name: string; in: string; required?: boolean; schema: Record<string, unknown> }[];
  requestBody?: { content: Record<string, { schema: Record<string, unknown> }> };
  responses: Record<string, { content?: Record<string, { schema: Record<string, unknown> }> }>;
}
interface Spec {
  paths: Record<string, Record<string, Operation>>;
  components: { schemas: Record<string, Record<string, unknown>> };
}

export const spec = snapshot as unknown as Spec;

const SPEC_ID = "https://contract.test/openapi.json";

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema({ $id: SPEC_ID, ...spec });

const compiled = new Map<string, ValidateFunction>();

/** Validate `value` against the named component schema; returns human-readable errors (empty = valid). */
export function validateComponent(name: string, value: unknown): string[] {
  let validate = compiled.get(name);
  if (!validate) {
    validate = ajv.compile({ $ref: `${SPEC_ID}#/components/schemas/${name}` });
    compiled.set(name, validate);
  }
  validate(value);
  return (validate.errors ?? []).map((e) => `${e.instancePath || "/"} ${e.message ?? ""}`.trim());
}

/** Validate against an inline schema from the spec (may contain `$ref`s into the document). */
export function validateSchema(schema: Record<string, unknown>, value: unknown): string[] {
  const absolute = JSON.parse(
    JSON.stringify(schema).replaceAll('"#/components', `"${SPEC_ID}#/components`),
  );
  const validate = ajv.compile(absolute);
  validate(value);
  return (validate.errors ?? []).map((e) => `${e.instancePath || "/"} ${e.message ?? ""}`.trim());
}

/** The spec path template for a runtime request path, e.g. `/api/v1/voice/profiles/abc` → `/api/v1/voice/profiles/{profile_id}`. */
export function matchSpecPath(pathname: string): string | null {
  const parts = pathname.split("/");
  return (
    Object.keys(spec.paths).find((template) => {
      const t = template.split("/");
      return (
        t.length === parts.length && t.every((seg, i) => seg.startsWith("{") || seg === parts[i])
      );
    }) ?? null
  );
}

export function operation(method: string, template: string): Operation | undefined {
  return spec.paths[template]?.[method.toLowerCase()];
}

/** The JSON schema a response with `status` is declared to carry, or undefined for bodyless/non-JSON. */
export function responseSchema(op: Operation, status: number): Record<string, unknown> | undefined {
  return op.responses[String(status)]?.content?.["application/json"]?.schema;
}
