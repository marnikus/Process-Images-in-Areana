/* Controlled DOM peer only; not packaged, no network or real user page. */
const { JSDOM } = require("jsdom");
const readline = require("node:readline");
const dom = new JSDOM(
  '<main id="fixture"><button data-testid="send">Send</button></main>',
  { runScripts: "outside-only", pretendToBeVisual: true },
);
const w = dom.window;
Object.defineProperty(w.HTMLElement.prototype, "offsetWidth", {
  get() {
    return 100;
  },
});
Object.defineProperty(w.HTMLElement.prototype, "offsetHeight", {
  get() {
    return 40;
  },
});
w.HTMLElement.prototype.getBoundingClientRect = function () {
  return { left: 10, top: 20, width: 100, height: 40, bottom: 60, right: 110 };
};
let clicks = 0;
w.document.querySelector("button").onclick = () => {
  clicks++;
};
readline
  .createInterface({ input: process.stdin })
  .on("line", (line) => {
    try {
      const result = w.eval(JSON.parse(line).script);
      const outlines = [
        ...w.document.querySelectorAll("[data-cf-highlight]"),
      ].map((e) => e.style.outline);
      console.log(
        JSON.stringify({ result, clicks, outlines, stash: !!w.__cfStash }),
      );
    } catch {
      console.log(
        JSON.stringify({
          result: '{"error":"fixture evaluation failed"}',
          clicks,
        }),
      );
    }
  })
  .on("close", () => {
    dom.window.close();
  });
