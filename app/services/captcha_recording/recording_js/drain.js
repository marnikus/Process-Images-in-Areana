(() => {
  const state=window.__arenaCaptchaRecorderV1;
  if (!state) return {ok:false,changes:[],dropped:0};
  const changes=state.queue.splice(0,200);
  const dropped=state.dropped; state.dropped=0;
  return {ok:true,changes,dropped,pending:state.queue.length};
})()
