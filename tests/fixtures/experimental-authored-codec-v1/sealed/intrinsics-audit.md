# Bounded exact-code intrinsic audit

Scope: SHA-pinned first 9014 IIFE after existing compact-v5, only when the
authenticated document is fully normalized and the conservative one-shot
capability remains live. This is not a proof for arbitrary hostile host objects.

* Even empty query results execute NodeList.prototype.forEach three times.
  This unconditional read was missing from the captured-descriptor list and has
  a real throwing counterexample. v2 adds exactly that descriptor identity.
* Array.from, its Array.forEach callbacks, classList add/remove, closest, packed
  decoding, atob/hex and chunk attribute writes occur only inside matching node
  callbacks. Eligibility forbids residual aliases/span[_c]/a[data-rb-j], and
  the observer rejects relevant attribute/structural drift before consumption.
  The reviewer tested Array.from/classList mutations and found no difference
  with the empty v5 candidate set. They were not expanded into new protocol.
* Existing Document/Element query descriptor checks remain; the v5 mapping
  reflection and stock Object.prototype checks remain the audited prior code.
  Changing captured reflection methods or the supported mapping environment
  invalidates the capability. No assumption of generalized intrinsic sandboxing
  or per-node getter equivalence is added.
* The observed NodeList change is detected after owner validation and before
  accepting. Rejection retires the one-shot record and runs original v5 source,
  preserving its actual first-query/throw path.
