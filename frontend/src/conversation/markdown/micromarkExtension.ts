import type { Extension } from 'micromark-util-types';
import type { Processor } from 'unified';

// The tokens `remark-math`'s `mathFromMarkdown` turns into math nodes, which
// the constructs here emit too.
declare module 'micromark-util-types' {
  interface TokenTypeMap {
    mathFlow: 'mathFlow';
    mathFlowFence: 'mathFlowFence';
    mathFlowFenceSequence: 'mathFlowFenceSequence';
    mathFlowValue: 'mathFlowValue';
    mathText: 'mathText';
    mathTextData: 'mathTextData';
    mathTextSequence: 'mathTextSequence';
  }
}

/** Registers a micromark syntax extension from inside a remark plugin. */
export function addMicromarkExtension(
  processor: Processor,
  extension: Extension,
): void {
  const data = processor.data() as { micromarkExtensions?: Extension[] };
  (data.micromarkExtensions ??= []).push(extension);
}
