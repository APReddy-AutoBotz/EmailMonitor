# Web scaffold

From the repository root, run `pnpm --dir apps/web install --frozen-lockfile --strict-peer-dependencies` then `pnpm --dir apps/web dev`. Open the loopback URL Vite prints. This UI has disabled keyword/source/URL inputs and explicit unavailable-extraction status. It does not display synthetic fixture expectations as results and makes no API or third-party requests.

`pnpm --dir apps/web test` renders the actual React component and checks its unavailable state. It is a component smoke test, not browser accessibility/UAT certification. `pnpm --dir apps/web build` performs TypeScript checking and creates a local production bundle. Hosting, TLS and HTTP security headers remain future deployment work. Vite development uses its development CSP behavior; the committed static production document restricts resource loading to the same origin.
