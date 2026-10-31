'use strict';
(function (root, factory) {
  const value = factory();
  if (typeof module === 'object' && module.exports) module.exports = value;
  else root.CompanionScenes = value;
})(typeof globalThis !== 'undefined' ? globalThis : this, () => {
  const base = 'assets/characters/official.eckera/';
  const sources = Object.freeze({ default: `${base}default.png`, 'no-game': `${base}states/no-game.png`, transfer: `${base}states/transfer.png`, tactics: `${base}states/tactics.png`, research: `${base}states/research.png` });
  const capabilities = Object.freeze({ transfer_analysis: 'transfer', tactical_analysis: 'tactics', player_info: 'research' });
  // These are discussion illustrations, not assertions about actions in the game.
  function discussionScene(text, capability) {
    if (Object.hasOwn(capabilities, capability)) return capabilities[capability];
    if (capability) return 'default';
    if (typeof text !== 'string') return 'default';
    if (/转会|引援|\btransfer\b|\bsigning\b/i.test(text)) return 'transfer';
    if (/战术|阵型|首发|\btactics?\b|\bformation\b|\blineup\b/i.test(text)) return 'tactics';
    if (/球员|球探|属性|\bplayer\b|\bscouting\b/i.test(text)) return 'research';
    return 'default';
  }
  function selectScene({ game, messages = [], sessionId, epoch } = {}) {
    if (game?.state === 'not_detected') return 'no-game';
    let latest;
    for (const message of messages) {
      if (message.role !== 'user' || message.sessionId !== sessionId || message.epoch !== epoch) continue;
      latest = message;
    }
    return discussionScene(latest?.text, latest?.capability || latest?.metadata?.capability);
  }
  function sourceFor(scene, failed = new Set()) {
    return Object.hasOwn(sources, scene) && !failed.has(scene) ? sources[scene] : sources.default;
  }
  return { sources, discussionScene, selectScene, sourceFor };
});
