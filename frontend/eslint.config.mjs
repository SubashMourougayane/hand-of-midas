import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
  {
    // React 19 strict-mode rules surface a lot of false positives for
    // legitimate patterns in this app:
    //   - setState in useEffect on mount or when a controlled prop
    //     changes (cancel-on-cancelled, hydrate-from-URL, etc.)
    //   - reading a ref's .current inside render to forward it to a
    //     CountUp animation (we don't *trigger renders* from it)
    //   - unescaped `'` and `"` inside JSX text — readability >> XSS
    //     since the source is hard-coded English copy, not user input
    // Downgrading these to warnings so the build pipeline isn't
    // blocked by stylistic preferences. Real bugs (impure render with
    // Math.random()) are fixed at the source.
    rules: {
      "react/no-unescaped-entities": "off",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
      "react-hooks/preserve-manual-memoization": "warn",
      "react-hooks/purity": "error", // Keep as error — actual impurity is a bug
    },
  },
]);

export default eslintConfig;
