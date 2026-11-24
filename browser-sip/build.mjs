import { build } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";

const component = "custom_components/simson_v2";
const outdir = `${component}/www`;

await build({
  entryPoints: { "simson-call-card": "src/call-card.js" },
  outdir,
  entryNames: "[name]",
  chunkNames: "chunks/[name]",
  bundle: true,
  splitting: true,
  minify: true,
  format: "esm",
  target: ["chrome110", "safari16.4", "firefox115"],
  loader: { ".css": "text" },
  legalComments: "linked",
  sourcemap: false,
});

await mkdir(`${outdir}/brand`, { recursive: true });
await Promise.all([
  copyFile("node_modules/sip.js/LICENSE.md", `${outdir}/SIPJS-LICENSE.txt`),
  copyFile(`${component}/brand/icon.png`, `${outdir}/brand/icon.png`),
  copyFile(`${component}/brand/logo.png`, `${outdir}/brand/logo.png`),
]);
