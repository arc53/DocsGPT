export function getOS() {
  const userAgent = window.navigator.userAgent;
  if (userAgent.indexOf('Mac') !== -1) return 'mac';
  if (userAgent.indexOf('Win') !== -1) return 'win';
  return 'linux';
}

export function isTouchDevice() {
  return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
}

/**
 * Hands a blob to the browser as a file download, through a temporary link.
 *
 * @param blob The file's contents.
 * @param fileName The name the browser saves it under.
 */
export function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(url);
  }
}
