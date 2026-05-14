(() => {
  const root = document.documentElement;
  const THEME_KEY = "sipadu_theme";
  const SIDEBAR_KEY = "sipadu_sidebar";
  const MOBILE_BP = 1080;

  // ---------- Theme ----------
  function currentTheme() {
    return root.dataset.theme === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    const next = theme === "dark" ? "dark" : "light";
    root.dataset.theme = next;
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (_) {}
    document.querySelectorAll("[data-theme-label]").forEach((el) => {
      el.textContent = next === "dark" ? "Gelap" : "Terang";
    });
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-pressed", String(next === "dark"));
    });
  }

  // ---------- Sidebar ----------
  function getShell() {
    return document.querySelector(".app-shell");
  }

  function isMobile() {
    return window.matchMedia(`(max-width: ${MOBILE_BP}px)`).matches;
  }

  function applyStoredSidebar() {
    const shell = getShell();
    if (!shell) return;
    let stored = null;
    try {
      stored = localStorage.getItem(SIDEBAR_KEY);
    } catch (_) {}
    if (stored === "collapsed" && !isMobile()) {
      shell.dataset.sidebar = "collapsed";
    } else {
      shell.dataset.sidebar = "expanded";
    }
    shell.dataset.mobileOpen = "false";
  }

  function toggleSidebar() {
    const shell = getShell();
    if (!shell) return;
    if (isMobile()) {
      const next = shell.dataset.mobileOpen === "true" ? "false" : "true";
      shell.dataset.mobileOpen = next;
      return;
    }
    const collapsed = shell.dataset.sidebar === "collapsed";
    const nextState = collapsed ? "expanded" : "collapsed";
    shell.dataset.sidebar = nextState;
    try {
      localStorage.setItem(SIDEBAR_KEY, nextState);
    } catch (_) {}
  }

  function closeMobileSidebar() {
    const shell = getShell();
    if (shell && shell.dataset.mobileOpen === "true") {
      shell.dataset.mobileOpen = "false";
    }
  }

  // ---------- Boot ----------
  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(currentTheme());
    applyStoredSidebar();

    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        applyTheme(currentTheme() === "dark" ? "light" : "dark");
      });
    });

    document.querySelectorAll("[data-sidebar-toggle]").forEach((button) => {
      button.addEventListener("click", toggleSidebar);
    });

    document.querySelectorAll("[data-sidebar-close]").forEach((el) => {
      el.addEventListener("click", closeMobileSidebar);
    });

    // Close mobile drawer after a sidebar link click
    document.querySelectorAll(".sidebar .side-link").forEach((link) => {
      link.addEventListener("click", () => {
        if (isMobile()) closeMobileSidebar();
      });
    });

    // Reset mobile state when resizing to desktop
    window.addEventListener("resize", () => {
      const shell = getShell();
      if (!shell) return;
      if (!isMobile() && shell.dataset.mobileOpen === "true") {
        shell.dataset.mobileOpen = "false";
      }
    });

    // Escape closes mobile sidebar
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMobileSidebar();
    });
  });
})();
