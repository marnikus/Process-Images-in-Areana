/* Recording flush probe — drain both buffers and clear them. Returns
   {mutations, requests, droppedMut, droppedNet}. Called by the recorder at
   lifecycle edges; each entry already carries its own ISO timestamp so the
   timeline survives edge-batched flushing. */
(() => {
  const w = window;
  const mut = Array.isArray(w.__arenaRecMut) ? w.__arenaRecMut.splice(0) : [];
  const net = Array.isArray(w.__arenaRecNet) ? w.__arenaRecNet.splice(0) : [];
  return {ok: true, mutations: mut, requests: net};
})()
