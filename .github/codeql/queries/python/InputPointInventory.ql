/**
 * @name HTTP input point (inventory / whitelist check)
 * @description Marks every point where the application reads data from an
 *              incoming HTTP request (Flask request args/form/json/headers/
 *              files, flask-restx parsed fields, etc.). Use this list as the
 *              authoritative inventory of untrusted input surfaces: each new
 *              finding on a PR is a new input point that must be reviewed for
 *              validation / allow-listing before merge.
 * @kind problem
 * @problem.severity recommendation
 * @security-severity 1.0
 * @precision high
 * @id docsgpt/py/input-point-inventory
 * @tags security
 *       maintainability
 *       audit
 */

import python
import semmle.python.dataflow.new.RemoteFlowSources

from RemoteFlowSource src
select src,
  "HTTP input point (" + src.getSourceType() +
    "). Confirm this endpoint validates or allow-lists the value before use."
