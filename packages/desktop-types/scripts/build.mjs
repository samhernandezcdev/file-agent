// FA-017 type-generation step 2 of 2: reads the combined JSON Schema
// produced by scripts/generate_desktop_view_schema.py (Pydantic
// model_json_schema()) and compiles every top-level $defs entry into one
// checked-in TypeScript file. Compile-time only -- see
// generated/index.ts's own header comment for the exact contract.

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "json-schema-to-typescript";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = join(here, "..", "schema", "desktop-api.schema.json");
const outputPath = join(here, "..", "generated", "index.ts");

async function main() {
  const raw = readFileSync(schemaPath, "utf-8");
  const schema = JSON.parse(raw);
  const defs = schema.$defs ?? {};
  const modelNames = Object.keys(defs).sort();

  const header = `/**
 * GENERATED FILE -- DO NOT EDIT BY HAND.
 *
 * Produced from src/file_agent/desktop_api's Pydantic View DTOs and
 * request-param models via:
 *   uv run python scripts/generate_desktop_view_schema.py
 *   pnpm --filter @file-agent/desktop-types generate
 *
 * These types are a COMPILE-TIME contract only. Nothing in this file
 * performs runtime validation of data arriving from the sidecar -- see
 * the FA-017 design plan's "TYPE GENERATION" section for why v1
 * deliberately does not add a runtime validator (Zod/Ajv) on top of this.
 */

`;

  // Compiled ONCE, as a single synthetic root schema referencing every
  // named $defs entry -- json-schema-to-typescript deduplicates shared
  // definitions within one compile() call, generating each named
  // interface exactly once, in dependency order. Compiling per-model
  // instead (one compile() call per top-level type) would re-emit every
  // transitively-shared definition (e.g. UserMessageView) once per
  // caller, producing duplicate TypeScript declarations.
  const rootSchema = {
    title: "DesktopApiTypesRoot",
    type: "object",
    $defs: defs,
    properties: Object.fromEntries(
      modelNames.map((name) => [name, { $ref: `#/$defs/${name}` }]),
    ),
    required: modelNames,
    additionalProperties: false,
  };

  const ts = await compile(rootSchema, "DesktopApiTypesRoot", {
    bannerComment: "",
    additionalProperties: false,
    style: { semi: true, singleQuote: false },
  });

  const output = header + ts;

  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, output, "utf-8");
  console.log(`wrote ${outputPath} (${modelNames.length} types)`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
