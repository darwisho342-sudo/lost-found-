(() => {
  const center = document.querySelector('[data-notification-center]');
  if (!center) return;
  const badge = center.querySelector('[data-notification-count]');
  const button = center.querySelector('.notification-bell-button');
  const refresh = async () => {
    if (document.hidden) return;
    try {
      const response = await fetch(center.dataset.countUrl, { headers: { Accept: 'application/json' } });
      if (response.status === 401 || response.status === 403 || response.redirected) return;
      if (!response.ok) return;
      const data = await response.json();
      badge.textContent = data.unread_count;
      badge.classList.toggle('d-none', data.unread_count === 0);
      if (button) {
        const label = data.unread_count === 1 ? button.dataset.unreadSingular : button.dataset.unreadPlural;
        button.setAttribute('aria-label', `${data.unread_count} ${label}`);
      }
    } catch (_) { /* A quiet polling failure must not interrupt the page. */ }
  };
  let timer = window.setInterval(refresh, 15000);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { window.clearInterval(timer); timer = null; }
    else { refresh(); if (!timer) timer = window.setInterval(refresh, 15000); }
  });
})();
