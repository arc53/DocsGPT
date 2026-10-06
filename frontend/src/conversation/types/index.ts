export type ToolCallsType = {
  tool_name: string;
  action_name: string;
  call_id: string;
  arguments: Record<string, any>;
  // What the call sends once fixed values replace what the model asked for;
  // absent when they are the same. The chat shows this.
  sent_arguments?: Record<string, any>;
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
  /** Link secret references approving this call fills in (`{{link_secret:REF}}` ids). */
  secret_refs?: string[];
  // A connection-backed tool whose account needs signing in pauses on a
  // Connect card instead of an approval. Never carries an account or secret.
  connection_required?: {
    connector_key: string | null;
    connector_name: string | null;
    status: 'missing' | 'reconnect_needed' | 'disconnected' | 'error' | string;
    /** The caller's own connection, reconnected in place. */
    connection_id?: string;
    /** The tool runs on its owner's account, not the caller's. */
    owner_account?: boolean;
    /** How to name that owner (their email); absent when unknown. */
    owner_name?: string;
  };
  // Which connection a tool call used (or, paused for approval, will use),
  // for the connector's logo and name on its chip and approval card (never
  // an account or a secret).
  connector_key?: string | null;
  connector_name?: string | null;
  access?: 'read' | 'write' | null;
  // Set when the call became a background job; the chat shows a job card.
  job_id?: string;
  // The job's final status, patched onto the saved call when the job ends.
  job_status?: string;
  /** When the job behind a handed-off call started and finished (patched on when it ends). */
  job_started_at?: string;
  job_finished_at?: string;
};

/** The arguments to show for a call: what it sends, not what the model asked. */
export const shownArguments = (toolCall: ToolCallsType): Record<string, any> =>
  toolCall.sent_arguments ?? toolCall.arguments ?? {};
