export function getOS() {
  const userAgent = window.navigator.userAgent;
  if (userAgent.indexOf('Mac') !== -1) return 'mac';
  if (userAgent.indexOf('Win') !== -1) return 'win';
  return 'linux';
}

export function isTouchDevice() {
  return 'ontouchstart' in window || navigator.maxTouchPoints > 0;
}
