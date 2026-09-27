const root = document.querySelector('[data-live-discovery]');
if (root) {
  let busy = false, failures = 0, timer;
  async function refresh() {
    if (busy) return;
    busy = true;
    clearTimeout(timer);
    try {
      const response = await fetch(root.dataset.liveDiscovery, {headers: {'Accept': 'application/json'}, signal: AbortSignal.timeout(8000), cache: 'no-store'});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Unavailable');
      const {invitation} = await response.json();
      const card = root.querySelector('[data-live-invitation]');
      if (card) {
        card.hidden = !invitation;
        if (invitation) {
          card.href = invitation.url;
          card.querySelector('[data-live-label]').textContent = invitation.label;
          card.querySelector('[data-live-title]').textContent = invitation.title;
        }
      }
      const host = document.querySelector('[data-host-card]');
      if (host) {
        host.href = invitation?.url || root.dataset.hostUrl;
        host.querySelector('[data-host-label]').textContent = invitation ? 'Hosting Live Quiz' : 'Host a Quiz';
      }
      failures = 0;
    } catch { failures++; }
    finally {
      busy = false;
      timer = setTimeout(refresh, Math.min(30000, 5000 * 2 ** Math.min(failures, 3)) + Math.random() * 500);
    }
  }
  window.addEventListener('focus', refresh);
  refresh();
}
