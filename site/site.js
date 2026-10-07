// Shared by every page of the site: reveal on scroll, pointer effects (desktop only), copy buttons.
(function () {
  (function () {
    if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var seen = new IntersectionObserver(function (items) {
      items.forEach(function (it) {
        if (!it.isIntersecting) return;
        // a clipped element never counts as visible, so recordings are watched through their <figure>
        (it.target.tagName === "FIGURE" ? it.target.querySelector("pre") : it.target).classList.add("in");
        seen.unobserve(it.target);
      });
    }, { threshold: 0.12 });
    document.querySelectorAll("figure pre").forEach(function (pre) {
      var n = Math.max(1, pre.textContent.split("\n").length);
      pre.classList.add("rec");
      pre.style.setProperty("--n", n);
      pre.style.setProperty("--dur", Math.min(4.2, Math.max(1.2, n * 0.055)) + "s");
      seen.observe(pre.closest("figure"));
    });
    document.querySelectorAll("dl.grid").forEach(function (dl) {
      Array.prototype.forEach.call(dl.children, function (c, i) { c.style.setProperty("--i", i % 2 + Math.floor(i / 2)); });
      seen.observe(dl);
    });
  })();
  (function () {
    // Desktop pointers only, and never for anyone who asked for less motion. Every effect eases toward the pointer in one rAF loop
    // that sleeps when nothing moves; no scroll listeners.
    if (!matchMedia("(hover: hover) and (pointer: fine)").matches || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    var root = document.documentElement, glow = document.querySelector(".glow"), mark = document.getElementById("mark"),
        prompt = document.getElementById("prompt"), tx = innerWidth / 2, ty = innerHeight * 0.3, x = tx, y = ty, raf = 0;
    var clamp = function (v) { return Math.max(-1, Math.min(1, v)); };
    function frame() {
      x += (tx - x) * 0.08; y += (ty - y) * 0.08;
      root.style.setProperty("--gx", x.toFixed(1) + "px"); root.style.setProperty("--gy", y.toFixed(1) + "px");
      if (mark) {
        var r = mark.getBoundingClientRect(), nx = clamp((x - (r.left + r.width / 2)) / (innerWidth * 0.45)), ny = clamp((y - (r.top + r.height / 2)) / (innerHeight * 0.45));
        mark.style.setProperty("--ry", (nx * 9).toFixed(2) + "deg"); mark.style.setProperty("--rx", (-ny * 7).toFixed(2) + "deg");
        prompt.setAttribute("transform", "translate(" + (nx * 3.2).toFixed(2) + " " + (ny * 2.6).toFixed(2) + ")");
      }
      raf = Math.abs(tx - x) > 0.4 || Math.abs(ty - y) > 0.4 ? requestAnimationFrame(frame) : 0;
    }
    if (glow) glow.classList.add("on");
    addEventListener("pointermove", function (e) {
      tx = e.clientX; ty = e.clientY;
      if (!raf) raf = requestAnimationFrame(frame);
      var t = e.target.closest && e.target.closest(".cut");
      if (t) { var b = t.getBoundingClientRect(); t.style.setProperty("--x", (e.clientX - b.left) + "px"); t.style.setProperty("--y", (e.clientY - b.top) + "px"); }
    }, { passive: true });
    requestAnimationFrame(frame);
  })();
  // Bonny page: the spotlight follows a mouse over the screenshot; the buttons swap the picture and its caption.
  (function () {
    var spot = document.getElementById("spot"), img = document.getElementById("spot-img"), cap = document.getElementById("spot-cap");
    if (!spot) return;
    if (matchMedia("(hover: hover) and (pointer: fine)").matches) {
      spot.addEventListener("pointermove", function (e) {
        var b = spot.getBoundingClientRect();
        spot.style.setProperty("--sx", (e.clientX - b.left) + "px"); spot.style.setProperty("--sy", (e.clientY - b.top) + "px");
        spot.classList.add("on");
      });
      spot.addEventListener("pointerleave", function () { spot.classList.remove("on"); });
    }
    var buttons = document.querySelectorAll(".shots button");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        buttons.forEach(function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
        img.src = btn.dataset.src; img.alt = btn.dataset.alt; cap.textContent = btn.dataset.cap;
      });
    });
  })();
  // copy buttons: <button data-copy="id-of-the-element-with-the-text">
  document.querySelectorAll("button[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var el = document.getElementById(btn.dataset.copy);
      if (!el) return;
      if (!navigator.clipboard) { btn.textContent = "Select it"; return; }
      navigator.clipboard.writeText(el.textContent).then(function () { btn.textContent = "Copied"; setTimeout(function () { btn.textContent = "Copy"; }, 1500); });
    });
  });
})();
