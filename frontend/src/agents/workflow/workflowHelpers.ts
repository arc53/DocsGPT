import { type TFunction } from 'i18next';

import { ConditionCase } from '../types/workflow';
import { FilePassing } from './documentConfig';

// Names and handles are the user's own text: React escapes on render, so
// i18next must not escape them first.
export const NO_ESCAPE = { interpolation: { escapeValue: false } } as const;

export interface AgentNodeConfig {
  agent_type: 'classic' | 'research';
  llm_name?: string;
  model_id?: string;
  system_prompt: string;
  prompt_template: string;
  output_variable?: string;
  stream_to_user: boolean;
  sources: string[];
  tools: string[];
  chunks?: string;
  retriever?: string;
  json_schema?: Record<string, unknown>;
  input_documents?: string[];
  file_passing?: FilePassing;
}

export interface UserTool {
  id: string;
  name: string;
  displayName: string;
  customName?: string;
  // Workflow-only builtins (e.g. read_document) are kept here; the classic
  // agent picker filters them out.
  workflow_only?: boolean;
}

/**
 * Check an agent node's structured-output schema.
 *
 * Args:
 *   schema: The parsed schema, or undefined when none is set.
 *
 * Returns:
 *   A short English error fragment, or null when the schema is usable.
 */
export function validateJsonSchemaConfig(schema: unknown): string | null {
  if (schema === undefined || schema === null) return null;
  if (typeof schema !== 'object' || Array.isArray(schema)) {
    return 'must be a valid JSON object';
  }

  const schemaObject = schema as Record<string, unknown>;
  if (!('schema' in schemaObject) && !('type' in schemaObject)) {
    return 'must include either a "type" or "schema" field';
  }

  return null;
}

// The schema validators return short English fragments (tests and the
// validation list key off them); these map each to its locale key.
const SCHEMA_ERROR_KEYS: Record<string, string> = {
  'must be a valid JSON object': 'agents.workflow.schema.notObject',
  'must include either a "type" or "schema" field':
    'agents.workflow.schema.missingType',
  'must be valid JSON': 'agents.workflow.schema.invalidJson',
};

/**
 * Translate a JSON schema validation fragment.
 *
 * Args:
 *   t: The i18next translate function.
 *   fragment: The fragment a schema validator returned.
 *
 * Returns:
 *   The translated fragment, or the fragment itself when it is unknown.
 */
export function schemaErrorText(t: TFunction, fragment: string): string {
  const key = SCHEMA_ERROR_KEYS[fragment];
  return key ? t(key) : fragment;
}

/**
 * Give every condition case a unique `case_N` source handle.
 *
 * Args:
 *   cases: The cases as stored.
 *
 * Returns:
 *   The cases, with missing or duplicate handles replaced.
 */
export function normalizeConditionCases(
  cases: ConditionCase[],
): ConditionCase[] {
  const usedHandles = new Set<string>();
  let nextIndex = 0;

  return cases.map((conditionCase) => {
    const candidate = (conditionCase.sourceHandle || '').trim();
    if (candidate && !usedHandles.has(candidate)) {
      usedHandles.add(candidate);
      const match = candidate.match(/^case_(\d+)$/);
      if (match) {
        nextIndex = Math.max(nextIndex, Number(match[1]) + 1);
      }
      return conditionCase;
    }

    while (usedHandles.has(`case_${nextIndex}`)) {
      nextIndex += 1;
    }
    const generatedHandle = `case_${nextIndex}`;
    usedHandles.add(generatedHandle);
    nextIndex += 1;

    return {
      ...conditionCase,
      sourceHandle: generatedHandle,
    };
  });
}

/**
 * The next free `case_N` handle for a new condition case.
 *
 * Args:
 *   cases: The existing cases.
 *
 * Returns:
 *   An unused handle.
 */
export function getNextConditionHandle(cases: ConditionCase[]): string {
  const usedHandles = new Set(
    cases.map((conditionCase) => conditionCase.sourceHandle).filter(Boolean),
  );
  const usedIndices = Array.from(usedHandles)
    .map((handle) => handle.match(/^case_(\d+)$/))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => Number(match[1]));

  let nextIndex = usedIndices.length > 0 ? Math.max(...usedIndices) + 1 : 0;
  while (usedHandles.has(`case_${nextIndex}`)) {
    nextIndex += 1;
  }

  return `case_${nextIndex}`;
}

interface PlacedNode {
  id: string;
  position: { x: number; y: number };
  width?: number | null;
  height?: number | null;
}

// Nodes React Flow hasn't measured yet count as a typical node.
const DEFAULT_NODE_WIDTH = 200;
const DEFAULT_NODE_HEIGHT = 64;
const NODE_GAP = 24;
const MAX_PLACEMENT_STEPS = 50;

/**
 * Find a spot for a new node that doesn't cover an existing one.
 *
 * Starts at `wanted` (the new node's top-left corner) and steps straight down
 * until the new node's box, with a gap around it, clears every other node.
 *
 * Args:
 *   nodes: The nodes already on the canvas.
 *   wanted: Where the new node would ideally go.
 *   size: The new node's expected size.
 *
 * Returns:
 *   The first free top-left position at or below `wanted`.
 */
export function findFreePosition(
  nodes: PlacedNode[],
  wanted: { x: number; y: number },
  size: { width: number; height: number } = {
    width: DEFAULT_NODE_WIDTH,
    height: DEFAULT_NODE_HEIGHT,
  },
): { x: number; y: number } {
  const overlapping = (y: number) =>
    nodes.find((node) => {
      const width = node.width ?? DEFAULT_NODE_WIDTH;
      const height = node.height ?? DEFAULT_NODE_HEIGHT;
      return (
        wanted.x < node.position.x + width + NODE_GAP &&
        wanted.x + size.width + NODE_GAP > node.position.x &&
        y < node.position.y + height + NODE_GAP &&
        y + size.height + NODE_GAP > node.position.y
      );
    });

  let y = wanted.y;
  for (let step = 0; step < MAX_PLACEMENT_STEPS; step += 1) {
    const blocker = overlapping(y);
    if (!blocker) break;
    y = blocker.position.y + (blocker.height ?? DEFAULT_NODE_HEIGHT) + NODE_GAP;
  }
  return { x: wanted.x, y };
}
