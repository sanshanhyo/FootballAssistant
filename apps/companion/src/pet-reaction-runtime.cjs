'use strict';
const { randomUUID } = require('node:crypto');
const { PetReactions } = require('./pet-reactions.cjs');
const { FileResultJournal, ResultEventGate } = require('./pet-events.cjs');
const { readStateFile, writeStateFile } = require('./state-file.cjs');
async function createPetReactionRuntime({ runtime, journalFile, preferencesFile, emit }) {
  const stored = await readStateFile(preferencesFile, 16384);
  let enabled = false;
  if (stored.bytes) { const value = JSON.parse(stored.bytes); if (value.schema_version !== 1 || typeof value.enabled !== 'boolean') throw Error('Invalid reaction preferences'); enabled = value.enabled; }
  let revision = stored.revision, contextKey = null;
  const motion = state => emit({ type: 'pet-motion', state, epoch: runtime.epoch, sessionId: runtime.sessionId });
  const reactions = new PetReactions({ gate: new ResultEventGate({ journal: new FileResultJournal(journalFile) }),
    suggest: async (event, { signal }) => {
      const epoch = runtime.epoch, sessionId = runtime.sessionId, characterContext = runtime.characterContext();
      const result = await runtime.realClient.reply({ message: `请对以下已核实赛果做一句简短陪伴回应，不推断过程或战术原因：${JSON.stringify(event)}`, conversationId: runtime.backendConversationId || sessionId, characterContext, signal });
      return { result, epoch, sessionId, characterId: runtime.characterId };
    },
    deliver: async ({ suggestion }, { signal }) => {
      if (signal.aborted || suggestion.epoch !== runtime.epoch || suggestion.sessionId !== runtime.sessionId || suggestion.characterId !== runtime.characterId) return;
      runtime.addMessage({ id: randomUUID(), role: 'assistant', origin: 'proactive', text: suggestion.result.text, epoch: suggestion.epoch, sessionId: suggestion.sessionId, createdAt: new Date().toISOString(), metadata: suggestion.result.metadata, cards: suggestion.result.cards || [] }); runtime.changed();
    }, motion: { setState: motion, reset: () => motion('idle') },
  });
  function configure() {
    const state = runtime.state(); const key = JSON.stringify([enabled, state.mode, state.epoch, state.sessionId, runtime.characterId, state.proactivity]);
    if (key === contextKey) return; contextKey = key;
    reactions.configure({ enabled: enabled && state.mode === 'real', muted: state.proactivity === 0, proactivity: state.proactivity, characterId: runtime.characterId, sessionGeneration: state.epoch });
  }
  const listener = event => { if (event.type === 'state') configure(); };
  runtime.on('event', listener); configure();
  return {
    status() { return { enabled, readerEvidence: 'unavailable', reason: '当前读取器没有可信终场、存档和玩家球队身份，不会从比分猜测赛果。' }; },
    async setEnabled(value) { if (typeof value !== 'boolean') throw Error('Invalid reaction switch'); revision = await writeStateFile(preferencesFile, JSON.stringify({ schema_version: 1, enabled: value }), revision); enabled = value; configure(); return this.status(); },
    // Internal trusted-adapter ingress only, never exposed through renderer IPC.
    observeVerified(observation) { if (observation?.saveId !== runtime.characterContext()?.save_id || runtime.state().characterScope?.verifiedSave !== true) return Promise.resolve({ status: 'unknown' }); return reactions.observe(observation); },
    cancel() { reactions.cancel(); },
    dispose() { runtime.off('event', listener); reactions.dispose(); },
  };
}
module.exports = { createPetReactionRuntime };
