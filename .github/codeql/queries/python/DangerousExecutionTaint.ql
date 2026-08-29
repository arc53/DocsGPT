/**
 * @name Untrusted HTTP input reaches a dangerous execution or deserialization sink
 * @description Data originating from an HTTP request (Flask request args/form/
 *              json/headers/files) flows to eval/exec/compile/os.system/
 *              subprocess/pickle/yaml.load. Such flows are prime candidates for
 *              remote code execution and should be removed or replaced with a
 *              safe alternative (e.g. the sandbox, ast.literal_eval, SafeLoader).
 * @kind path-problem
 * @problem.severity error
 * @security-severity 9.8
 * @precision high
 * @id docsgpt/py/tainted-dangerous-execution
 * @tags security
 *       external/cwe/cwe-078
 *       external/cwe/cwe-094
 *       external/cwe/cwe-502
 */

import python
import semmle.python.dataflow.new.DataFlow
import semmle.python.dataflow.new.TaintTracking
import semmle.python.dataflow.new.RemoteFlowSources
import DangerousSinks
import DangerousExecFlow::PathGraph

module DangerousExecConfig implements DataFlow::ConfigSig {
  predicate isSource(DataFlow::Node source) { source instanceof RemoteFlowSource }

  predicate isSink(DataFlow::Node sink) {
    exists(DangerousCall c | sink = c.getSinkArgument())
  }
}

module DangerousExecFlow = TaintTracking::Global<DangerousExecConfig>;

from DangerousExecFlow::PathNode source, DangerousExecFlow::PathNode sink
where DangerousExecFlow::flowPath(source, sink)
select sink.getNode(), source, sink,
  "Untrusted HTTP input from $@ reaches a dangerous execution/deserialization sink.",
  source.getNode(), "a user request"
