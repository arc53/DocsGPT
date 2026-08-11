// happy-dom's localStorage lives on `window`; slices read the bare
// global at module-load. Install a Map-backed shim on globalThis.
const store = new Map<string, string>();
const shim = {
  getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
  setItem: (k: string, v: string) => {
    store.set(k, String(v));
  },
  removeItem: (k: string) => {
    store.delete(k);
  },
  clear: () => store.clear(),
  key: (i: number) => Array.from(store.keys())[i] ?? null,
  get length() {
    return store.size;
  },
};
// Force-override: some happy-dom versions expose a Storage stub
// without getItem, so simple assignment isn't enough.
Object.defineProperty(globalThis, 'localStorage', {
  value: shim,
  writable: true,
  configurable: true,
});
