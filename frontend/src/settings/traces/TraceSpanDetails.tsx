import React from 'react';
import { useTranslation } from 'react-i18next';

import { Alert, AlertDescription } from '../../components/ui/alert';
import { ToolCallPanel } from '../../conversation/AnswerFlow';
import { TraceSpan } from '../types';
import { formatDurationMs, formatTokens } from './traceUtils';

type Row = [string, string];

function str(value: unknown): string | undefined {
  if (value === null || value === undefined || value === '') return undefined;
  if (Array.isArray(value)) return value.map(String).join(', ');
  return String(value);
}

function jsonText(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}

type ChunkPreview = {
  title?: string;
  source?: string;
  score?: number;
  text?: string;
};

/** Everything recorded for one span: its key facts, previews and raw attributes. */
export default function TraceSpanDetails({ span }: { span: TraceSpan }) {
  const { t } = useTranslation();
  const a = span.attributes || {};
  const f = (key: string) => t(`settings.logs.trace.fields.${key}`);
  const yes = t('settings.logs.trace.fields.yes');
  const rows: Row[] = [];
  const push = (label: string, value: unknown) => {
    const text = str(value);
    if (text !== undefined) rows.push([label, text]);
  };

  push(
    f('status'),
    t(`settings.logs.trace.status.${span.status}`, span.status),
  );
  push(f('duration'), formatDurationMs(span.duration_ms));
  switch (span.kind) {
    case 'llm': {
      push(f('provider'), a['gen_ai.provider.name']);
      push(f('model'), a['gen_ai.request.model']);
      const input = a['gen_ai.usage.input_tokens'];
      const output = a['gen_ai.usage.output_tokens'];
      if (typeof input === 'number')
        push(f('inputTokens'), formatTokens(input));
      if (typeof output === 'number')
        push(f('outputTokens'), formatTokens(output));
      push(f('cachedTokens'), a['gen_ai.usage.cache_read.input_tokens']);
      if (typeof a['docsgpt.ttft_ms'] === 'number')
        push(f('timeToFirstToken'), formatDurationMs(a['docsgpt.ttft_ms']));
      if (
        typeof a['docsgpt.cost_usd'] === 'number' &&
        a['docsgpt.cost_usd'] > 0
      )
        push(f('cost'), `$${a['docsgpt.cost_usd'].toFixed(6)}`);
      push(f('tokenSource'), a['docsgpt.token_source']);
      if (a['docsgpt.cache_hit']) push(f('cacheHit'), yes);
      if (a['docsgpt.usage_estimated']) push(f('estimatedUsage'), yes);
      break;
    }
    case 'tool':
      push(f('tool'), a['docsgpt.tool']);
      push(f('action'), a['docsgpt.action'] ?? a['gen_ai.tool.name']);
      push(f('callId'), a['gen_ai.tool.call.id']);
      break;
    case 'retrieval':
    case 'search':
    case 'embedding':
    case 'rerank':
      push(f('retriever'), a['docsgpt.retriever']);
      push(f('sources'), a['docsgpt.source_ids'] ?? a['gen_ai.data_source.id']);
      push(f('model'), a['gen_ai.request.model']);
      push(f('topK'), a['docsgpt.top_k']);
      push(f('chunks'), a['docsgpt.chunk_count'] ?? a['docsgpt.kept_count']);
      push(f('candidates'), a['docsgpt.candidate_count']);
      push(f('topScore'), a['docsgpt.top_score']);
      push(f('vectorStore'), a['docsgpt.vector_store']);
      break;
    case 'agent':
      push(f('agentType'), a['docsgpt.agent_type']);
      push(f('model'), a['gen_ai.request.model']);
      push(f('sources'), a['docsgpt.source_count']);
      push(f('toolCalls'), a['docsgpt.tool_call_count']);
      break;
    case 'guardrail':
      push(f('stage'), a['docsgpt.guardrail.stage']);
      push(f('checks'), a['docsgpt.guardrail.checks']);
      push(f('triggered'), a['docsgpt.guardrail.triggered']);
      if (a['docsgpt.guardrail.blocked']) push(f('blocked'), yes);
      if (a['docsgpt.guardrail.redacted']) push(f('redacted'), yes);
      break;
    case 'step':
      push(f('nodeType'), a['docsgpt.workflow.node_type']);
      push(f('phase'), a['docsgpt.research.phase']);
      break;
  }

  const preview = span.preview || {};
  const chunks = Array.isArray(preview.chunks)
    ? (preview.chunks as ChunkPreview[])
    : [];
  const otherPreviews = Object.entries(preview).filter(
    ([key]) =>
      !['arguments', 'result', 'query', 'chunks', 'output'].includes(key),
  );

  return (
    <div className="flex flex-col gap-3 text-xs">
      <div className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)] gap-x-3 gap-y-1">
        {rows.map(([label, value]) => (
          <React.Fragment key={label}>
            <span className="text-muted-foreground">{label}</span>
            <span className="text-foreground break-all">{value}</span>
          </React.Fragment>
        ))}
      </div>
      {span.error && (
        <Alert variant="destructive">
          <AlertDescription className="font-mono whitespace-pre-wrap">
            {span.error}
          </AlertDescription>
        </Alert>
      )}
      {preview.query !== undefined && (
        <ToolCallPanel title={f('query')} copyText={jsonText(preview.query)}>
          <p className="font-mono whitespace-pre-wrap">
            {jsonText(preview.query)}
          </p>
        </ToolCallPanel>
      )}
      {preview.arguments !== undefined && (
        <ToolCallPanel
          title={f('arguments')}
          copyText={jsonText(preview.arguments)}
        >
          <p className="max-h-60 overflow-y-auto font-mono whitespace-pre-wrap">
            {jsonText(preview.arguments)}
          </p>
        </ToolCallPanel>
      )}
      {preview.result !== undefined && (
        <ToolCallPanel title={f('result')} copyText={jsonText(preview.result)}>
          <p className="max-h-60 overflow-y-auto font-mono whitespace-pre-wrap">
            {jsonText(preview.result)}
          </p>
        </ToolCallPanel>
      )}
      {preview.output !== undefined && (
        <ToolCallPanel title={f('output')} copyText={jsonText(preview.output)}>
          <p className="max-h-60 overflow-y-auto whitespace-pre-wrap">
            {jsonText(preview.output)}
          </p>
        </ToolCallPanel>
      )}
      {chunks.length > 0 && (
        <ToolCallPanel
          title={f('retrievedChunks')}
          copyText={JSON.stringify(chunks, null, 2)}
        >
          <ol className="flex max-h-72 flex-col gap-2 overflow-y-auto">
            {chunks.map((chunk, index) => (
              <li key={index} className="flex flex-col gap-0.5">
                <span className="text-foreground font-medium">
                  {index + 1}. {chunk.title || chunk.source || '—'}
                  {typeof chunk.score === 'number' && (
                    <span className="text-muted-foreground ml-2 font-normal tabular-nums">
                      {chunk.score.toFixed(3)}
                    </span>
                  )}
                </span>
                {chunk.text && (
                  <span className="text-muted-foreground line-clamp-3">
                    {chunk.text}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </ToolCallPanel>
      )}
      {otherPreviews.map(([key, value]) => (
        <ToolCallPanel key={key} title={key} copyText={jsonText(value)}>
          <p className="max-h-60 overflow-y-auto font-mono whitespace-pre-wrap">
            {jsonText(value)}
          </p>
        </ToolCallPanel>
      ))}
      <details>
        <summary className="text-muted-foreground cursor-pointer select-none">
          {f('allAttributes')}
        </summary>
        <pre className="text-muted-foreground mt-1 max-h-60 overflow-y-auto font-mono whitespace-pre-wrap">
          {JSON.stringify(a, null, 2)}
        </pre>
      </details>
    </div>
  );
}
