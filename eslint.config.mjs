import js from "@eslint/js";
import globals from "globals";
export default [
  {files: ["tools/visual_fixture.cjs"], languageOptions: {sourceType: "commonjs", globals: globals.node}, rules: js.configs.recommended.rules},
  {
    files: [
      "src/image_queue/ui/js/{boot,panels,workspace,workspace-view,connect,wire,libraries,stack-editor,queue-view,chrome-view,features,block-fields}.js",
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
        StackDnDConfigRows: "readonly", BlockFields: "readonly",
        Features: "readonly", Libraries: "readonly", StackEditor: "readonly", QueueView: "readonly", ChromeView: "readonly", StackDrag: "readonly", PresetsUITemplates: "readonly",
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
            "^(Workspace|WorkspaceView|PanelRegistry|WorkspaceWire|Features|Libraries|StackEditor|QueueView|ChromeView|BlockFields)$",
        },
      ],
    },
  },
];
