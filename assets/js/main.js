/* OurBnb — ourbnb.gr */
(function () {
  "use strict";

  var header = document.querySelector("[data-header]");
  var toggle = document.querySelector("[data-menu-toggle]");
  var nav = document.querySelector("[data-nav]");

  // Χρονιά στο footer
  document.querySelectorAll("[data-year]").forEach(function (el) {
    el.textContent = String(new Date().getFullYear());
  });

  // Μενού για κινητό
  function setMenu(open) {
    if (!header || !toggle) return;
    header.classList.toggle("is-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  }
  if (toggle) {
    toggle.addEventListener("click", function () {
      setMenu(!header.classList.contains("is-open"));
    });
  }
  if (nav) {
    nav.addEventListener("click", function (e) {
      if (e.target.closest("a")) setMenu(false);
    });
  }
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && header && header.classList.contains("is-open")) {
      setMenu(false);
      toggle.focus();
    }
  });
  document.addEventListener("click", function (e) {
    if (header && header.classList.contains("is-open") && !header.contains(e.target)) setMenu(false);
  });

  // Σκιά στο header όταν κάνεις scroll
  function onScroll() {
    if (header) header.classList.toggle("is-scrolled", window.scrollY > 8);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // Ενεργό link στο μενού ανάλογα με την ενότητα
  if (nav && "IntersectionObserver" in window) {
    var links = Array.prototype.slice.call(nav.querySelectorAll('a[href^="#"]:not(.nav-cta)'));
    var byId = {};
    links.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        var link = byId[entry.target.id];
        if (!link) return;
        if (entry.isIntersecting) {
          links.forEach(function (l) { l.removeAttribute("aria-current"); });
          link.setAttribute("aria-current", "true");
        }
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    Object.keys(byId).forEach(function (id) {
      var section = document.getElementById(id);
      if (section) observer.observe(section);
    });
  }

  // Φόρμα εκτίμησης
  var form = document.querySelector("[data-lead-form]");
  if (!form) return;
  var status = form.querySelector("[data-form-status]");
  var ts = form.querySelector("[data-ts]");
  if (ts) ts.value = String(Math.floor(Date.now() / 1000));

  var FALLBACK = "Κάτι πήγε στραβά. Πάρε μας τηλέφωνο στο 694 803 4055 ή γράψε στο petrospikionis@gmail.com.";

  function showStatus(text, ok) {
    if (!status) return;
    status.textContent = text;
    status.classList.toggle("is-ok", !!ok);
    status.classList.toggle("is-error", !ok);
  }

  function showDone() {
    form.innerHTML =
      '<div class="form-done" role="status">' +
      "<strong>Ευχαριστούμε!</strong>" +
      "<p>Λάβαμε το αίτημά σου. Θα σε πάρουμε τηλέφωνο για να κανονίσουμε την επίσκεψη και την εκτίμηση.</p>" +
      "</div>";
  }

  if (new URLSearchParams(window.location.search).get("lead") === "ok") showDone();

  form.addEventListener("submit", function (e) {
    if (!window.fetch || !window.FormData) return; // απλό POST χωρίς JavaScript
    e.preventDefault();
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }
    var button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    showStatus("Αποστολή…", true);

    fetch(form.getAttribute("action"), {
      method: "POST",
      body: new FormData(form),
      headers: { Accept: "application/json" }
    })
      .then(function (res) {
        return res.json().catch(function () { return { ok: false }; }).then(function (data) {
          return { httpOk: res.ok, data: data };
        });
      })
      .then(function (r) {
        if (r.httpOk && r.data && r.data.ok) {
          showDone();
        } else {
          showStatus((r.data && r.data.message) || FALLBACK, false);
          if (button) button.disabled = false;
        }
      })
      .catch(function () {
        showStatus(FALLBACK, false);
        if (button) button.disabled = false;
      });
  });
})();
