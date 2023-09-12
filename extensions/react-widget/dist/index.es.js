import Ce, { useState as Se, useRef as lr, useEffect as ur } from "react";
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
var Pe;
function cr() {
  if (Pe)
    return Y;
  Pe = 1;
  var D = Ce, w = Symbol.for("react.element"), O = Symbol.for("react.fragment"), f = Object.prototype.hasOwnProperty, E = D.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentOwner, j = { key: !0, ref: !0, __self: !0, __source: !0 };
  function T(b, d, v) {
    var m, h = {}, x = null, p = null;
    v !== void 0 && (x = "" + v), d.key !== void 0 && (x = "" + d.key), d.ref !== void 0 && (p = d.ref);
    for (m in d)
      f.call(d, m) && !j.hasOwnProperty(m) && (h[m] = d[m]);
    if (b && b.defaultProps)
      for (m in d = b.defaultProps, d)
        h[m] === void 0 && (h[m] = d[m]);
    return { $$typeof: w, type: b, key: x, ref: p, props: h, _owner: E.current };
  }
  return Y.Fragment = O, Y.jsx = T, Y.jsxs = T, Y;
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
    var D = Ce, w = Symbol.for("react.element"), O = Symbol.for("react.portal"), f = Symbol.for("react.fragment"), E = Symbol.for("react.strict_mode"), j = Symbol.for("react.profiler"), T = Symbol.for("react.provider"), b = Symbol.for("react.context"), d = Symbol.for("react.forward_ref"), v = Symbol.for("react.suspense"), m = Symbol.for("react.suspense_list"), h = Symbol.for("react.memo"), x = Symbol.for("react.lazy"), p = Symbol.for("react.offscreen"), R = Symbol.iterator, k = "@@iterator";
    function J(e) {
      if (e === null || typeof e != "object")
        return null;
      var r = R && e[R] || e[k];
      return typeof r == "function" ? r : null;
    }
    var C = D.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;
    function g(e) {
      {
        for (var r = arguments.length, t = new Array(r > 1 ? r - 1 : 0), n = 1; n < r; n++)
          t[n - 1] = arguments[n];
        B("error", e, t);
      }
    }
    function B(e, r, t) {
      {
        var n = C.ReactDebugCurrentFrame, o = n.getStackAddendum();
        o !== "" && (r += "%s", t = t.concat([o]));
        var s = t.map(function(i) {
          return String(i);
        });
        s.unshift("Warning: " + r), Function.prototype.apply.call(console[e], console, s);
      }
    }
    var N = !1, z = !1, De = !1, Ne = !1, Ae = !1, ae;
    ae = Symbol.for("react.module.reference");
    function Fe(e) {
      return !!(typeof e == "string" || typeof e == "function" || e === f || e === j || Ae || e === E || e === v || e === m || Ne || e === p || N || z || De || typeof e == "object" && e !== null && (e.$$typeof === x || e.$$typeof === h || e.$$typeof === T || e.$$typeof === b || e.$$typeof === d || // This needs to include all possible module reference object
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
    function S(e) {
      if (e == null)
        return null;
      if (typeof e.tag == "number" && g("Received an unexpected object in getComponentNameFromType(). This is likely a bug in React. Please file an issue."), typeof e == "function")
        return e.displayName || e.name || null;
      if (typeof e == "string")
        return e;
      switch (e) {
        case f:
          return "Fragment";
        case O:
          return "Portal";
        case j:
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
            return n !== null ? n : S(e.type) || "Memo";
          case x: {
            var o = e, s = o._payload, i = o._init;
            try {
              return S(i(s));
            } catch {
              return null;
            }
          }
        }
      return null;
    }
    var A = Object.assign, I = 0, oe, se, le, ue, ce, fe, de;
    function ve() {
    }
    ve.__reactDisabledLog = !0;
    function Ie() {
      {
        if (I === 0) {
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
        I++;
      }
    }
    function We() {
      {
        if (I--, I === 0) {
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
        I < 0 && g("disabledDepth fell below zero. This is a bug in React. Please file an issue.");
      }
    }
    var H = C.ReactCurrentDispatcher, K;
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
      var Ye = typeof WeakMap == "function" ? WeakMap : Map;
      M = new Ye();
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
      s = H.current, H.current = null, Ie();
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
`), u = a.length - 1, c = y.length - 1; u >= 1 && c >= 0 && a[u] !== y[c]; )
            c--;
          for (; u >= 1 && c >= 0; u--, c--)
            if (a[u] !== y[c]) {
              if (u !== 1 || c !== 1)
                do
                  if (u--, c--, c < 0 || a[u] !== y[c]) {
                    var _ = `
` + a[u].replace(" at new ", " at ");
                    return e.displayName && _.includes("<anonymous>") && (_ = _.replace("<anonymous>", e.displayName)), typeof e == "function" && M.set(e, _), _;
                  }
                while (u >= 1 && c >= 0);
              break;
            }
        }
      } finally {
        X = !1, H.current = s, We(), Error.prepareStackTrace = o;
      }
      var $ = e ? e.displayName || e.name : "", ke = $ ? V($) : "";
      return typeof e == "function" && M.set(e, ke), ke;
    }
    function Le(e, r, t) {
      return pe(e, !1);
    }
    function Ve(e) {
      var r = e.prototype;
      return !!(r && r.isReactComponent);
    }
    function U(e, r, t) {
      if (e == null)
        return "";
      if (typeof e == "function")
        return pe(e, Ve(e));
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
            return Le(e.render);
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
    var q = Object.prototype.hasOwnProperty, he = {}, me = C.ReactDebugCurrentFrame;
    function G(e) {
      if (e) {
        var r = e._owner, t = U(e.type, e._source, r ? r.type : null);
        me.setExtraStackFrame(t);
      } else
        me.setExtraStackFrame(null);
    }
    function Me(e, r, t, n, o) {
      {
        var s = Function.call.bind(q);
        for (var i in e)
          if (s(e, i)) {
            var a = void 0;
            try {
              if (typeof e[i] != "function") {
                var y = Error((n || "React class") + ": " + t + " type `" + i + "` is invalid; it must be a function, usually from the `prop-types` package, but received `" + typeof e[i] + "`.This often happens because of typos such as `PropTypes.function` instead of `PropTypes.func`.");
                throw y.name = "Invariant Violation", y;
              }
              a = e[i](r, i, n, t, null, "SECRET_DO_NOT_PASS_THIS_OR_YOU_WILL_BE_FIRED");
            } catch (u) {
              a = u;
            }
            a && !(a instanceof Error) && (G(o), g("%s: type specification of %s `%s` is invalid; the type checker function must return `null` or an `Error` but returned a %s. You may have forgotten to pass an argument to the type checker creator (arrayOf, instanceOf, objectOf, oneOf, oneOfType, and shape all require an argument).", n || "React class", t, i, typeof a), G(null)), a instanceof Error && !(a.message in he) && (he[a.message] = !0, G(o), g("Failed %s type: %s", t, a.message), G(null));
          }
      }
    }
    var Ue = Array.isArray;
    function Z(e) {
      return Ue(e);
    }
    function qe(e) {
      {
        var r = typeof Symbol == "function" && Symbol.toStringTag, t = r && e[Symbol.toStringTag] || e.constructor.name || "Object";
        return t;
      }
    }
    function Ge(e) {
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
      if (Ge(e))
        return g("The provided key is an unsupported type %s. This value must be coerced to a string before before using it here.", qe(e)), ge(e);
    }
    var W = C.ReactCurrentOwner, Je = {
      key: !0,
      ref: !0,
      __self: !0,
      __source: !0
    }, be, Ee, Q;
    Q = {};
    function Be(e) {
      if (q.call(e, "ref")) {
        var r = Object.getOwnPropertyDescriptor(e, "ref").get;
        if (r && r.isReactWarning)
          return !1;
      }
      return e.ref !== void 0;
    }
    function ze(e) {
      if (q.call(e, "key")) {
        var r = Object.getOwnPropertyDescriptor(e, "key").get;
        if (r && r.isReactWarning)
          return !1;
      }
      return e.key !== void 0;
    }
    function He(e, r) {
      if (typeof e.ref == "string" && W.current && r && W.current.stateNode !== r) {
        var t = S(W.current.type);
        Q[t] || (g('Component "%s" contains the string ref "%s". Support for string refs will be removed in a future major release. This case cannot be automatically converted to an arrow function. We ask you to manually fix this case by using useRef() or createRef() instead. Learn more about using refs safely here: https://reactjs.org/link/strict-mode-string-ref', S(W.current.type), e.ref), Q[t] = !0);
      }
    }
    function Ke(e, r) {
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
    function Xe(e, r) {
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
    var Ze = function(e, r, t, n, o, s, i) {
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
    function Qe(e, r, t, n, o) {
      {
        var s, i = {}, a = null, y = null;
        t !== void 0 && (ye(t), a = "" + t), ze(r) && (ye(r.key), a = "" + r.key), Be(r) && (y = r.ref, He(r, o));
        for (s in r)
          q.call(r, s) && !Je.hasOwnProperty(s) && (i[s] = r[s]);
        if (e && e.defaultProps) {
          var u = e.defaultProps;
          for (s in u)
            i[s] === void 0 && (i[s] = u[s]);
        }
        if (a || y) {
          var c = typeof e == "function" ? e.displayName || e.name || "Unknown" : e;
          a && Ke(i, c), y && Xe(i, c);
        }
        return Ze(e, a, y, o, n, W.current, i);
      }
    }
    var ee = C.ReactCurrentOwner, xe = C.ReactDebugCurrentFrame;
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
          var e = S(ee.current.type);
          if (e)
            return `

Check the render method of \`` + e + "`.";
        }
        return "";
      }
    }
    function er(e) {
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
    function rr(e) {
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
        var t = rr(r);
        if (Re[t])
          return;
        Re[t] = !0;
        var n = "";
        e && e._owner && e._owner !== ee.current && (n = " It was passed a child from " + S(e._owner.type) + "."), F(e), g('Each child in a list should have a unique "key" prop.%s%s See https://reactjs.org/link/warning-keys for more information.', t, n), F(null);
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
    function tr(e) {
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
          var n = S(r);
          Me(t, e.props, "prop", n, e);
        } else if (r.PropTypes !== void 0 && !re) {
          re = !0;
          var o = S(r);
          g("Component %s declared `PropTypes` instead of `propTypes`. Did you misspell the property assignment?", o || "Unknown");
        }
        typeof r.getDefaultProps == "function" && !r.getDefaultProps.isReactClassApproved && g("getDefaultProps is only used on classic React.createClass definitions. Use a static property named `defaultProps` instead.");
      }
    }
    function nr(e) {
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
    function je(e, r, t, n, o, s) {
      {
        var i = Fe(e);
        if (!i) {
          var a = "";
          (e === void 0 || typeof e == "object" && e !== null && Object.keys(e).length === 0) && (a += " You likely forgot to export your component from the file it's defined in, or you might have mixed up default and named imports.");
          var y = er(o);
          y ? a += y : a += _e();
          var u;
          e === null ? u = "null" : Z(e) ? u = "array" : e !== void 0 && e.$$typeof === w ? (u = "<" + (S(e.type) || "Unknown") + " />", a = " Did you accidentally export a JSX literal instead of a component?") : u = typeof e, g("React.jsx: type is invalid -- expected a string (for built-in components) or a class/function (for composite components) but got: %s.%s", u, a);
        }
        var c = Qe(e, r, t, o, s);
        if (c == null)
          return c;
        if (i) {
          var _ = r.children;
          if (_ !== void 0)
            if (n)
              if (Z(_)) {
                for (var $ = 0; $ < _.length; $++)
                  Te(_[$], e);
                Object.freeze && Object.freeze(_);
              } else
                g("React.jsx: Static children should always be an array. You are likely explicitly calling React.jsxs or React.jsxDEV. Use the Babel transform instead.");
            else
              Te(_, e);
        }
        return e === f ? nr(c) : tr(c), c;
      }
    }
    function ar(e, r, t) {
      return je(e, r, t, !0);
    }
    function ir(e, r, t) {
      return je(e, r, t, !1);
    }
    var or = ir, sr = ar;
    L.Fragment = f, L.jsx = or, L.jsxs = sr;
  }()), L;
}
process.env.NODE_ENV === "production" ? ne.exports = cr() : ne.exports = fr();
var l = ne.exports;
function dr({
  question: D = "",
  apiKey: w = "",
  selectedDocs: O = "",
  history: f = [],
  conversationId: E = null,
  apiHost: j = "",
  onEvent: T = () => {
    console.log("Event triggered, but no handler provided.");
  }
}) {
  let b = "default";
  return O && (b = O), new Promise((d, v) => {
    const m = {
      question: D,
      api_key: w,
      embeddings_key: w,
      active_docs: b,
      history: JSON.stringify(f),
      conversation_id: E,
      model: "default"
    };
    fetch(j + "/stream", {
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
      const k = ({
        done: J,
        value: C
      }) => {
        if (J) {
          console.log(R), d();
          return;
        }
        R += 1;
        const B = p.decode(C).split(`
`);
        for (let N of B) {
          if (N.trim() == "")
            continue;
          N.startsWith("data:") && (N = N.substring(5));
          const z = new MessageEvent("message", {
            data: N
          });
          T(z);
        }
        x.read().then(k).catch(v);
      };
      x.read().then(k).catch(v);
    }).catch((h) => {
      console.error("Connection failed:", h), v(h);
    });
  });
}
const pr = ({ apiHost: D = "https://gptcloud.arc53.com", selectDocs: w = "default", apiKey: O = "docsgpt-public" }) => {
  const [f, E] = Se(
    "init"
    /* Init */
  ), [j, T] = Se(""), b = lr(null);
  ur(() => {
    if (b.current) {
      const v = b.current;
      v.scrollTop = v.scrollHeight;
    }
  }, [j]);
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
      apiKey: O,
      selectedDocs: w,
      history: [],
      conversationId: null,
      apiHost: D,
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
            const k = p.metadata.title.split("/");
            R = {
              title: k[k.length - 1],
              text: p.doc
            };
          } else
            R = { title: p.doc, text: p.doc };
          console.log(R);
        } else if (p.type === "id")
          console.log(p.id);
        else {
          const R = p.answer;
          T((k) => k + R);
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
        className: `${f !== "minimized" ? "hidden" : ""} cursor-pointer`,
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
    /* @__PURE__ */ l.jsxs("div", { className: ` ${f !== "minimized" ? "" : "hidden"} divide-y dark:divide-gray-700 rounded-md border dark:border-gray-700 bg-gradient-to-br from-gray-100/80 via-white to-white dark:from-gray-900/80 dark:via-gray-900 dark:to-gray-900 font-sans shadow backdrop-blur-sm`, style: { width: "18rem", transform: "translateY(0%) translateZ(0px)" }, children: [
      /* @__PURE__ */ l.jsxs("div", { children: [
        /* @__PURE__ */ l.jsx(
          "img",
          {
            src: "https://d3dg1063dc54p9.cloudfront.net/exit.svg",
            alt: "Exit",
            className: "cursor-pointer hover:opacity-50 h-3 absolute top-0 right-0 m-2 white-filter",
            onClick: (v) => {
              v.stopPropagation(), E(
                "minimized"
                /* Minimized */
              );
            }
          }
        ),
        /* @__PURE__ */ l.jsxs("div", { className: "flex items-center gap-2 p-3", children: [
          /* @__PURE__ */ l.jsxs("div", { className: `${f === "init" || f === "processing" || f === "typing" ? "" : "hidden"} flex-1`, children: [
            /* @__PURE__ */ l.jsx("h3", { className: "text-sm font-bold text-gray-700 dark:text-gray-200", children: "Looking for help with documentation?" }),
            /* @__PURE__ */ l.jsx("p", { className: "mt-1 text-xs text-gray-400 dark:text-gray-500", children: "DocsGPT AI assistant will help you with docs" })
          ] }),
          /* @__PURE__ */ l.jsx("div", { id: "docsgpt-answer", ref: b, className: `${f !== "answer" ? "hidden" : ""}`, children: /* @__PURE__ */ l.jsx("p", { className: "mt-1 text-sm text-gray-600 dark:text-white text-left", children: j }) })
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
            className: `flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 hover:bg-gray-100 rounded-b dark:hover:bg-gray-800/70 ${f !== "init" ? "hidden" : ""}`,
            children: "Ask DocsGPT"
          }
        ),
        (f === "typing" || f === "answer") && /* @__PURE__ */ l.jsxs(
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
              /* @__PURE__ */ l.jsx("button", { className: "absolute text-gray-400 dark:text-gray-500 text-sm inset-y-0 right-2 -mx-2 px-2", type: "submit", children: "Sumbit" })
            ]
          }
        ),
        /* @__PURE__ */ l.jsxs("p", { className: `${f !== "processing" ? "hidden" : ""} flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 rounded-b`, children: [
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
