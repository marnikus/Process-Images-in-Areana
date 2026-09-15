import js from "@eslint/js";
import globals from "globals";
export default [
  {
    files: [
      "src/image_queue/ui/js/{boot,panels,workspace,workspace-view,connect,wire}.js",
    ],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        App: "readonly",
        GridInitializers: "readonly",
        SashGrid: "readonly",
        SashCore: "readonly",
        Workspace: "readonly",
        WorkspaceView: "readonly",
        WorkspaceWire: "readonly",
        QWebChannel: "readonly",
        qt: "readonly",
      },
    },
    rules: {
      ...js.configs.recommended.rules,
      "no-redeclare": ["error", { builtinGlobals: false }],
      complexity: ["error", 10],
      "max-depth": ["error", 4],
      "max-params": ["error", 4],
      "no-unused-vars": [
        "error",
        {
          varsIgnorePattern:
            "^(Workspace|WorkspaceView|PanelRegistry|WorkspaceWire)$",
        },
      ],
    },
  },
];
