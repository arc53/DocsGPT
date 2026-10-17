import { type Node } from 'reactflow';

/** Props every node settings panel body takes. */
export interface NodePanelBodyProps {
  /** The node being edited. */
  node: Node;
  /** Merge fields into the node's data (a snapshot first unless disabled). */
  onUpdate: (
    data: Record<string, unknown>,
    options?: { snapshot?: boolean },
  ) => void;
}
