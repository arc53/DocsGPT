/**
 * Shared definitions of "dangerous" dynamic-execution and unsafe-deserialization
 * sinks used by DocsGPT's custom CodeQL queries.
 *
 * NOTE ON THE SANDBOX: DocsGPT deliberately executes user-supplied code through
 * application/sandbox (manager.exec / backend.exec on Jupyter and Daytona
 * backends). Those are *method* calls named `exec` on project objects, not the
 * Python builtin `exec`, so the builtin-based matchers below never flag them.
 * That is intentional: the sandbox is the sanctioned execution boundary and
 * should not appear as noise here.
 */

import python
import semmle.python.ApiGraphs
import semmle.python.dataflow.new.DataFlow

/** A call to a builtin or stdlib function that can execute code or deserialize untrusted data. */
class DangerousCall extends API::CallNode {
  string kind;

  DangerousCall() {
    this = API::builtin("eval").getACall() and kind = "eval"
    or
    this = API::builtin("exec").getACall() and kind = "exec"
    or
    this = API::builtin("compile").getACall() and kind = "compile"
    or
    this = API::builtin("__import__").getACall() and kind = "__import__"
    or
    this = API::moduleImport("os").getMember("system").getACall() and kind = "os.system"
    or
    this =
      API::moduleImport("os")
          .getMember(["popen", "spawnl", "spawnv", "execl", "execv"])
          .getACall() and
    kind = "os.exec/spawn/popen"
    or
    this =
      API::moduleImport("subprocess")
          .getMember(["run", "call", "check_call", "check_output", "Popen"])
          .getACall() and
    kind = "subprocess"
    or
    this = API::moduleImport("pickle").getMember(["load", "loads"]).getACall() and
    kind = "pickle.load"
    or
    this = API::moduleImport("marshal").getMember(["load", "loads"]).getACall() and
    kind = "marshal.load"
    or
    // yaml.load with no explicit Loader uses the full loader and is unsafe
    // deserialization. When a Loader is passed (e.g. SafeLoader), safety is
    // loader-dependent, so we defer to security-extended's loader-aware
    // py/unsafe-deserialization query rather than flag it here.
    this = API::moduleImport("yaml").getMember("load").getACall() and
    not exists(this.getArgByName("Loader")) and
    not exists(this.getArg(1)) and
    kind = "yaml.load (no explicit Loader)"
  }

  /** A short human-readable name for the sink, e.g. "eval" or "subprocess". */
  string getKind() { result = kind }

  /** The primary user-controllable argument for this sink. */
  DataFlow::Node getSinkArgument() {
    // First positional argument for code/command sinks.
    result = this.getArg(0)
  }
}
