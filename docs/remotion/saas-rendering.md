---
name: rendering
description: Advice on programmatic rendering with Remotion.
metadata:
  tags: remotion, saas, ssr, renderer, node, bun, render-server
---

This is about rendering videos programmatically with Remotion.
For one-off renders, `npx remotion render` or the Studio is better suited.

## Comparison of SSR methods

See https://www.remotion.dev/docs/compare-ssr.md for the tradeoffs between server-side rendering options.

## Plain Node.js APIs

Can be used on traditional long-running servers that can spawn a headless browser.

- SSR overview: https://www.remotion.dev/docs/ssr.md
- Renderer package: https://www.remotion.dev/docs/renderer.md
- Node SSR: https://www.remotion.dev/docs/ssr-node.md

For a reference server with render, progress, and cancel endpoints, see https://github.com/remotion-dev/template-render-server.

## Remotion Lambda

Render Remotion videos on AWS Lambda. This is the fastest and most scalable way to render Remotion videos.

- Overview: https://www.remotion.dev/docs/lambda.md
- API: https://www.remotion.dev/docs/lambda/api.md

### Steps to set up Lambda

(Setup checklist lives upstream: https://www.remotion.dev/docs/lambda/setup.md —
IAM roles, credentials in `.env` as `REMOTION_AWS_ACCESS_KEY_ID` /
`REMOTION_AWS_SECRET_ACCESS_KEY`, redeploy function + site on Remotion
upgrades, quota checks.)

Before production, handle rate limiting, authentication, cost controls,
output privacy, render cleanup, and progress/error reporting.

## Vercel

Ideal if planning to deploy the app to Vercel.
See https://www.remotion.dev/docs/vercel-sandbox.md for more info.

## GitHub Actions

See https://www.remotion.dev/docs/ssr.md#render-using-github-actions for how to render on GitHub Actions.
Don't recommend unless asked for.

## Azure Container Apps

See https://www.remotion.dev/docs/azure-container-apps.md if rendering on Azure Container Apps is requested.
Don't recommend unless asked for.

## Cloudflare Containers

See https://www.remotion.dev/docs/cloudflare-containers.md if rendering on Cloudflare Containers is requested.
