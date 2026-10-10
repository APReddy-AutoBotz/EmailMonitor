import tseslint from 'typescript-eslint'
import globals from 'globals'

export default tseslint.config(
  ...tseslint.configs.recommended,
  { files: ['src/**/*.{ts,tsx}', 'vite.config.ts'], languageOptions: { globals: globals.browser } },
  { files: ['eslint.config.js'], languageOptions: { globals: globals.node } },
)
