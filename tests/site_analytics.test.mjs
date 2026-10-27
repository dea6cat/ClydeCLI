// The website counter, run as the real site/analytics.js against a fake page: what it sends, and when it sends nothing.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../site/analytics.js", import.meta.url), "utf8");
const COUNTER = "https://counter.example/count";

function element({ closestTo = {}, dataset = {}, text = "", href = "" } = {}) {
  return { textContent: text, dataset, href, closest: (selector) => closestTo[selector] ?? null };
}

// Runs analytics.js on a page; returns the requests it made and the click handler it registered.
function run({ endpoint = COUNTER, host = "dea6cat.github.io", path = "/ClydeCLI/features.html", search = "", referrer = "",
               navigatorProps = {}, stored = {}, optoutButton = false } = {}) {
  const requests = [], clicks = [], listeners = {};
  const storage = { getItem: (k) => stored[k] ?? null, setItem: (k, v) => { stored[k] = v; }, removeItem: (k) => { delete stored[k]; } };
  const button = { textContent: "", addEventListener: (type, fn) => { listeners.optout = fn; } };
  const sandbox = {
    document: { title: "Features", referrer, getElementById: (id) => (optoutButton && id === "analytics-optout" ? button : null),
                addEventListener: (type, fn) => clicks.push({ type, fn }) },
    location: { hostname: host, pathname: path, search },
    navigator: { ...navigatorProps },
    window: { localStorage: storage, fetch: (url, init) => { requests.push({ url, init }); return Promise.resolve(); } },
    URL, Math, Object, String, encodeURIComponent, Image: function () {},
  };
  sandbox.window.window = sandbox.window;
  vm.runInNewContext(SOURCE.replace(/var ENDPOINT = "[^"]*";/, `var ENDPOINT = ${JSON.stringify(endpoint)};`), { ...sandbox, root: undefined }, { filename: "analytics.js" });
  const params = (i) => Object.fromEntries(new URL(requests[i].url).searchParams);
  return { requests, clicks, params, button, listeners, stored };
}

test("with no endpoint set it sends nothing", () => {
  assert.equal(run({ endpoint: "" }).requests.length, 0);
});

test("the documentation tab is counted under its own names, not as the home page or the features page", () => {
  for (const [path, name] of [["/ClydeCLI/docs/usage.html", "/docs-usage"], ["/ClydeCLI/docs/features.html", "/docs-features"], ["/ClydeCLI/docs/", "/docs"],
                              ["/ClydeCLI/docs/index.html", "/docs"], ["/ClydeCLI/docs", "/docs"], ["/ClydeCLI/features.html", "/features"], ["/ClydeCLI/", "/home"]]) {
    assert.equal(run({ path }).params(0).p, name, path);
  }
});

test("a page view carries the page, its title and the site you came from, and nothing else", () => {
  const r = run({ referrer: "https://github.com/dea6cat/ClydeCLI" });
  assert.equal(r.requests.length, 1);
  const { rnd, ...rest } = r.params(0);
  assert.deepEqual(rest, { p: "/features", t: "Features", r: "github.com" });
  assert.ok(rnd);
  assert.equal(r.requests[0].init.credentials, "omit");
  assert.equal(r.requests[0].init.referrerPolicy, "no-referrer");
});

test("a ?ref= label wins over the referrer, and a hostile one is ignored", () => {
  assert.equal(run({ search: "?ref=github-readme", referrer: "https://github.com/x" }).params(0).r, "github-readme");
  assert.equal(run({ search: "?ref=<script>alert(1)</script>", referrer: "https://github.com/x" }).params(0).r, "github.com");
});

test("a move between this site's own pages is labelled internal, and no referrer sends none", () => {
  assert.equal(run({ referrer: "https://dea6cat.github.io/ClydeCLI/" }).params(0).r, "internal");
  assert.equal(run({ referrer: "" }).params(0).r, undefined);
});

test("Do Not Track, Global Privacy Control and the local opt-out each switch it off", () => {
  assert.equal(run({ navigatorProps: { doNotTrack: "1" } }).requests.length, 0);
  assert.equal(run({ navigatorProps: { globalPrivacyControl: true } }).requests.length, 0);
  assert.equal(run({ stored: { "clyde-analytics": "off" } }).requests.length, 0);
});

test("a local preview does not report to a real counter, but does to a local one", () => {
  assert.equal(run({ host: "localhost" }).requests.length, 0);
  assert.equal(run({ host: "localhost", endpoint: "http://localhost:18787/count" }).requests.length, 1);
});

test("a click on a nav tab, a screenshot tab, a copy button and a link to another site each counts under a fixed name", () => {
  const r = run();
  const click = r.clicks.find((c) => c.type === "click").fn;
  const sends = (target) => { const before = r.requests.length; click({ target }); return r.requests.length > before ? r.params(r.requests.length - 1) : null; };
  assert.equal(sends(element({ closestTo: { "nav a": element({ text: "API keys" }) } })).p, "tab-api-keys");
  assert.equal(sends(element({ closestTo: { ".shots button": element({ dataset: { src: "bonnie/automations.png" } }) } })).p, "shot-automations");
  assert.equal(sends(element({ closestTo: { "button[data-copy]": element({ dataset: { copy: "cmd" } }) } })).p, "copy-cmd");
  assert.equal(sends(element({ closestTo: { "a[href]": element({ href: "https://ollama.com/download?x=secret" }) } })).p, "out-ollama-com");
  assert.equal(sends(element({ closestTo: { "a[href]": element({ href: "https://dea6cat.github.io/ClydeCLI/keys.html" }) } })), null);
  assert.equal(sends(element()), null);
  assert.equal(r.params(r.requests.length - 1).e, "1");
});

test("an automated browser is flagged so the counter ignores it", () => {
  assert.equal(run({ navigatorProps: { webdriver: true } }).params(0).b, "153");
});

test("the privacy page's switch turns counting off in this browser and back on", () => {
  const r = run({ endpoint: "", optoutButton: true });
  assert.match(r.button.textContent, /Turn counting off/);
  r.listeners.optout();
  assert.equal(r.stored["clyde-analytics"], "off");
  assert.match(r.button.textContent, /Counting is off/);
  r.listeners.optout();
  assert.equal(r.stored["clyde-analytics"], undefined);
});
