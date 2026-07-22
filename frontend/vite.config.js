import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // katex's tokenizer regex embeds lone UTF-16 surrogate escapes
  // (\uD800 etc., not part of a real pair — used to match astral-plane
  // input as a fallback). esbuild's dependency pre-bundling pass can't
  // re-emit those as valid UTF-8 output and silently replaces them with
  // U+FFFD, corrupting the regex (control sequences like \alpha then only
  // match \a). Excluding just katex (not react-katex, which still needs
  // pre-bundling for its CJS→ESM interop) avoids the batched esbuild
  // transform that introduces this.
  optimizeDeps: {
    exclude: ['katex'],
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
