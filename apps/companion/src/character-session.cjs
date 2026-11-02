'use strict';
const { scopeFor } = require('./character-library.cjs');
/** Single active character. All generated output must retain and check its captured token. */
class CharacterSession {
  constructor({ library, cancel = [] }) {
    this.library = library; this.cancel = cancel; this.epoch = 0; this.current = null; this.controller = null;
  }
  activate(saveId, characterId) {
    // Validate all inputs and persist selection before canceling the working session.
    let desired = characterId === undefined ? this.library.selected(saveId) : this.library.resolve(characterId);
    if (characterId !== undefined && desired.fallback) throw Error('Selected character is unavailable');
    const scope = scopeFor(saveId, desired.characterId);
    desired = this.library.select(saveId, desired.characterId);
    this.controller?.abort('character_switch');
    this.epoch += 1;
    const cancellationErrors = [];
    for (const stop of this.cancel) {
      // Cancellation hooks must synchronously stop/invalidate output; late async results are epoch-gated.
      try { const pending = stop(); if (pending?.catch) pending.catch(() => {}); } catch (error) { cancellationErrors.push(String(error.message || error)); }
    }
    this.controller = new AbortController();
    this.current = Object.freeze({ epoch: this.epoch, scope, character: desired, signal: this.controller.signal, cancellationErrors });
    return this.current;
  }
  accepts(token) { return Boolean(this.current && token === this.current && !token.signal.aborted && token.epoch === this.epoch); }
  guard(token, effect) { if (!this.accepts(token)) return false; effect(); return true; }
  dispose() { this.controller?.abort('disposed'); this.epoch += 1; this.current = null; for (const stop of this.cancel) { try { const p = stop(); p?.catch?.(() => {}); } catch {} } }
}
module.exports = { CharacterSession };
