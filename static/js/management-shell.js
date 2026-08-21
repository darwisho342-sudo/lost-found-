(() => {
  const body = document.body;
  const sidebar = document.querySelector('#adminSidebar');
  const openButton = document.querySelector('[data-admin-sidebar-open]');
  const closeButton = document.querySelector('[data-admin-sidebar-close]');
  const backdrop = document.querySelector('[data-admin-sidebar-backdrop]');
  const mobile = window.matchMedia('(max-width: 991.98px)');
  if (!body.classList.contains('sidebar-layout') || !sidebar || !openButton || !closeButton || !backdrop) return;

  let previousFocus = null;
  const focusableSelector = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';

  const setOpen = (open, restoreFocus = true) => {
    const shouldOpen = mobile.matches && open;
    body.classList.toggle('admin-sidebar-open', shouldOpen);
    openButton.setAttribute('aria-expanded', String(shouldOpen));
    sidebar.setAttribute('aria-hidden', mobile.matches ? String(!shouldOpen) : 'false');
    sidebar.inert = mobile.matches && !shouldOpen;
    if (shouldOpen) {
      previousFocus = document.activeElement;
      closeButton.focus();
    } else if (restoreFocus && previousFocus instanceof HTMLElement) {
      previousFocus.focus();
      previousFocus = null;
    }
  };

  openButton.addEventListener('click', () => setOpen(true));
  closeButton.addEventListener('click', () => setOpen(false));
  backdrop.addEventListener('click', () => setOpen(false));
  sidebar.addEventListener('click', (event) => {
    if (mobile.matches && event.target.closest('a[href]')) setOpen(false, false);
  });

  document.addEventListener('keydown', (event) => {
    if (!mobile.matches || !body.classList.contains('admin-sidebar-open')) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key !== 'Tab') return;
    const focusable = [...sidebar.querySelectorAll(focusableSelector)].filter((item) => !item.closest('[hidden]'));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  const synchronizeBreakpoint = () => setOpen(false, false);
  mobile.addEventListener?.('change', synchronizeBreakpoint);
  synchronizeBreakpoint();
})();
