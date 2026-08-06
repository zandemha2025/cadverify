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

/** One-shot capability probe for components that cannot pass a pre-acquired
 * context into their renderer (for example react-three-fiber's Canvas). The
 * probe is released immediately when the browser exposes WEBGL_lose_context,
 * so it does not consume one of the renderer's scarce live context slots. */
export function probeWebGlSupport(
  createCanvas: () => HTMLCanvasElement = () => document.createElement("canvas"),
): boolean {
  try {
    const context = acquireWebGlContext(createCanvas());
    if (!context) return false;
    const release = context.getExtension("WEBGL_lose_context") as
      | { loseContext: () => void }
      | null;
    release?.loseContext();
    return true;
  } catch {
    return false;
  }
}
