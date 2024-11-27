export function truncate(str: string, n: number) {
  // slices long strings and ends with ...
  return str.length > n ? str.slice(0, n - 1) + '...' : str;
}
