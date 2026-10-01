/* The panel sidebar: a section's header opens its page, a click shows at once that the next page is
   on its way, a quick filter runs over the folding sections, and the sidebar keeps its scroll
   position from page to page (restored by the inline script in nav_sidebar.html, before paint).
   Django's own nav_sidebar.js still runs the show/hide button; its filter looks for the stock
   table rows, which this sidebar doesn't have, so the filtering is done here. */
'use strict';
{
  const SCROLL_KEY = 'mahay.admin.navScroll';
  const nav = document.getElementById('nav-sidebar');
  const filter = document.getElementById('nav-filter');
  if (nav && filter) {
    const apps = [...nav.querySelectorAll('.nav-app')];
    const wasOpen = new Map(apps.map((app) => [app, app.open]));
    const text = (el) => el.textContent.trim().toLowerCase();

    const saveScroll = () => {
      try {
        sessionStorage.setItem(SCROLL_KEY, String(nav.scrollTop));
      } catch (e) { /* private mode: the sidebar just starts at the top */ }
    };
    // shown the moment a sidebar link is clicked, until the next page replaces this one
    const go = (url) => {
      saveScroll();
      document.body.classList.add('is-loading');
      window.location.href = url;
    };
    window.addEventListener('pagehide', saveScroll);
    // coming back with the browser's back button restores the page as it was left: loading and all
    window.addEventListener('pageshow', () => document.body.classList.remove('is-loading'));

    // A section page is fetched ahead while the pointer rests on its header, the same way the
    // browser fetches a hovered sidebar link (the speculation rules in base_site.html).
    const prefetched = new Set();
    const prefetch = (url) => {
      if (prefetched.has(url) || !HTMLScriptElement.supports?.('speculationrules')) return;
      prefetched.add(url);
      const rules = document.createElement('script');
      rules.type = 'speculationrules';
      rules.textContent = JSON.stringify({ prefetch: [{ source: 'list', urls: [url] }] });
      document.head.append(rules);
    };

    const apply = () => {
      const value = filter.value.trim().toLowerCase();
      let any = false;
      for (const app of apps) {
        const appHit = value && text(app.querySelector('.nav-app-name')).includes(value);
        let hits = 0;
        for (const item of app.querySelectorAll('.nav-model')) {
          const hit = !value || appHit || text(item).includes(value);
          item.hidden = !hit;
          if (hit) hits += 1;
        }
        app.hidden = Boolean(value) && hits === 0;
        if (value) {
          // while filtering, every section with a match stays open at once
          app.removeAttribute('name');
          app.open = hits > 0;
        } else {
          app.setAttribute('name', 'nav-apps');
          app.open = wasOpen.get(app);
        }
        any = any || hits > 0;
      }
      filter.classList.toggle('no-results', Boolean(value) && !any);
    };

    // A section's header opens that section's page in the middle column (the new page comes back
    // with the section open). The section already on screen just folds and unfolds.
    for (const app of apps) {
      const summary = app.querySelector('summary');
      const url = app.dataset.url;
      summary.addEventListener('click', (event) => {
        app.classList.add('just-opened');
        if (!url || app.classList.contains('current-app') || filter.value.trim()) return;
        event.preventDefault();
        app.open = true;
        go(url);
      });
      if (url && !app.classList.contains('current-app')) {
        let timer;
        summary.addEventListener('pointerenter', () => { timer = setTimeout(() => prefetch(url), 120); });
        summary.addEventListener('pointerleave', () => clearTimeout(timer));
      }
    }
    nav.addEventListener('click', (event) => {
      const link = event.target.closest('a[href]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
      nav.querySelectorAll('.nav-model.is-going').forEach((item) => item.classList.remove('is-going'));
      link.closest('.nav-model')?.classList.add('is-going');
      saveScroll();
      document.body.classList.add('is-loading');
    });

    filter.addEventListener('input', apply);
    filter.addEventListener('keyup', (event) => {
      if (event.key === 'Escape') {
        filter.value = '';
        apply();
      }
    });
    apply();

    // arriving from outside the sidebar (a breadcrumb, a link in a page): bring the open item in
    const current = nav.querySelector('.current-model') || nav.querySelector('.current-app');
    if (current) {
      const top = current.offsetTop;
      const bottom = top + current.offsetHeight;
      if (top < nav.scrollTop || bottom > nav.scrollTop + nav.clientHeight) {
        nav.scrollTop = top - nav.clientHeight / 3;
      }
    }
  }
}
