import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      "react-hooks/purity": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Unit tests run on `node --test` with native TS type-stripping, which
    // requires explicit `.ts` import extensions (rejected by the app tsconfig /
    // typecheck). Keep them out of the app lint/build; they run via `npm test`.
    "**/*.test.ts",
  ]),
]);

export default eslintConfig;
