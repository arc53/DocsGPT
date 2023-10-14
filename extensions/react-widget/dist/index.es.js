import Ne, { useState as ke, useRef as ur, useEffect as Pe } from "react";
var ne = { exports: {} }, Y = {};
/**
 * @license React
 * react-jsx-runtime.production.min.js
 *
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
var Ce;
function cr() {
  if (Ce)
    return Y;
  Ce = 1;
  var N = Ne, w = Symbol.for("react.element"), C = Symbol.for("react.fragment"), u = Object.prototype.hasOwnProperty, E = N.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentOwner, S = { key: !0, ref: !0, __self: !0, __source: !0 };
  function T(b, d, v) {
    var m, h = {}, x = null, p = null;
    v !== void 0 && (x = "" + v), d.key !== void 0 && (x = "" + d.key), d.ref !== void 0 && (p = d.ref);
    for (m in d)
      u.call(d, m) && !S.hasOwnProperty(m) && (h[m] = d[m]);
    if (b && b.defaultProps)
      for (m in d = b.defaultProps, d)
        h[m] === void 0 && (h[m] = d[m]);
    return { $$typeof: w, type: b, key: x, ref: p, props: h, _owner: E.current };
  }
  return Y.Fragment = C, Y.jsx = T, Y.jsxs = T, Y;
}
var L = {};
/**
 * @license React
 * react-jsx-runtime.development.js
 *
 * Copyright (c) Facebook, Inc. and its affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */
var Oe;
function fr() {
  return Oe || (Oe = 1, process.env.NODE_ENV !== "production" && function() {
    var N = Ne, w = Symbol.for("react.element"), C = Symbol.for("react.portal"), u = Symbol.for("react.fragment"), E = Symbol.for("react.strict_mode"), S = Symbol.for("react.profiler"), T = Symbol.for("react.provider"), b = Symbol.for("react.context"), d = Symbol.for("react.forward_ref"), v = Symbol.for("react.suspense"), m = Symbol.for("react.suspense_list"), h = Symbol.for("react.memo"), x = Symbol.for("react.lazy"), p = Symbol.for("react.offscreen"), R = Symbol.iterator, j = "@@iterator";
    function J(e) {
      if (e === null || typeof e != "object")
        return null;
      var r = R && e[R] || e[j];
      return typeof r == "function" ? r : null;
    }
    var O = N.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;
    function g(e) {
      {
        for (var r = arguments.length, t = new Array(r > 1 ? r - 1 : 0), n = 1; n < r; n++)
          t[n - 1] = arguments[n];
        B("error", e, t);
      }
    }
    function B(e, r, t) {
      {
        var n = O.ReactDebugCurrentFrame, o = n.getStackAddendum();
        o !== "" && (r += "%s", t = t.concat([o]));
        var s = t.map(function(i) {
          return String(i);
        });
        s.unshift("Warning: " + r), Function.prototype.apply.call(console[e], console, s);
      }
    }
    var D = !1, z = !1, De = !1, Ae = !1, Fe = !1, ae;
    ae = Symbol.for("react.module.reference");
    function Ie(e) {
      return !!(typeof e == "string" || typeof e == "function" || e === u || e === S || Fe || e === E || e === v || e === m || Ae || e === p || D || z || De || typeof e == "object" && e !== null && (e.$$typeof === x || e.$$typeof === h || e.$$typeof === T || e.$$typeof === b || e.$$typeof === d || // This needs to include all possible module reference object
      // types supported by any Flight configuration anywhere since
      // we don't know which Flight build this will end up being used
      // with.
      e.$$typeof === ae || e.getModuleId !== void 0));
    }
    function $e(e, r, t) {
      var n = e.displayName;
      if (n)
        return n;
      var o = r.displayName || r.name || "";
      return o !== "" ? t + "(" + o + ")" : t;
    }
    function ie(e) {
      return e.displayName || "Context";
    }
    function k(e) {
      if (e == null)
        return null;
      if (typeof e.tag == "number" && g("Received an unexpected object in getComponentNameFromType(). This is likely a bug in React. Please file an issue."), typeof e == "function")
        return e.displayName || e.name || null;
      if (typeof e == "string")
        return e;
      switch (e) {
        case u:
          return "Fragment";
        case C:
          return "Portal";
        case S:
          return "Profiler";
        case E:
          return "StrictMode";
        case v:
          return "Suspense";
        case m:
          return "SuspenseList";
      }
      if (typeof e == "object")
        switch (e.$$typeof) {
          case b:
            var r = e;
            return ie(r) + ".Consumer";
          case T:
            var t = e;
            return ie(t._context) + ".Provider";
          case d:
            return $e(e, e.render, "ForwardRef");
          case h:
            var n = e.displayName || null;
            return n !== null ? n : k(e.type) || "Memo";
          case x: {
            var o = e, s = o._payload, i = o._init;
            try {
              return k(i(s));
            } catch {
              return null;
            }
          }
        }
      return null;
    }
    var A = Object.assign, $ = 0, oe, se, le, ue, ce, fe, de;
    function ve() {
    }
    ve.__reactDisabledLog = !0;
    function We() {
      {
        if ($ === 0) {
          oe = console.log, se = console.info, le = console.warn, ue = console.error, ce = console.group, fe = console.groupCollapsed, de = console.groupEnd;
          var e = {
            configurable: !0,
            enumerable: !0,
            value: ve,
            writable: !0
          };
          Object.defineProperties(console, {
            info: e,
            log: e,
            warn: e,
            error: e,
            group: e,
            groupCollapsed: e,
            groupEnd: e
          });
        }
        $++;
      }
    }
    function Ye() {
      {
        if ($--, $ === 0) {
          var e = {
            configurable: !0,
            enumerable: !0,
            writable: !0
          };
          Object.defineProperties(console, {
            log: A({}, e, {
              value: oe
            }),
            info: A({}, e, {
              value: se
            }),
            warn: A({}, e, {
              value: le
            }),
            error: A({}, e, {
              value: ue
            }),
            group: A({}, e, {
              value: ce
            }),
            groupCollapsed: A({}, e, {
              value: fe
            }),
            groupEnd: A({}, e, {
              value: de
            })
          });
        }
        $ < 0 && g("disabledDepth fell below zero. This is a bug in React. Please file an issue.");
      }
    }
    var H = O.ReactCurrentDispatcher, K;
    function V(e, r, t) {
      {
        if (K === void 0)
          try {
            throw Error();
          } catch (o) {
            var n = o.stack.trim().match(/\n( *(at )?)/);
            K = n && n[1] || "";
          }
        return `
` + K + e;
      }
    }
    var X = !1, M;
    {
      var Le = typeof WeakMap == "function" ? WeakMap : Map;
      M = new Le();
    }
    function pe(e, r) {
      if (!e || X)
        return "";
      {
        var t = M.get(e);
        if (t !== void 0)
          return t;
      }
      var n;
      X = !0;
      var o = Error.prepareStackTrace;
      Error.prepareStackTrace = void 0;
      var s;
      s = H.current, H.current = null, We();
      try {
        if (r) {
          var i = function() {
            throw Error();
          };
          if (Object.defineProperty(i.prototype, "props", {
            set: function() {
              throw Error();
            }
          }), typeof Reflect == "object" && Reflect.construct) {
            try {
              Reflect.construct(i, []);
            } catch (P) {
              n = P;
            }
            Reflect.construct(e, [], i);
          } else {
            try {
              i.call();
            } catch (P) {
              n = P;
            }
            e.call(i.prototype);
          }
        } else {
          try {
            throw Error();
          } catch (P) {
            n = P;
          }
          e();
        }
      } catch (P) {
        if (P && n && typeof P.stack == "string") {
          for (var a = P.stack.split(`
`), y = n.stack.split(`
`), c = a.length - 1, f = y.length - 1; c >= 1 && f >= 0 && a[c] !== y[f]; )
            f--;
          for (; c >= 1 && f >= 0; c--, f--)
            if (a[c] !== y[f]) {
              if (c !== 1 || f !== 1)
                do
                  if (c--, f--, f < 0 || a[c] !== y[f]) {
                    var _ = `
` + a[c].replace(" at new ", " at ");
                    return e.displayName && _.includes("<anonymous>") && (_ = _.replace("<anonymous>", e.displayName)), typeof e == "function" && M.set(e, _), _;
                  }
                while (c >= 1 && f >= 0);
              break;
            }
        }
      } finally {
        X = !1, H.current = s, Ye(), Error.prepareStackTrace = o;
      }
      var I = e ? e.displayName || e.name : "", je = I ? V(I) : "";
      return typeof e == "function" && M.set(e, je), je;
    }
    function Ve(e, r, t) {
      return pe(e, !1);
    }
    function Me(e) {
      var r = e.prototype;
      return !!(r && r.isReactComponent);
    }
    function U(e, r, t) {
      if (e == null)
        return "";
      if (typeof e == "function")
        return pe(e, Me(e));
      if (typeof e == "string")
        return V(e);
      switch (e) {
        case v:
          return V("Suspense");
        case m:
          return V("SuspenseList");
      }
      if (typeof e == "object")
        switch (e.$$typeof) {
          case d:
            return Ve(e.render);
          case h:
            return U(e.type, r, t);
          case x: {
            var n = e, o = n._payload, s = n._init;
            try {
              return U(s(o), r, t);
            } catch {
            }
          }
        }
      return "";
    }
    var G = Object.prototype.hasOwnProperty, he = {}, me = O.ReactDebugCurrentFrame;
    function q(e) {
      if (e) {
        var r = e._owner, t = U(e.type, e._source, r ? r.type : null);
        me.setExtraStackFrame(t);
      } else
        me.setExtraStackFrame(null);
    }
    function Ue(e, r, t, n, o) {
      {
        var s = Function.call.bind(G);
        for (var i in e)
          if (s(e, i)) {
            var a = void 0;
            try {
              if (typeof e[i] != "function") {
                var y = Error((n || "React class") + ": " + t + " type `" + i + "` is invalid; it must be a function, usually from the `prop-types` package, but received `" + typeof e[i] + "`.This often happens because of typos such as `PropTypes.function` instead of `PropTypes.func`.");
                throw y.name = "Invariant Violation", y;
              }
              a = e[i](r, i, n, t, null, "SECRET_DO_NOT_PASS_THIS_OR_YOU_WILL_BE_FIRED");
            } catch (c) {
              a = c;
            }
            a && !(a instanceof Error) && (q(o), g("%s: type specification of %s `%s` is invalid; the type checker function must return `null` or an `Error` but returned a %s. You may have forgotten to pass an argument to the type checker creator (arrayOf, instanceOf, objectOf, oneOf, oneOfType, and shape all require an argument).", n || "React class", t, i, typeof a), q(null)), a instanceof Error && !(a.message in he) && (he[a.message] = !0, q(o), g("Failed %s type: %s", t, a.message), q(null));
          }
      }
    }
    var Ge = Array.isArray;
    function Z(e) {
      return Ge(e);
    }
    function qe(e) {
      {
        var r = typeof Symbol == "function" && Symbol.toStringTag, t = r && e[Symbol.toStringTag] || e.constructor.name || "Object";
        return t;
      }
    }
    function Je(e) {
      try {
        return ge(e), !1;
      } catch {
        return !0;
      }
    }
    function ge(e) {
      return "" + e;
    }
    function ye(e) {
      if (Je(e))
        return g("The provided key is an unsupported type %s. This value must be coerced to a string before using it here.", qe(e)), ge(e);
    }
    var W = O.ReactCurrentOwner, Be = {
      key: !0,
      ref: !0,
      __self: !0,
      __source: !0
    }, be, Ee, Q;
    Q = {};
    function ze(e) {
      if (G.call(e, "ref")) {
        var r = Object.getOwnPropertyDescriptor(e, "ref").get;
        if (r && r.isReactWarning)
          return !1;
      }
      return e.ref !== void 0;
    }
    function He(e) {
      if (G.call(e, "key")) {
        var r = Object.getOwnPropertyDescriptor(e, "key").get;
        if (r && r.isReactWarning)
          return !1;
      }
      return e.key !== void 0;
    }
    function Ke(e, r) {
      if (typeof e.ref == "string" && W.current && r && W.current.stateNode !== r) {
        var t = k(W.current.type);
        Q[t] || (g('Component "%s" contains the string ref "%s". Support for string refs will be removed in a future major release. This case cannot be automatically converted to an arrow function. We ask you to manually fix this case by using useRef() or createRef() instead. Learn more about using refs safely here: https://reactjs.org/link/strict-mode-string-ref', k(W.current.type), e.ref), Q[t] = !0);
      }
    }
    function Xe(e, r) {
      {
        var t = function() {
          be || (be = !0, g("%s: `key` is not a prop. Trying to access it will result in `undefined` being returned. If you need to access the same value within the child component, you should pass it as a different prop. (https://reactjs.org/link/special-props)", r));
        };
        t.isReactWarning = !0, Object.defineProperty(e, "key", {
          get: t,
          configurable: !0
        });
      }
    }
    function Ze(e, r) {
      {
        var t = function() {
          Ee || (Ee = !0, g("%s: `ref` is not a prop. Trying to access it will result in `undefined` being returned. If you need to access the same value within the child component, you should pass it as a different prop. (https://reactjs.org/link/special-props)", r));
        };
        t.isReactWarning = !0, Object.defineProperty(e, "ref", {
          get: t,
          configurable: !0
        });
      }
    }
    var Qe = function(e, r, t, n, o, s, i) {
      var a = {
        // This tag allows us to uniquely identify this as a React Element
        $$typeof: w,
        // Built-in properties that belong on the element
        type: e,
        key: r,
        ref: t,
        props: i,
        // Record the component responsible for creating this element.
        _owner: s
      };
      return a._store = {}, Object.defineProperty(a._store, "validated", {
        configurable: !1,
        enumerable: !1,
        writable: !0,
        value: !1
      }), Object.defineProperty(a, "_self", {
        configurable: !1,
        enumerable: !1,
        writable: !1,
        value: n
      }), Object.defineProperty(a, "_source", {
        configurable: !1,
        enumerable: !1,
        writable: !1,
        value: o
      }), Object.freeze && (Object.freeze(a.props), Object.freeze(a)), a;
    };
    function er(e, r, t, n, o) {
      {
        var s, i = {}, a = null, y = null;
        t !== void 0 && (ye(t), a = "" + t), He(r) && (ye(r.key), a = "" + r.key), ze(r) && (y = r.ref, Ke(r, o));
        for (s in r)
          G.call(r, s) && !Be.hasOwnProperty(s) && (i[s] = r[s]);
        if (e && e.defaultProps) {
          var c = e.defaultProps;
          for (s in c)
            i[s] === void 0 && (i[s] = c[s]);
        }
        if (a || y) {
          var f = typeof e == "function" ? e.displayName || e.name || "Unknown" : e;
          a && Xe(i, f), y && Ze(i, f);
        }
        return Qe(e, a, y, o, n, W.current, i);
      }
    }
    var ee = O.ReactCurrentOwner, xe = O.ReactDebugCurrentFrame;
    function F(e) {
      if (e) {
        var r = e._owner, t = U(e.type, e._source, r ? r.type : null);
        xe.setExtraStackFrame(t);
      } else
        xe.setExtraStackFrame(null);
    }
    var re;
    re = !1;
    function te(e) {
      return typeof e == "object" && e !== null && e.$$typeof === w;
    }
    function _e() {
      {
        if (ee.current) {
          var e = k(ee.current.type);
          if (e)
            return `

Check the render method of \`` + e + "`.";
        }
        return "";
      }
    }
    function rr(e) {
      {
        if (e !== void 0) {
          var r = e.fileName.replace(/^.*[\\\/]/, ""), t = e.lineNumber;
          return `

Check your code at ` + r + ":" + t + ".";
        }
        return "";
      }
    }
    var Re = {};
    function tr(e) {
      {
        var r = _e();
        if (!r) {
          var t = typeof e == "string" ? e : e.displayName || e.name;
          t && (r = `

Check the top-level render call using <` + t + ">.");
        }
        return r;
      }
    }
    function we(e, r) {
      {
        if (!e._store || e._store.validated || e.key != null)
          return;
        e._store.validated = !0;
        var t = tr(r);
        if (Re[t])
          return;
        Re[t] = !0;
        var n = "";
        e && e._owner && e._owner !== ee.current && (n = " It was passed a child from " + k(e._owner.type) + "."), F(e), g('Each child in a list should have a unique "key" prop.%s%s See https://reactjs.org/link/warning-keys for more information.', t, n), F(null);
      }
    }
    function Te(e, r) {
      {
        if (typeof e != "object")
          return;
        if (Z(e))
          for (var t = 0; t < e.length; t++) {
            var n = e[t];
            te(n) && we(n, r);
          }
        else if (te(e))
          e._store && (e._store.validated = !0);
        else if (e) {
          var o = J(e);
          if (typeof o == "function" && o !== e.entries)
            for (var s = o.call(e), i; !(i = s.next()).done; )
              te(i.value) && we(i.value, r);
        }
      }
    }
    function nr(e) {
      {
        var r = e.type;
        if (r == null || typeof r == "string")
          return;
        var t;
        if (typeof r == "function")
          t = r.propTypes;
        else if (typeof r == "object" && (r.$$typeof === d || // Note: Memo only checks outer props here.
        // Inner props are checked in the reconciler.
        r.$$typeof === h))
          t = r.propTypes;
        else
          return;
        if (t) {
          var n = k(r);
          Ue(t, e.props, "prop", n, e);
        } else if (r.PropTypes !== void 0 && !re) {
          re = !0;
          var o = k(r);
          g("Component %s declared `PropTypes` instead of `propTypes`. Did you misspell the property assignment?", o || "Unknown");
        }
        typeof r.getDefaultProps == "function" && !r.getDefaultProps.isReactClassApproved && g("getDefaultProps is only used on classic React.createClass definitions. Use a static property named `defaultProps` instead.");
      }
    }
    function ar(e) {
      {
        for (var r = Object.keys(e.props), t = 0; t < r.length; t++) {
          var n = r[t];
          if (n !== "children" && n !== "key") {
            F(e), g("Invalid prop `%s` supplied to `React.Fragment`. React.Fragment can only have `key` and `children` props.", n), F(null);
            break;
          }
        }
        e.ref !== null && (F(e), g("Invalid attribute `ref` supplied to `React.Fragment`."), F(null));
      }
    }
    function Se(e, r, t, n, o, s) {
      {
        var i = Ie(e);
        if (!i) {
          var a = "";
          (e === void 0 || typeof e == "object" && e !== null && Object.keys(e).length === 0) && (a += " You likely forgot to export your component from the file it's defined in, or you might have mixed up default and named imports.");
          var y = rr(o);
          y ? a += y : a += _e();
          var c;
          e === null ? c = "null" : Z(e) ? c = "array" : e !== void 0 && e.$$typeof === w ? (c = "<" + (k(e.type) || "Unknown") + " />", a = " Did you accidentally export a JSX literal instead of a component?") : c = typeof e, g("React.jsx: type is invalid -- expected a string (for built-in components) or a class/function (for composite components) but got: %s.%s", c, a);
        }
        var f = er(e, r, t, o, s);
        if (f == null)
          return f;
        if (i) {
          var _ = r.children;
          if (_ !== void 0)
            if (n)
              if (Z(_)) {
                for (var I = 0; I < _.length; I++)
                  Te(_[I], e);
                Object.freeze && Object.freeze(_);
              } else
                g("React.jsx: Static children should always be an array. You are likely explicitly calling React.jsxs or React.jsxDEV. Use the Babel transform instead.");
            else
              Te(_, e);
        }
        return e === u ? ar(f) : nr(f), f;
      }
    }
    function ir(e, r, t) {
      return Se(e, r, t, !0);
    }
    function or(e, r, t) {
      return Se(e, r, t, !1);
    }
    var sr = or, lr = ir;
    L.Fragment = u, L.jsx = sr, L.jsxs = lr;
  }()), L;
}
process.env.NODE_ENV === "production" ? ne.exports = cr() : ne.exports = fr();
var l = ne.exports;
function dr({
  question: N = "",
  apiKey: w = "",
  selectedDocs: C = "",
  history: u = [],
  conversationId: E = null,
  apiHost: S = "",
  onEvent: T = () => {
    console.log("Event triggered, but no handler provided.");
  }
}) {
  let b = "default";
  return C && (b = C), new Promise((d, v) => {
    const m = {
      question: N,
      api_key: w,
      embeddings_key: w,
      active_docs: b,
      history: JSON.stringify(u),
      conversation_id: E,
      model: "default"
    };
    fetch(S + "/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(m)
    }).then((h) => {
      if (!h.body)
        throw Error("No response body");
      const x = h.body.getReader(), p = new TextDecoder("utf-8");
      let R = 0;
      const j = ({
        done: J,
        value: O
      }) => {
        if (J) {
          console.log(R), d();
          return;
        }
        R += 1;
        const B = p.decode(O).split(`
`);
        for (let D of B) {
          if (D.trim() == "")
            continue;
          D.startsWith("data:") && (D = D.substring(5));
          const z = new MessageEvent("message", {
            data: D
          });
          T(z);
        }
        x.read().then(j).catch(v);
      };
      x.read().then(j).catch(v);
    }).catch((h) => {
      console.error("Connection failed:", h), v(h);
    });
  });
}
const pr = ({ apiHost: N = "https://gptcloud.arc53.com", selectDocs: w = "default", apiKey: C = "docsgpt-public" }) => {
  const [u, E] = ke(() => typeof window < "u" && localStorage.getItem("docsGPTChatState") || "init"), [S, T] = ke(""), b = ur(null);
  Pe(() => {
    if (b.current) {
      const v = b.current;
      v.scrollTop = v.scrollHeight;
    }
  }, [S]), Pe(() => {
    localStorage.setItem("docsGPTChatState", u);
  }, [u]);
  const d = (v) => {
    T(""), v.preventDefault(), E(
      "processing"
      /* Processing */
    ), setTimeout(() => {
      E(
        "answer"
        /* Answer */
      );
    }, 800);
    const h = v.currentTarget[0].value;
    dr({
      question: h,
      apiKey: C,
      selectedDocs: w,
      history: [],
      conversationId: null,
      apiHost: N,
      onEvent: (x) => {
        const p = JSON.parse(x.data);
        if (p.type === "end")
          E(
            "answer"
            /* Answer */
          );
        else if (p.type === "source") {
          let R;
          if (p.metadata && p.metadata.title) {
            const j = p.metadata.title.split("/");
            R = {
              title: j[j.length - 1],
              text: p.doc
            };
          } else
            R = { title: p.doc, text: p.doc };
          console.log(R);
        } else if (p.type === "id")
          console.log(p.id);
        else {
          const R = p.answer;
          T((j) => j + R);
        }
      }
    });
  };
  return /* @__PURE__ */ l.jsx(l.Fragment, { children: /* @__PURE__ */ l.jsxs("div", { className: "dark widget-container", children: [
    /* @__PURE__ */ l.jsx(
      "div",
      {
        onClick: () => E(
          "init"
          /* Init */
        ),
        className: `${u !== "minimized" ? "hidden" : ""} cursor-pointer`,
        children: /* @__PURE__ */ l.jsx("div", { className: "mr-2 mb-2 w-20 h-20 rounded-full overflow-hidden dark:divide-gray-700 border dark:border-gray-700 bg-gradient-to-br from-gray-100/80 via-white to-white dark:from-gray-900/80 dark:via-gray-900 dark:to-gray-900 font-sans shadow backdrop-blur-sm flex items-center justify-center", children: /* @__PURE__ */ l.jsx(
          "img",
          {
            src: "https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png",
            alt: "DocsGPT",
            className: "cursor-pointer hover:opacity-50 h-14"
          }
        ) })
      }
    ),
    /* @__PURE__ */ l.jsxs("div", { className: ` ${u !== "minimized" ? "" : "hidden"} divide-y dark:divide-gray-700 rounded-md border dark:border-gray-700 bg-gradient-to-br from-gray-100/80 via-white to-white dark:from-gray-900/80 dark:via-gray-900 dark:to-gray-900 font-sans shadow backdrop-blur-sm`, style: { width: "18rem", transform: "translateY(0%) translateZ(0px)" }, children: [
      /* @__PURE__ */ l.jsxs("div", { children: [
        /* @__PURE__ */ l.jsx(
          "img",
          {
            src: "https://d3dg1063dc54p9.cloudfront.net/exit.svg",
            alt: "Exit",
            className: "cursor-pointer hover:opacity-50 h-2 absolute top-0 right-0 m-2 white-filter",
            onClick: (v) => {
              v.stopPropagation(), E(
                "minimized"
                /* Minimized */
              );
            }
          }
        ),
        /* @__PURE__ */ l.jsxs("div", { className: "flex items-center gap-2 p-3", children: [
          /* @__PURE__ */ l.jsxs("div", { className: `${u === "init" || u === "processing" || u === "typing" ? "" : "hidden"} flex-1`, children: [
            /* @__PURE__ */ l.jsx("h3", { className: "text-sm font-bold text-gray-700 dark:text-gray-200", children: "Need help with documentation?" }),
            /* @__PURE__ */ l.jsx("p", { className: "mt-1 text-xs text-gray-400 dark:text-gray-500", children: "DocsGPT AI assistant will help you with docs" })
          ] }),
          /* @__PURE__ */ l.jsx("div", { id: "docsgpt-answer", ref: b, className: `${u !== "answer" ? "hidden" : ""}`, children: /* @__PURE__ */ l.jsx("p", { className: "mt-1 text-sm text-gray-600 dark:text-white text-left", children: S }) })
        ] })
      ] }),
      /* @__PURE__ */ l.jsxs("div", { className: "w-full", children: [
        /* @__PURE__ */ l.jsx(
          "button",
          {
            onClick: () => E(
              "typing"
              /* Typing */
            ),
            className: `flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 hover:bg-gray-100 rounded-b dark:hover:bg-gray-800/70 ${u !== "init" ? "hidden" : ""}`,
            children: "Ask DocsGPT"
          }
        ),
        (u === "typing" || u === "answer") && /* @__PURE__ */ l.jsxs(
          "form",
          {
            onSubmit: d,
            className: "relative w-full m-0",
            style: { opacity: 1 },
            children: [
              /* @__PURE__ */ l.jsx(
                "input",
                {
                  type: "text",
                  className: "w-full bg-transparent px-5 py-3 pr-8 text-sm text-gray-700 dark:text-white focus:outline-none",
                  placeholder: "What do you want to do?"
                }
              ),
              /* @__PURE__ */ l.jsx("button", { className: "absolute text-gray-400 dark:text-gray-500 text-sm inset-y-0 right-2 -mx-2 px-2", type: "submit", children: "Submit" })
            ]
          }
        ),
        /* @__PURE__ */ l.jsxs("p", { className: `${u !== "processing" ? "hidden" : ""} flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 rounded-b`, children: [
          "Processing",
          /* @__PURE__ */ l.jsx("span", { className: "dot-animation", children: "." }),
          /* @__PURE__ */ l.jsx("span", { className: "dot-animation delay-200", children: "." }),
          /* @__PURE__ */ l.jsx("span", { className: "dot-animation delay-400", children: "." })
        ] })
      ] })
    ] })
  ] }) });
};
export {
  pr as DocsGPTWidget
};
//# sourceMappingURL=index.es.js.map
