export type ToolCallsType = {
  tool_name: string;
  action_name: string;
  call_id: string;
  arguments: Record<string, any>;
  result?: Record<string, any>;
  error?: string;
  status?:
    | 'pending'
    | 'completed'
    | 'error'
    | 'awaiting_approval'
    | 'denied'
    | 'requires_client_execution';
  artifact_id?: string;
  // Every artifact this call produced, with display names. A single call can
  // write several files (``run_code``), and ``artifact_id`` names only the
  // first — the rest had no way into the UI without this.
  // ``ref`` is the model-facing handle (``A1``) — stable per conversation, so
  // a ref the model typed cannot be resolved by position within one turn.
  artifacts?: { id: string; filename?: string | null; ref?: string | null }[];
  // Remote-device tool calls carry the device id so the approval UI can
  // offer a "don't ask again" sticky-pattern action without a lookup.
  device_id?: string;
  // A connection-backed tool whose account needs signing in pauses on a
  // Connect card instead of an approval. Never carries an account or secret.
  connection_required?: {
    connector_key: string | null;
    connector_name: string | null;
    status: 'missing' | 'reconnect_needed' | 'disconnected' | 'error' | string;
  };
  // Which connection a tool call used, for the connector's logo and name on
  // its chip (never an account or a secret).
  connector_key?: string | null;
  connector_name?: string | null;
  access?: 'read' | 'write' | null;
};
