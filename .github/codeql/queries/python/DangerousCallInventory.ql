/**
 * @name Dangerous dynamic-execution or deserialization call (inventory)
 * @description Lists every call to eval/exec/compile/__import__/os.system/
 *              subprocess/pickle/marshal/yaml.load so each can be reviewed and,
 *              where possible, replaced with a safer construct. This is an audit
 *              inventory, not a reachability finding: a listed call is not
 *              necessarily exploitable. Reachable-from-HTTP cases are reported
 *              separately (and at higher severity) by
 *              DangerousExecutionTaint.ql.
 * @kind problem
 * @problem.severity recommendation
 * @security-severity 2.0
 * @precision high
 * @id docsgpt/py/dangerous-call-inventory
 * @tags security
 *       maintainability
 *       external/cwe/cwe-094
 */

import python
import DangerousSinks

from DangerousCall call
select call,
  "Dangerous call to '" + call.getKind() +
    "'. Review whether the argument is fully trusted; prefer a safe alternative " +
    "(sandbox, ast.literal_eval, yaml.safe_load, a fixed argv list)."
