import Ce, { useState as Se, useRef as lr, useEffect as ur } from "react";
var ne = { exports: {} }, W = {};
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
    return W;
  Pe = 1;
  var h = Ce, g = Symbol.for("react.element"), j = Symbol.for("react.fragment"), _ = Object.prototype.hasOwnProperty, P = h.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED.ReactCurrentOwner, O = { key: !0, ref: !0, __self: !0, __source: !0 };
  function R(b, l, w) {
    var v, p = {}, c = null, E = null;
    w !== void 0 && (c = "" + w), l.key !== void 0 && (c = "" + l.key), l.ref !== void 0 && (E = l.ref);
    for (v in l)
      _.call(l, v) && !O.hasOwnProperty(v) && (p[v] = l[v]);
    if (b && b.defaultProps)
      for (v in l = b.defaultProps, l)
        p[v] === void 0 && (p[v] = l[v]);
    return { $$typeof: g, type: b, key: c, ref: E, props: p, _owner: P.current };
  }
  return W.Fragment = j, W.jsx = R, W.jsxs = R, W;
}
var Y = {};
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
    var h = Ce, g = Symbol.for("react.element"), j = Symbol.for("react.portal"), _ = Symbol.for("react.fragment"), P = Symbol.for("react.strict_mode"), O = Symbol.for("react.profiler"), R = Symbol.for("react.provider"), b = Symbol.for("react.context"), l = Symbol.for("react.forward_ref"), w = Symbol.for("react.suspense"), v = Symbol.for("react.suspense_list"), p = Symbol.for("react.memo"), c = Symbol.for("react.lazy"), E = Symbol.for("react.offscreen"), T = Symbol.iterator, L = "@@iterator";
    function J(e) {
      if (e === null || typeof e != "object")
        return null;
      var r = T && e[T] || e[L];
      return typeof r == "function" ? r : null;
    }
    var C = h.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;
    function m(e) {
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
    var D = !1, z = !1, De = !1, Ne = !1, Ae = !1, ae;
    ae = Symbol.for("react.module.reference");
    function Fe(e) {
      return !!(typeof e == "string" || typeof e == "function" || e === _ || e === O || Ae || e === P || e === w || e === v || Ne || e === E || D || z || De || typeof e == "object" && e !== null && (e.$$typeof === c || e.$$typeof === p || e.$$typeof === R || e.$$typeof === b || e.$$typeof === l || // This needs to include all possible module reference object
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
      if (typeof e.tag == "number" && m("Received an unexpected object in getComponentNameFromType(). This is likely a bug in React. Please file an issue."), typeof e == "function")
        return e.displayName || e.name || null;
      if (typeof e == "string")
        return e;
      switch (e) {
        case _:
          return "Fragment";
        case j:
          return "Portal";
        case O:
          return "Profiler";
        case P:
          return "StrictMode";
        case w:
          return "Suspense";
        case v:
          return "SuspenseList";
      }
      if (typeof e == "object")
        switch (e.$$typeof) {
          case b:
            var r = e;
            return ie(r) + ".Consumer";
          case R:
            var t = e;
            return ie(t._context) + ".Provider";
          case l:
            return $e(e, e.render, "ForwardRef");
          case p:
            var n = e.displayName || null;
            return n !== null ? n : k(e.type) || "Memo";
          case c: {
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
    var N = Object.assign, $ = 0, oe, se, le, ue, ce, fe, de;
    function ve() {
    }
    ve.__reactDisabledLog = !0;
    function Ie() {
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
    function We() {
      {
        if ($--, $ === 0) {
          var e = {
            configurable: !0,
            enumerable: !0,
            writable: !0
          };
          Object.defineProperties(console, {
            log: N({}, e, {
              value: oe
            }),
            info: N({}, e, {
              value: se
            }),
            warn: N({}, e, {
              value: le
            }),
            error: N({}, e, {
              value: ue
            }),
            group: N({}, e, {
              value: ce
            }),
            groupCollapsed: N({}, e, {
              value: fe
            }),
            groupEnd: N({}, e, {
              value: de
            })
          });
        }
        $ < 0 && m("disabledDepth fell below zero. This is a bug in React. Please file an issue.");
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
            } catch (S) {
              n = S;
            }
            Reflect.construct(e, [], i);
          } else {
            try {
              i.call();
            } catch (S) {
              n = S;
            }
            e.call(i.prototype);
          }
        } else {
          try {
            throw Error();
          } catch (S) {
            n = S;
          }
          e();
        }
      } catch (S) {
        if (S && n && typeof S.stack == "string") {
          for (var a = S.stack.split(`
`), y = n.stack.split(`
`), f = a.length - 1, d = y.length - 1; f >= 1 && d >= 0 && a[f] !== y[d]; )
            d--;
          for (; f >= 1 && d >= 0; f--, d--)
            if (a[f] !== y[d]) {
              if (f !== 1 || d !== 1)
                do
                  if (f--, d--, d < 0 || a[f] !== y[d]) {
                    var x = `
` + a[f].replace(" at new ", " at ");
                    return e.displayName && x.includes("<anonymous>") && (x = x.replace("<anonymous>", e.displayName)), typeof e == "function" && M.set(e, x), x;
                  }
                while (f >= 1 && d >= 0);
              break;
            }
        }
      } finally {
        X = !1, H.current = s, We(), Error.prepareStackTrace = o;
      }
      var F = e ? e.displayName || e.name : "", ke = F ? V(F) : "";
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
        case w:
          return V("Suspense");
        case v:
          return V("SuspenseList");
      }
      if (typeof e == "object")
        switch (e.$$typeof) {
          case l:
            return Le(e.render);
          case p:
            return U(e.type, r, t);
          case c: {
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
            } catch (f) {
              a = f;
            }
            a && !(a instanceof Error) && (G(o), m("%s: type specification of %s `%s` is invalid; the type checker function must return `null` or an `Error` but returned a %s. You may have forgotten to pass an argument to the type checker creator (arrayOf, instanceOf, objectOf, oneOf, oneOfType, and shape all require an argument).", n || "React class", t, i, typeof a), G(null)), a instanceof Error && !(a.message in he) && (he[a.message] = !0, G(o), m("Failed %s type: %s", t, a.message), G(null));
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
        return m("The provided key is an unsupported type %s. This value must be coerced to a string before before using it here.", qe(e)), ge(e);
    }
    var I = C.ReactCurrentOwner, Je = {
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
      if (typeof e.ref == "string" && I.current && r && I.current.stateNode !== r) {
        var t = k(I.current.type);
        Q[t] || (m('Component "%s" contains the string ref "%s". Support for string refs will be removed in a future major release. This case cannot be automatically converted to an arrow function. We ask you to manually fix this case by using useRef() or createRef() instead. Learn more about using refs safely here: https://reactjs.org/link/strict-mode-string-ref', k(I.current.type), e.ref), Q[t] = !0);
      }
    }
    function Ke(e, r) {
      {
        var t = function() {
          be || (be = !0, m("%s: `key` is not a prop. Trying to access it will result in `undefined` being returned. If you need to access the same value within the child component, you should pass it as a different prop. (https://reactjs.org/link/special-props)", r));
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
          Ee || (Ee = !0, m("%s: `ref` is not a prop. Trying to access it will result in `undefined` being returned. If you need to access the same value within the child component, you should pass it as a different prop. (https://reactjs.org/link/special-props)", r));
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
        $$typeof: g,
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
          var f = e.defaultProps;
          for (s in f)
            i[s] === void 0 && (i[s] = f[s]);
        }
        if (a || y) {
          var d = typeof e == "function" ? e.displayName || e.name || "Unknown" : e;
          a && Ke(i, d), y && Xe(i, d);
        }
        return Ze(e, a, y, o, n, I.current, i);
      }
    }
    var ee = C.ReactCurrentOwner, xe = C.ReactDebugCurrentFrame;
    function A(e) {
      if (e) {
        var r = e._owner, t = U(e.type, e._source, r ? r.type : null);
        xe.setExtraStackFrame(t);
      } else
        xe.setExtraStackFrame(null);
    }
    var re;
    re = !1;
    function te(e) {
      return typeof e == "object" && e !== null && e.$$typeof === g;
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
        e && e._owner && e._owner !== ee.current && (n = " It was passed a child from " + k(e._owner.type) + "."), A(e), m('Each child in a list should have a unique "key" prop.%s%s See https://reactjs.org/link/warning-keys for more information.', t, n), A(null);
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
        else if (typeof r == "object" && (r.$$typeof === l || // Note: Memo only checks outer props here.
        // Inner props are checked in the reconciler.
        r.$$typeof === p))
          t = r.propTypes;
        else
          return;
        if (t) {
          var n = k(r);
          Me(t, e.props, "prop", n, e);
        } else if (r.PropTypes !== void 0 && !re) {
          re = !0;
          var o = k(r);
          m("Component %s declared `PropTypes` instead of `propTypes`. Did you misspell the property assignment?", o || "Unknown");
        }
        typeof r.getDefaultProps == "function" && !r.getDefaultProps.isReactClassApproved && m("getDefaultProps is only used on classic React.createClass definitions. Use a static property named `defaultProps` instead.");
      }
    }
    function nr(e) {
      {
        for (var r = Object.keys(e.props), t = 0; t < r.length; t++) {
          var n = r[t];
          if (n !== "children" && n !== "key") {
            A(e), m("Invalid prop `%s` supplied to `React.Fragment`. React.Fragment can only have `key` and `children` props.", n), A(null);
            break;
          }
        }
        e.ref !== null && (A(e), m("Invalid attribute `ref` supplied to `React.Fragment`."), A(null));
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
          var f;
          e === null ? f = "null" : Z(e) ? f = "array" : e !== void 0 && e.$$typeof === g ? (f = "<" + (k(e.type) || "Unknown") + " />", a = " Did you accidentally export a JSX literal instead of a component?") : f = typeof e, m("React.jsx: type is invalid -- expected a string (for built-in components) or a class/function (for composite components) but got: %s.%s", f, a);
        }
        var d = Qe(e, r, t, o, s);
        if (d == null)
          return d;
        if (i) {
          var x = r.children;
          if (x !== void 0)
            if (n)
              if (Z(x)) {
                for (var F = 0; F < x.length; F++)
                  Te(x[F], e);
                Object.freeze && Object.freeze(x);
              } else
                m("React.jsx: Static children should always be an array. You are likely explicitly calling React.jsxs or React.jsxDEV. Use the Babel transform instead.");
            else
              Te(x, e);
        }
        return e === _ ? nr(d) : tr(d), d;
      }
    }
    function ar(e, r, t) {
      return je(e, r, t, !0);
    }
    function ir(e, r, t) {
      return je(e, r, t, !1);
    }
    var or = ir, sr = ar;
    Y.Fragment = _, Y.jsx = or, Y.jsxs = sr;
  }()), Y;
}
process.env.NODE_ENV === "production" ? ne.exports = cr() : ne.exports = fr();
var u = ne.exports;
function dr({
  question: h = "",
  apiKey: g = "",
  selectedDocs: j = "",
  history: _ = [],
  conversationId: P = null,
  apiHost: O = "",
  onEvent: R = () => {
    console.log("Event triggered, but no handler provided.");
  }
}) {
  let b = "default";
  return j && (b = j), new Promise((l, w) => {
    const v = {
      question: h,
      api_key: g,
      embeddings_key: g,
      active_docs: b,
      history: JSON.stringify(_),
      conversation_id: P
    };
    fetch(O + "/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(v)
    }).then((p) => {
      if (!p.body)
        throw Error("No response body");
      const c = p.body.getReader(), E = new TextDecoder("utf-8");
      let T = 0;
      const L = ({
        done: J,
        value: C
      }) => {
        if (J) {
          console.log(T), l();
          return;
        }
        T += 1;
        const B = E.decode(C).split(`
`);
        for (let D of B) {
          if (D.trim() == "")
            continue;
          D.startsWith("data:") && (D = D.substring(5));
          const z = new MessageEvent("message", {
            data: D
          });
          R(z);
        }
        c.read().then(L).catch(w);
      };
      c.read().then(L).catch(w);
    }).catch((p) => {
      console.error("Connection failed:", p), w(p);
    });
  });
}
const pr = () => {
  const [h, g] = Se(
    "init"
    /* Init */
  ), [j, _] = Se(""), P = "local/1706.03762.pdf/", O = "http://localhost:7091", R = lr(null);
  ur(() => {
    if (R.current) {
      const l = R.current;
      l.scrollTop = l.scrollHeight;
    }
  }, [j]);
  const b = (l) => {
    _(""), l.preventDefault(), g(
      "processing"
      /* Processing */
    ), setTimeout(() => {
      g(
        "answer"
        /* Answer */
      );
    }, 2e3);
    const v = l.currentTarget[0].value;
    dr({
      question: v,
      apiKey: "",
      selectedDocs: P,
      history: [],
      conversationId: null,
      apiHost: O,
      onEvent: (p) => {
        const c = JSON.parse(p.data);
        if (c.type === "end")
          g(
            "answer"
            /* Answer */
          );
        else if (c.type === "source") {
          let E;
          if (c.metadata && c.metadata.title) {
            const T = c.metadata.title.split("/");
            E = {
              title: T[T.length - 1],
              text: c.doc
            };
          } else
            E = { title: c.doc, text: c.doc };
          console.log(E);
        } else if (c.type === "id")
          console.log(c.id);
        else {
          const E = c.answer;
          _((T) => T + E);
        }
      }
    });
  };
  return /* @__PURE__ */ u.jsx(u.Fragment, { children: /* @__PURE__ */ u.jsxs("div", { className: "dark widget-container", children: [
    /* @__PURE__ */ u.jsx(
      "div",
      {
        onClick: () => g(
          "init"
          /* Init */
        ),
        className: `${h !== "minimized" ? "hidden" : ""} cursor-pointer`,
        children: /* @__PURE__ */ u.jsx("div", { className: "mr-2 mb-2 w-20 h-20 rounded-full overflow-hidden dark:divide-gray-700 border dark:border-gray-700 bg-gradient-to-br from-gray-100/80 via-white to-white dark:from-gray-900/80 dark:via-gray-900 dark:to-gray-900 font-sans shadow backdrop-blur-sm flex items-center justify-center", children: /* @__PURE__ */ u.jsx(
          "img",
          {
            src: "https://d3dg1063dc54p9.cloudfront.net/cute-docsgpt.png",
            alt: "DocsGPT",
            className: "cursor-pointer hover:opacity-50 h-14"
          }
        ) })
      }
    ),
    /* @__PURE__ */ u.jsxs("div", { className: ` ${h !== "minimized" ? "" : "hidden"} divide-y dark:divide-gray-700 rounded-md border dark:border-gray-700 bg-gradient-to-br from-gray-100/80 via-white to-white dark:from-gray-900/80 dark:via-gray-900 dark:to-gray-900 font-sans shadow backdrop-blur-sm`, style: { width: "18rem", transform: "translateY(0%) translateZ(0px)" }, children: [
      /* @__PURE__ */ u.jsxs("div", { children: [
        /* @__PURE__ */ u.jsx(
          "img",
          {
            src: "https://d3dg1063dc54p9.cloudfront.net/exit.svg",
            alt: "Exit",
            className: "cursor-pointer hover:opacity-50 h-3 absolute top-0 right-0 m-2 white-filter",
            onClick: (l) => {
              l.stopPropagation(), g(
                "minimized"
                /* Minimized */
              );
            }
          }
        ),
        /* @__PURE__ */ u.jsxs("div", { className: "flex items-center gap-2 p-3", children: [
          /* @__PURE__ */ u.jsxs("div", { className: `${h === "init" || h === "processing" || h === "typing" ? "" : "hidden"} flex-1`, children: [
            /* @__PURE__ */ u.jsx("h3", { className: "text-sm font-bold text-gray-700 dark:text-gray-200", children: "Looking for help with documentation?" }),
            /* @__PURE__ */ u.jsx("p", { className: "mt-1 text-xs text-gray-400 dark:text-gray-500", children: "DocsGPT AI assistant will help you with docs" })
          ] }),
          /* @__PURE__ */ u.jsx("div", { id: "docsgpt-answer", ref: R, className: `${h !== "answer" ? "hidden" : ""}`, children: /* @__PURE__ */ u.jsx("p", { className: "mt-1 text-sm text-gray-600 dark:text-white text-left", children: j }) })
        ] })
      ] }),
      /* @__PURE__ */ u.jsxs("div", { className: "w-full", children: [
        /* @__PURE__ */ u.jsx(
          "button",
          {
            onClick: () => g(
              "typing"
              /* Typing */
            ),
            className: `flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 hover:bg-gray-100 rounded-b dark:hover:bg-gray-800/70 ${h !== "init" ? "hidden" : ""}`,
            children: "Ask DocsGPT"
          }
        ),
        (h === "typing" || h === "answer") && /* @__PURE__ */ u.jsxs(
          "form",
          {
            onSubmit: b,
            className: "relative w-full m-0",
            style: { opacity: 1 },
            children: [
              /* @__PURE__ */ u.jsx(
                "input",
                {
                  type: "text",
                  className: "w-full bg-transparent px-5 py-3 pr-8 text-sm text-gray-700 dark:text-white focus:outline-none",
                  placeholder: "What do you want to do?"
                }
              ),
              /* @__PURE__ */ u.jsx("button", { className: "absolute text-gray-400 dark:text-gray-500 text-sm inset-y-0 right-2 -mx-2 px-2", type: "submit", children: "Sumbit" })
            ]
          }
        ),
        /* @__PURE__ */ u.jsxs("p", { className: `${h !== "processing" ? "hidden" : ""} flex w-full justify-center px-5 py-3 text-sm text-gray-800 font-bold dark:text-white transition duration-300 rounded-b`, children: [
          "Processing",
          /* @__PURE__ */ u.jsx("span", { className: "dot-animation", children: "." }),
          /* @__PURE__ */ u.jsx("span", { className: "dot-animation delay-200", children: "." }),
          /* @__PURE__ */ u.jsx("span", { className: "dot-animation delay-400", children: "." })
        ] })
      ] })
    ] })
  ] }) });
};
export {
  pr as DocsGPTWidget
};
//# sourceMappingURL=index.es.js.map
