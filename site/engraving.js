// Engraving layer: the viewport frame, film grain, illustrations that lag the scroll and fade up, a flash where you click.
(function () {
  var frame = document.createElement("div");
  frame.className = "vframe";
  frame.setAttribute("aria-hidden", "true");
  frame.innerHTML = '<i class="amb t"></i><i class="amb r"></i><i class="amb b"></i><i class="amb l"></i><i class="sglow"></i><i class="flash"></i>';
  var grain = document.createElement("div");
  grain.className = "grain";
  grain.setAttribute("aria-hidden", "true");
  document.body.append(frame, grain);

  var plates = document.querySelectorAll(".plate");
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if ("IntersectionObserver" in window) {
    var seen = new IntersectionObserver(function (items) {
      items.forEach(function (it) { if (it.isIntersecting) { it.target.classList.add("in"); seen.unobserve(it.target); } });
    }, { rootMargin: "0px 0px -12% 0px" });
    plates.forEach(function (p) { seen.observe(p); });
  }
  var queued = false;
  function drift() {
    queued = false;
    var vh = innerHeight || 1, sc = document.scrollingElement, max = sc.scrollHeight - sc.clientHeight;
    if (max > 0) frame.style.setProperty("--sp", (sc.scrollTop / max * 100).toFixed(1) + "%");
    plates.forEach(function (p) {
      var r = p.getBoundingClientRect();
      if (r.bottom < -vh || r.top > vh * 2) return;
      // the picture moves at 0.35 of the scroll, measured from its centre crossing the viewport centre
      var lag = Math.max(-r.height * 0.3, Math.min(r.height * 0.3, (vh / 2 - (r.top + r.height / 2)) * 0.35));
      p.querySelector("img").style.setProperty("--lag", lag.toFixed(1) + "px");
    });
  }
  function queue() { if (!queued) { queued = true; requestAnimationFrame(drift); } }
  addEventListener("scroll", queue, { passive: true });
  addEventListener("resize", queue, { passive: true });
  var flash = frame.querySelector(".flash");
  addEventListener("pointerdown", function (e) {
    flash.style.setProperty("--cx", e.clientX + "px");
    flash.style.setProperty("--cy", e.clientY + "px");
    flash.classList.remove("on");
    void flash.offsetWidth;
    flash.classList.add("on");
  }, { passive: true });
  drift();
})();
