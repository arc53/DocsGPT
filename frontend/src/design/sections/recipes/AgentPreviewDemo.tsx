import { useState } from 'react';
import { Button } from '@/components/ui/button';
import AgentPreviewSheet from '../../../agents/components/AgentPreviewSheet';
import type { WorkflowNode } from '../../../agents/types/workflow';
import {
  ExecutionDetails,
  RunArtifactsSection,
} from '../../../agents/workflow/WorkflowPreview';
import type { WorkflowExecutionStep } from '../../../agents/workflow/workflowPreviewSlice';

// Sample run for the Agent preview drawer example.
const DEMO_WORKFLOW_NODES = [
  { id: 'd1', type: 'agent', title: 'Find expiring certificates' },
  { id: 'd2', type: 'state', title: 'Set region' },
  { id: 'd3', type: 'agent', title: 'Draft reminders' },
] as unknown as WorkflowNode[];

const DEMO_WORKFLOW_STEPS = [
  {
    nodeId: 'd1',
    nodeType: 'agent',
    nodeTitle: 'Find expiring certificates',
    status: 'completed',
    output: 'Three carriers have certificates expiring before 31 October.',
  },
  {
    nodeId: 'd2',
    nodeType: 'state',
    nodeTitle: 'Set region',
    status: 'completed',
    stateDelta: { region: 'EU', carriers: ['Halvorsen', 'Nordline'] },
  },
  {
    nodeId: 'd3',
    nodeType: 'agent',
    nodeTitle: 'Draft reminders',
    status: 'failed',
    error: 'The email tool timed out after 30 s.',
  },
] as unknown as WorkflowExecutionStep[];

/**
 * App recipe for the /design gallery: the agent preview drawer with a sample workflow run inside.
 * Rendered in place by its section; a candidate to cut from the system demos.
 */
export default function AgentPreviewDemo() {
  const [agentPreviewOpen, setAgentPreviewOpen] = useState(false);
  const [demoStepsOpen, setDemoStepsOpen] = useState(true);
  return (
    <>
      <Button
        variant="outline"
        onClick={() => setAgentPreviewOpen(true)}
        data-testid="ds-agent-preview"
      >
        Agent preview
      </Button>
      <AgentPreviewSheet
        open={agentPreviewOpen}
        onOpenChange={setAgentPreviewOpen}
        title="Preview"
        description="Carrier compliance workflow · Checks certificates weekly"
        running
      >
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto py-4">
          <ExecutionDetails
            steps={DEMO_WORKFLOW_STEPS}
            nodes={DEMO_WORKFLOW_NODES}
            isOpen={demoStepsOpen}
            onToggle={() => setDemoStepsOpen(!demoStepsOpen)}
          />
          <RunArtifactsSection
            workflowRunId="demo"
            isOpen={false}
            onToggle={() => undefined}
          />
        </div>
      </AgentPreviewSheet>
    </>
  );
}
