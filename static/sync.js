const clamp = (n, low, high) => Math.max(low, Math.min(n, high));

// Align the corresponding PDF paragraph with the clicked paragraph's screen height.
// Measurements are CSS pixels, independent of zoom and display pixel density.
export function paragraphScrollPosition(block, page, view) {
  const [x0, y0, x1] = block.bbox;
  const top = view.paperTop + y0 / page.height * view.paperHeight;
  const left = view.paperLeft + x0 / page.width * view.paperWidth;
  const right = view.paperLeft + x1 / page.width * view.paperWidth;
  const inset = 16;
  const offset = clamp(view.offsetTop, inset, Math.max(inset, view.viewportHeight - 64));
  let scrollLeft = view.scrollLeft;
  if (left < scrollLeft + inset || right - left > view.viewportWidth - inset * 2) {
    scrollLeft = left - inset;
  } else if (right > scrollLeft + view.viewportWidth - inset) {
    scrollLeft = right - view.viewportWidth + inset;
  }
  return {
    top: clamp(top - offset, 0, view.maxScrollTop),
    left: clamp(scrollLeft, 0, view.maxScrollLeft),
  };
}
