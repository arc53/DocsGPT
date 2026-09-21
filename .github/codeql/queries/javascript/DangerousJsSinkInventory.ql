/**
 * @name Dynamic code execution or unsafe HTML sink (inventory)
 * @description Lists frontend uses of eval(), the Function constructor (called
 *              or constructed), setTimeout/setInterval with a string body,
 *              document.write/writeln, insertAdjacentHTML, and React's
 *              dangerouslySetInnerHTML. These evaluate code or inject raw HTML
 *              and are common XSS / code-injection sinks; prefer parsed React
 *              elements (see MarkdownPreview.tsx) or JSON.parse instead.
 *              Reachability from untrusted data is covered by the
 *              security-extended suite; this query is the review inventory.
 * @kind problem
 * @problem.severity warning
 * @security-severity 6.1
 * @precision high
 * @id docsgpt/js/dangerous-sink-inventory
 * @tags security
 *       maintainability
 *       external/cwe/cwe-079
 *       external/cwe/cwe-094
 */

import javascript

from DataFlow::Node node, string kind
where
  node = DataFlow::globalVarRef("eval").getACall() and kind = "eval()"
  or
  // `new Function(body)` and `Function(body)` both compile a string into code.
  node = DataFlow::globalVarRef("Function").getAnInvocation() and kind = "Function() constructor"
  or
  exists(DataFlow::CallNode call |
    call = DataFlow::globalVarRef(["setTimeout", "setInterval"]).getACall() and
    call.getArgument(0).mayHaveStringValue(_) and
    node = call and
    kind = "setTimeout/setInterval with string body"
  )
  or
  exists(DataFlow::CallNode call |
    call = DataFlow::globalVarRef("document").getAMethodCall(["write", "writeln"]) and
    node = call and
    kind = "document.write()"
  )
  or
  exists(DataFlow::MethodCallNode call |
    call.getMethodName() = "insertAdjacentHTML" and
    node = call and
    kind = "insertAdjacentHTML()"
  )
  or
  exists(JsxAttribute attr |
    attr.getName() = "dangerouslySetInnerHTML" and
    node = attr.getValue().flow() and
    kind = "dangerouslySetInnerHTML"
  )
select node,
  "Dynamic/unsafe sink (" + kind +
    "). Review that any input reaching this is trusted or sanitized."
