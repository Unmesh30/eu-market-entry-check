// Own company or merchant of record: the arithmetic behind box 3.
// Kept in its own file so the tests run exactly the code the page runs.
function compareRoutes(input) {
  const names = ["sales", "feePct", "cardPct", "setup", "running"];
  const invalid = names.filter((name) => !Number.isFinite(input[name]) || input[name] < 0);
  if (input.feePct > 100) invalid.push("feePct");
  if (input.cardPct > 100) invalid.push("cardPct");
  if (invalid.length) return { ok: false, invalid };

  // A merchant-of-record fee already includes card fees, so only the part above them is extra.
  const extraShare = (input.feePct - input.cardPct) / 100;
  if (extraShare <= 0) return { ok: true, mode: "own-never-cheaper" };

  const breakEven = input.running / extraShare; // yearly sales where both routes cost the same
  const yearlySaving = input.sales * extraShare - input.running; // own company vs merchant of record
  const paybackMonths = yearlySaving > 0 ? (input.setup / yearlySaving) * 12 : null;
  return { ok: true, mode: "compare", breakEven, yearlySaving, paybackMonths };
}

if (typeof module !== "undefined") module.exports = { compareRoutes };
