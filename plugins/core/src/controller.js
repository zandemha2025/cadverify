export function createCheckController({ client, view, exportStep }) {
  let running = false;
  return {
    async check() {
      if (running) return;
      running = true;
      view.progress("Exporting STEP from Onshape...");
      try {
        const part = await exportStep();
        if (!part?.source) throw new Error("Host export did not include revision identity");
        view.progress("Checking with ProofShape...");
        const verdict = await client.validateStep(part);
        view.verdict(verdict);
      } catch (error) {
        view.error(error instanceof Error ? error.message : String(error));
      } finally {
        running = false;
      }
    },
  };
}
