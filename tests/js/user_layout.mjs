/* The user's real persisted layout (config/session.json) — the exact grid the
   bug reports were filed against. Shared by the regression tests and the fuzz
   so they exercise the reported tree. Sizes are the user's saved values. */
export const USER_TREE = {
  t: 'split', dir: 'row',
  children: [
    { t: 'leaf', id: 'action_blocks' },
    { t: 'split', dir: 'col', children: [
      { t: 'split', dir: 'col', children: [
        { t: 'split', dir: 'row', children: [
          { t: 'split', dir: 'col', children: [{ t: 'leaf', id: 'url_list' }, { t: 'leaf', id: 'folder' }], sizes: [55, 45] },
          { t: 'split', dir: 'col', children: [{ t: 'leaf', id: 'prompt' }, { t: 'leaf', id: 'run' }], sizes: [64.28571428571429, 35.714285714285715] },
        ], sizes: [76.07093156234069, 23.929068437659314] },
        { t: 'split', dir: 'row', children: [
          { t: 'leaf', id: 'block_config' },
          { t: 'split', dir: 'col', children: [{ t: 'leaf', id: 'arena_presets' }, { t: 'leaf', id: 'progress' }], sizes: [58.333333333333336, 41.666666666666667] },
        ], sizes: [80.87887464210132, 19.12112535789867] },
      ], sizes: [73.20061255742726, 26.79938744257274] },
      { t: 'split', dir: 'col', children: [
        { t: 'leaf', id: 'browser' }, { t: 'leaf', id: 'queue' }, { t: 'leaf', id: 'watcher' },
      ], sizes: [33.33333333333333, 46.603970741901776, 20.06269592476489] },
    ], sizes: [57.63665594855305, 42.363344051446944] },
    { t: 'leaf', id: 'settings' },
    { t: 'leaf', id: 'log' },
  ],
  sizes: [23.511875491738788, 32.979076514555466, 33.43454956726987, 10.074498426435877],
};
export const USER_CLOSED = ['progress', 'arena_presets', 'block_config', 'browser'];
export const USER_MINIMIZED = ['settings'];
