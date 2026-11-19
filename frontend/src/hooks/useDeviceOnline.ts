import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';

import devicesService from '../api/services/devicesService';
import { selectToken } from '../preferences/preferenceSlice';
import { deviceOnlineMap } from '../utils/deviceUtils';

/**
 * Remote devices' online state for a tool picker's Online / Offline badges,
 * the same in the chat, the agent builder and a workflow agent node. It asks
 * each time the picker opens with a device in its list, so the badge is
 * fresh; until the answer comes, or when the list fails, it is undefined and
 * the rows show no status.
 *
 * Args:
 *   open: Whether the picker is open.
 *   tools: The picker's tools; only a `remote_device` one makes it ask.
 *
 * Returns:
 *   Device id → online, or undefined while unknown.
 */
export function useDeviceOnline(
  open: boolean,
  tools: readonly { name: string }[],
): Map<string, boolean> | undefined {
  const token = useSelector(selectToken);
  const hasRemoteDevice = tools.some((tool) => tool.name === 'remote_device');
  const [online, setOnline] = useState<Map<string, boolean>>();
  useEffect(() => {
    if (!open || !hasRemoteDevice) return;
    let current = true;
    devicesService
      .list(token)
      .then((result) => {
        if (current) setOnline(deviceOnlineMap(result?.devices ?? []));
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [open, hasRemoteDevice, token]);
  return online;
}
