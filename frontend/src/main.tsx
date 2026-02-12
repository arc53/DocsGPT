import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { BrowserRouter } from 'react-router-dom';
import { Provider } from 'react-redux';
import store from './store';
import './index.css';

// Show scrollbar on scroll for scrollbar-overlay elements, hide after 1s idle
const scrollTimers = new WeakMap<Element, ReturnType<typeof setTimeout>>();
let sbIdCounter = 0;
const sbStyleEl = document.createElement('style');
document.head.appendChild(sbStyleEl);
const activeSbs = new Map<string, string>();
function rebuildSbStyles() {
  sbStyleEl.textContent = Array.from(activeSbs.values()).join('');
}
function showOverlayScrollbar(el: HTMLElement) {
  if (!el.dataset.sbId) el.dataset.sbId = String(++sbIdCounter);
  const sbId = el.dataset.sbId;
  const isDark = document.body.classList.contains('dark');
  const thumb = isDark ? '#949494' : '#E2E8F0';
  const thumbHover = isDark ? '#F0F0F0' : '#8C9198';
  // Webkit: inject <style> (Safari only re-renders scrollbar on stylesheet changes)
  activeSbs.set(
    sbId,
    `[data-sb-id="${sbId}"]::-webkit-scrollbar-thumb{background:${thumb}!important;border-radius:9999px}` +
      `[data-sb-id="${sbId}"]::-webkit-scrollbar-thumb:hover{background:${thumbHover}!important}`,
  );
  rebuildSbStyles();
  // Standard property (Chrome 121+, Firefox)
  el.style.scrollbarColor = `${thumb} transparent`;

  const prev = scrollTimers.get(el);
  if (prev) clearTimeout(prev);
  scrollTimers.set(
    el,
    setTimeout(() => {
      activeSbs.delete(sbId);
      rebuildSbStyles();
      el.style.removeProperty('scrollbar-color');
    }, 1000),
  );
}
// scroll events don't bubble — use capture phase, target is the scrolling element
document.addEventListener(
  'scroll',
  (e) => {
    const target = e.target;
    if (
      target instanceof HTMLElement &&
      target.classList.contains('scrollbar-overlay')
    ) {
      showOverlayScrollbar(target);
    }
  },
  true,
);
// wheel events bubble — use closest() to find the overlay container (works in Safari)
document.addEventListener(
  'wheel',
  (e) => {
    const el = (e.target as Element)?.closest?.('.scrollbar-overlay');
    if (el instanceof HTMLElement) showOverlayScrollbar(el);
  },
  { passive: true },
);

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <Provider store={store}>
        <App />
      </Provider>
    </BrowserRouter>
  </React.StrictMode>,
);
