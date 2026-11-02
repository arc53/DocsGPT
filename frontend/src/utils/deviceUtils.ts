/** How recently a remote device must have checked in to count as online. */
export const DEVICE_ONLINE_WINDOW_MS = 30_000;

type SeenDevice = { last_seen_at?: string | null };

/**
 * Whether a paired device checked in within the online window.
 *
 * Args:
 *   device: The device, or null while it loads.
 *   now: The time to measure from, in ms.
 *
 * Returns:
 *   True when it was seen in the last 30 seconds.
 */
export function isDeviceOnline(
  device: SeenDevice | null | undefined,
  now: number = Date.now(),
): boolean {
  if (!device?.last_seen_at) return false;
  const seen = Date.parse(device.last_seen_at);
  if (Number.isNaN(seen)) return false;
  return now - seen < DEVICE_ONLINE_WINDOW_MS;
}

/**
 * Each device's online state by id, for the tool pickers' status badges.
 *
 * Args:
 *   devices: The devices `/api/devices` lists.
 *   now: The time to measure from, in ms.
 *
 * Returns:
 *   Device id → online.
 */
export const deviceOnlineMap = (
  devices: (SeenDevice & { id: string })[],
  now: number = Date.now(),
): Map<string, boolean> =>
  new Map(devices.map((device) => [device.id, isDeviceOnline(device, now)]));
