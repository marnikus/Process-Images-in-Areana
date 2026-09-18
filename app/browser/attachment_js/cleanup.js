((marker) => {
  const selector = `[data-arena-upload-target="${CSS.escape(marker)}"]`;
  const input = document.querySelector(selector);
  if (input) input.removeAttribute('data-arena-upload-target');
  return {ok: true, removed: Boolean(input)};
})
