export type MakeBuyInputs = {
  quantity: number;
  makeFixed: number;
  makeVariable: number;
  buyFixed: number;
  buyVariable: number;
};

/** Constant-rate planning model. Costs must share a currency and time horizon. */
export function calculateMakeBuy(input: MakeBuyInputs) {
  if (!Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 1_000_000_000) {
    throw new Error("Quantity must be a whole number between 1 and 1,000,000,000.");
  }
  for (const value of [input.makeFixed, input.makeVariable, input.buyFixed, input.buyVariable]) {
    if (!Number.isFinite(value) || value < 0 || value > 1_000_000_000) {
      throw new Error("Enter each cost between 0 and 1,000,000,000.");
    }
  }
  const makeTotal = input.makeFixed + input.quantity * input.makeVariable;
  const buyTotal = input.buyFixed + input.quantity * input.buyVariable;
  const difference = buyTotal - makeTotal;
  // Treat only floating-point rounding noise as equality, not rounded dollars.
  const equal = Math.abs(difference) <= Number.EPSILON * Math.max(1, makeTotal, buyTotal) * 4;
  const fixedDifference = input.makeFixed - input.buyFixed;
  const variableDifference = input.buyVariable - input.makeVariable;
  const equality = variableDifference === 0 ? null : fixedDifference / variableDifference;
  const crossover = equality !== null && Number.isFinite(equality) && equality > 0 ? equality : null;
  return {
    makeTotal, buyTotal,
    makeUnit: makeTotal / input.quantity,
    buyUnit: buyTotal / input.quantity,
    savings: equal ? 0 : Math.abs(difference),
    cheaper: equal ? "equal" as const : difference > 0 ? "make" as const : "buy" as const,
    crossover,
    crossoverType: crossover !== null ? "positive" as const : fixedDifference === 0 && variableDifference === 0 ? "all" as const : "none" as const,
  };
}
