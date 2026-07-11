/** Safe WebGL acquisition for decorative product scenes. */
export function acquireWebGlContext(
  canvas: HTMLCanvasElement,
): WebGLRenderingContext | WebGL2RenderingContext | null {
  const attributes: WebGLContextAttributes = {
    alpha: true,
    antialias: true,
  };

  try {
    return (
      canvas.getContext("webgl2", attributes) ??
      canvas.getContext("webgl", attributes)
    );
  } catch {
    return null;
  }
}
