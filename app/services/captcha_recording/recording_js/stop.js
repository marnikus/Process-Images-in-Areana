(() => {
  const state=window.__arenaCaptchaRecorderV1;
  if (!state) return {ok:true,stopped:false};
  try { if (state.observer) state.observer.disconnect(); } catch (_) {}
  delete window.__arenaCaptchaRecorderV1;
  return {ok:true,stopped:true};
})()
