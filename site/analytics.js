// Counts visits to this site without cookies, accounts or any stored identifier. It sends the page, the tab or button clicked and the
// site you came from (the host name only), and nothing else. Do Not Track and Global Privacy Control switch it off, and so does
// privacy.html. With ENDPOINT empty it sends nothing at all.
(function (root) {
  "use strict";
  // The counter to send to: the project's GoatCounter. Any service or server that takes GoatCounter's GET /count (p=, e=, r=, t=, b=)
  // works instead, such as tools/telemetry_receiver.py behind https. Empty: nothing is sent.
  var ENDPOINT = "https://dea6cat.goatcounter.com/count";
  var OPT_OUT_KEY = "clyde-analytics";

  function slug(text) {
    return String(text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
  }
  // features.html -> "features"; the home page, however it is reached -> "home"
  function pageName(pathname) {
    var parts = String(pathname || "").split("/").filter(Boolean), last = (parts.pop() || "").replace(/\.html$/, "");
    // the documentation tab: docs/usage.html -> "docs-usage", so it is not mistaken for the home page's own "features"; docs/ -> "docs"
    if (last === "docs" || parts.pop() === "docs") return last && last !== "index" && last !== "docs" ? "docs-" + (slug(last) || "page") : "docs";
    return !last || last === "index" || last === "ClydeCLI" ? "home" : slug(last) || "home";
  }
  // A ?ref=label in the link says where it was placed (github-readme); otherwise the site the visitor came from, as a host name;
  // "internal" for a move between this site's own pages, so it is not mistaken for an arrival; "" when there is no referrer.
  function referrerLabel(search, referrerUrl, ownHost) {
    var ref = /[?&]ref=([a-z0-9-]{1,24})(?:&|$)/i.exec(search || "");
    if (ref) return ref[1].toLowerCase();
    try {
      var host = new URL(referrerUrl).hostname.toLowerCase().replace(/^www\./, "");
      return host === String(ownHost || "").toLowerCase().replace(/^www\./, "") ? "internal" : host;
    } catch (e) { return ""; }
  }
  // The name of a click worth counting, or "" to ignore it: a nav tab, a screenshot tab, a copy button, a link to another site.
  function clickName(el, ownHost) {
    if (!el || !el.closest) return "";
    var tab = el.closest("nav a");
    if (tab) return "tab-" + slug(tab.textContent);
    var shot = el.closest(".shots button");
    if (shot) return "shot-" + slug(String(shot.dataset.src || "").split("/").pop().replace(/\.[a-z]+$/, ""));
    var copy = el.closest("button[data-copy]");
    if (copy) return "copy-" + slug(copy.dataset.copy);
    var link = el.closest("a[href]");
    if (link && /^https?:/.test(link.href)) {
      try {
        var host = new URL(link.href).hostname.toLowerCase().replace(/^www\./, "");
        if (host && host !== String(ownHost || "").toLowerCase().replace(/^www\./, "")) return "out-" + slug(host);
      } catch (e) { /* not a URL */ }
    }
    return "";
  }
  function url(endpoint, params) {
    var parts = [];
    Object.keys(params).forEach(function (k) { if (params[k] !== "" && params[k] != null) parts.push(k + "=" + encodeURIComponent(params[k])); });
    return endpoint + (endpoint.indexOf("?") < 0 ? "?" : "&") + parts.join("&");
  }
  var api = { slug: slug, pageName: pageName, referrerLabel: referrerLabel, clickName: clickName, url: url };

  function optedOut(nav, storage) {
    if (nav.doNotTrack === "1" || nav.globalPrivacyControl === true) return true;
    try { return storage.getItem(OPT_OUT_KEY) === "off"; } catch (e) { return false; }
  }
  function send(endpoint, params, nav) {
    if (nav.webdriver) params.b = 153;   // an automated browser: the counter ignores it
    params.rnd = Math.random().toString(36).slice(2, 8);
    var target = url(endpoint, params);
    if (root.fetch) root.fetch(target, { method: "GET", mode: "no-cors", credentials: "omit", keepalive: true, referrerPolicy: "no-referrer" }).catch(function () {});
    else new Image().src = target;
  }
  function start(doc, loc, nav, storage) {
    var button = doc.getElementById("analytics-optout");
    if (button) {   // privacy.html: a switch for this browser, whatever ENDPOINT is
      var show = function () { button.textContent = optedOut({}, storage) ? "Counting is off in this browser. Turn it on" : "Turn counting off in this browser"; };
      button.addEventListener("click", function () {
        try { optedOut({}, storage) ? storage.removeItem(OPT_OUT_KEY) : storage.setItem(OPT_OUT_KEY, "off"); } catch (e) { /* storage blocked */ }
        show();
      });
      show();
    }
    if (!ENDPOINT || optedOut(nav, storage)) return;
    var local = /^(localhost|127\.0\.0\.1)$/.test(loc.hostname);
    if (local && !/^https?:\/\/(localhost|127\.0\.0\.1)/.test(ENDPOINT)) return;   // a local preview never reports to the real counter
    send(ENDPOINT, { p: "/" + pageName(loc.pathname), t: doc.title, r: referrerLabel(loc.search, doc.referrer, loc.hostname) }, nav);
    doc.addEventListener("click", function (e) {
      var name = clickName(e.target, loc.hostname);
      if (name) send(ENDPOINT, { p: name, e: 1 }, nav);
    }, true);
  }

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof document !== "undefined") start(document, location, navigator, root.localStorage || { getItem: function () {}, setItem: function () {}, removeItem: function () {} });
})(typeof window !== "undefined" ? window : this);
