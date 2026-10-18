import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';

/** What the prompt-injection model costs here, as the admin guardrails and defaults routes report it. */
export type InjectionModel = {
  /** The operator's switch (`DECISION_INJECTION_ENABLED`) and a usable model. */
  enabled: boolean;
  runtime: string | null;
  // One check on a user message on this server; null until the model has
  // been measured.
  predicted_input_s: number | null;
  /** The deadline the chat-time check runs within. */
  timeout_s: number;
};

const fmtSeconds = (s: number) => `${s < 10 ? s.toFixed(1) : Math.round(s)} s`;

/** How the administrator turns the model on, while it is off. */
export function InjectionModelOff() {
  return (
    <Alert variant="info" role="note">
      <AlertDescription>
        The prompt-injection model is off on this server, so agents can&apos;t
        use the model check. Turn it on with{' '}
        <code className="font-mono">DECISION_INJECTION_ENABLED=true</code> in
        the server&apos;s environment.
      </AlertDescription>
    </Alert>
  );
}

/**
 * The prompt-injection model's cost on a user message on this server and,
 * when a check would outlast its deadline, the warning that messages go
 * unchecked; or, while the model is off, how to turn it on.
 */
export function InjectionModelNotice({ model }: { model: InjectionModel }) {
  if (!model.enabled) return <InjectionModelOff />;
  const predicted = model.predicted_input_s;
  const runtime = model.runtime ? ` (${model.runtime})` : '';
  return (
    <div className="flex flex-col gap-3">
      <Alert variant="info" role="note">
        <AlertDescription>
          {predicted === null
            ? 'Cost on this server: measured after the model loads.'
            : `Checking a user message adds about ${fmtSeconds(predicted)} on this server${runtime}.`}
        </AlertDescription>
      </Alert>
      {predicted !== null && predicted > model.timeout_s && (
        <Alert variant="warning">
          <AlertTitle>The check will time out on this server</AlertTitle>
          <AlertDescription>
            One check takes longer than its {fmtSeconds(model.timeout_s)}{' '}
            deadline, so messages are recorded as not evaluated. Run the model
            on a GPU or a decision server.
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}
