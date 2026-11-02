'use strict';
// Dependency-injected boundary to the existing agent and renderer. No provider,
// reader or character-package assumptions belong here.
class PetReactions {
  constructor({ gate, suggest, deliver, motion }) {
    this.gate = gate; this.suggest = suggest; this.deliver = deliver; this.motion = motion;
    this.revision = 0; this.context = null; this.controller = null;
  }
  configure(context) {
    this.cancel(); this.gate.reset(); this.context = { ...context };
  }
  cancel() {
    this.revision++; this.controller?.abort(); this.controller = null;
    this.motion?.reset();
  }
  async observe(observation) {
    const revision = this.revision, context = this.context;
    if (!context) return { status: 'unconfigured' };
    const result = await this.gate.observe(observation, context);
    if (revision !== this.revision) return { status: 'cancelled' };
    if (result.status !== 'ready') return result;
    // New eligible reactions replace older agent work; late completions cannot speak.
    this.cancel(); const activeRevision = this.revision;
    const controller = this.controller = new AbortController();
    this.motion?.setState(result.event.expression);
    try {
      const suggestion = await this.suggest(result.event, { signal: controller.signal });
      if (controller.signal.aborted || activeRevision !== this.revision) return { status: 'cancelled' };
      await this.deliver({ event: result.event, suggestion }, { signal: controller.signal });
      return { status: 'delivered' };
    } catch {
      return { status: controller.signal.aborted ? 'cancelled' : 'suggestion_failed' };
    } finally {
      if (this.controller === controller) { this.controller = null; this.motion?.reset(); }
    }
  }
  dispose() { this.cancel(); this.gate.reset(); this.context = null; }
}
module.exports = { PetReactions };
