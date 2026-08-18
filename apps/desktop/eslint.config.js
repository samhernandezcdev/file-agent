import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src-tauri/target", "src/vite-env.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
    },
  },
  {
    // FA-017 design §"FRONTEND TAURI BOUNDARY": only src/desktop/ may
    // import Tauri frontend APIs. Every feature calls its typed wrappers
    // instead -- no component anywhere else calls invoke() directly or
    // imports a Tauri plugin.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/desktop/**", "**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@tauri-apps/*"],
              message:
                "Only src/desktop/ may import Tauri frontend APIs -- call the typed desktop.* wrapper instead.",
            },
          ],
        },
      ],
    },
  },
);
