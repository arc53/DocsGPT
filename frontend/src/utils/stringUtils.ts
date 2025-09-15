export function truncate(str: string, n: number) {
  // slices long strings and ends with ...
  return str.length > n ? str.slice(0, n - 1) + '...' : str;
}

export function formatBytes(bytes: number | null): string {
  if (!bytes || bytes <= 0) return '';

  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}
