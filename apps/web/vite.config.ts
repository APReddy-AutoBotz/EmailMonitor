import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => ({
  plugins: [react(), {
    name: 'production-content-policy',
    transformIndexHtml() {
      if (command !== 'build') return []
      return [{
        tag: 'meta',
        attrs: {
          'http-equiv': 'Content-Security-Policy',
          content: "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'",
        },
        injectTo: 'head',
      }]
    },
  }],
  server: { host: '127.0.0.1' },
}))
