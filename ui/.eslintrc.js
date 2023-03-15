module.exports = {
    root: true,
    parserOptions: {
        ecmaVersion: '2021',
    },
    env: {
        node: true,
        browser: true,
        'vue/setup-compiler-macros': true
    },
    extends: [
        'plugin:vue/vue3-essential', // Priority A: Essential (Error Prevention)
        'plugin:vue/vue3-strongly-recommended', // Priority B: Strongly Recommended (Improving Readability)
        'plugin:vue/vue3-recommended', // Priority C: Recommended (Minimizing Arbitrary Choices and Cognitive Overhead)
        'plugin:prettier/recommended'
    ],
    plugins: [
        'vue'
    ],
    globals: {
        ga: 'readonly', // Google Analytics
        cordova: 'readonly',
        __statics: 'readonly',
        __QUASAR_SSR__: 'readonly',
        __QUASAR_SSR_SERVER__: 'readonly',
        __QUASAR_SSR_CLIENT__: 'readonly',
        __QUASAR_SSR_PWA__: 'readonly',
        process: 'readonly',
        Capacitor: 'readonly',
        chrome: 'readonly'
    },
    rules: {
        'prefer-promise-reject-errors': 'off',
        'no-debugger': process.env.NODE_ENV === 'production' ? 'error' : 'off',
    }
}
