/** Resolve the app's extensionless relative TypeScript imports under node --test. */
export async function resolve(specifier, context, nextResolve) {
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (/^\.{1,2}\//.test(specifier) && !/\.[^/]+$/.test(specifier)) {
      return nextResolve(`${specifier}.ts`, context);
    }
    throw error;
  }
}
