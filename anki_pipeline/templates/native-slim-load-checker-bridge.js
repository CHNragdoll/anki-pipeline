// Lexical FRAME checker only; no global crypto changes or view-bound cache.
function withSlimLoadChecker(win, run) {
  const key = '__studySlimLoadCheckerCapture';
  if (typeof knownPinMatches !== 'function' || key in win) return run(false);
  const capture = () => knownPinMatches;
  try { Object.defineProperty(win, key, {value: capture, configurable: true}); }
  catch (_) { return run(false); }
  try { return run(true); }
  finally {
    try { if (Object.getOwnPropertyDescriptor(win, key)?.value === capture) delete win[key]; }
    catch (_) {}
  }
}
