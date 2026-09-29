(function () {
  const header = document.querySelector(".site-header");
  const toggle = document.querySelector(".nav-toggle");
  const nav = document.querySelector(".site-nav");
  const toTop = document.querySelector(".to-top");

  function onScroll() {
    if (header) header.classList.toggle("is-stuck", window.scrollY > 8);
    if (toTop) toTop.classList.toggle("is-on", window.scrollY > 500);
  }
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  if (toggle && nav) {
    const label = toggle.querySelector(".sr-only");
    toggle.addEventListener("click", function () {
      const open = nav.classList.toggle("is-open");
      document.body.classList.toggle("nav-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (label) label.textContent = open ? "\u95dc\u9589\u9078\u55ae" : "\u958b\u555f\u9078\u55ae";
    });
    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        window.setTimeout(function () {
          nav.classList.remove("is-open");
          document.body.classList.remove("nav-open");
          toggle.setAttribute("aria-expanded", "false");
          if (label) label.textContent = "\u958b\u555f\u9078\u55ae";
        }, 0);
      });
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        nav.classList.remove("is-open");
        document.body.classList.remove("nav-open");
        toggle.setAttribute("aria-expanded", "false");
        if (label) label.textContent = "\u958b\u555f\u9078\u55ae";
      }
    });
  }
})();
