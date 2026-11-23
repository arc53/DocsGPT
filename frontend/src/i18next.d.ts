import 'i18next';

// i18next 27 types t() strictly by default, which rejects options that may be
// undefined. Translation resources are not typed here, so the strict checks
// have no keys or variables to verify; keep the v26 call signatures.
declare module 'i18next' {
  interface CustomTypeOptions {
    strictInterpolationChecks: false;
  }
}
