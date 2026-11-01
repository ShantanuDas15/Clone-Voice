import { defineConfig, globalIgnores } from "eslint/config";
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

export default defineConfig([
  ...nextCoreWebVitals,
  ...nextTypescript,
  {
    rules: {
      "react/no-danger": "error",
      "no-console": "error",
      // New in eslint-plugin-react-hooks 7 (Next 16's config): React Compiler readiness lints that
      // the Next 14 config never enforced. Revisit when adopting the compiler.
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/refs": "off",
    },
  },
  globalIgnores([".next/**", "node_modules/**", "test-results/**", "next-env.d.ts"]),
]);
