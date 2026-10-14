/* Countdown timers. The server sends the seconds remaining (data-seconds), so
   the display never depends on the visitor's clock being right. This is
   cosmetic only: the server alone decides when bidding opens and closes. */
(function () {
  var els = Array.prototype.slice.call(document.querySelectorAll("[data-countdown]"));
  if (!els.length) return;
  var t0 = Date.now();
  var pad = function (n) { return (n < 10 ? "0" : "") + n; };

  function fmt(s) {
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
        m = Math.floor((s % 3600) / 60), x = s % 60;
    return (d > 0 ? d + "d " : "") + pad(h) + ":" + pad(m) + ":" + pad(x);
  }

  els.forEach(function (el) {
    el._total = parseInt(el.getAttribute("data-seconds"), 10) || 0;
    el._startedAtZero = el._total === 0;
  });

  function tick() {
    var elapsed = Math.floor((Date.now() - t0) / 1000);
    els.forEach(function (el) {
      var left = Math.max(0, el._total - elapsed);
      var valueEl = el.querySelector(".cd-value");
      if (left > 0) {
        valueEl.textContent = fmt(left);
        el.classList.toggle("cd-urgent", left <= 300);
        return;
      }
      valueEl.textContent = el.getAttribute("data-done-text") || "00:00:00";
      el.classList.remove("cd-urgent");
      el.classList.add("cd-done");
      if (el.getAttribute("data-reload") === "1" && !el._reloadQueued) {
        el._reloadQueued = true;
        // Re-check with the server shortly after zero; wait longer if the
        // page was already at zero when it loaded, to avoid reload loops.
        setTimeout(function () { window.location.reload(); }, el._startedAtZero ? 20000 : 3000);
      }
    });
  }
  tick();
  setInterval(tick, 1000);
})();
