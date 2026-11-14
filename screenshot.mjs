// Screenshot helper: `node screenshot.mjs http://localhost:3000 [label]`
// Requires puppeteer to be resolvable. Set PUPPETEER_PATH if it lives elsewhere.
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";

const url = process.argv[2] || "http://localhost:3000";
const label = process.argv[3] || "";
const OUT_DIR = "temporary screenshots";

const require = createRequire(import.meta.url);
let puppeteer;
for (const candidate of [
  "puppeteer",
  process.env.PUPPETEER_PATH,
  "C:/Users/nateh/AppData/Local/Temp/puppeteer-test/node_modules/puppeteer"
].filter(Boolean)) {
  try {
    puppeteer = require(candidate);
    break;
  } catch {
    /* try the next candidate */
  }
}

if (!puppeteer) {
  console.error(
    "Puppeteer not found. Run `npm i -D puppeteer` here, or set PUPPETEER_PATH to an existing install."
  );
  process.exit(1);
}

await mkdir(OUT_DIR, { recursive: true });

const browser = await puppeteer.launch({ headless: "new", defaultViewport: { width: 1600, height: 980 } });
const page = await browser.newPage();
const errors = [];
page.on("pageerror", (err) => errors.push(String(err)));
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});

await page.goto(url, { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2500));

let index = 1;
for (;;) {
  try {
    await (await import("node:fs/promises")).access(join(OUT_DIR, `screenshot-${index}${label ? "-" + label : ""}.png`));
    index += 1;
  } catch {
    break;
  }
}
const file = join(OUT_DIR, `screenshot-${index}${label ? "-" + label : ""}.png`);
await page.screenshot({ path: file });
console.log(`saved ${file}`);
if (errors.length) console.log("page errors:\n" + errors.join("\n"));
await browser.close();
