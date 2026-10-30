'use strict';

/**
 * A character's stable identity and its current built-in visual reference.
 * Character/package versions are deliberately separate from the UI storage version.
 * @typedef {Readonly<{characterId: string, displayName: string, englishName: string, visualResource: string}>} CharacterDefinition
 */

const DEFAULT_CHARACTER_ID = 'official.eckera';

/** @type {CharacterDefinition} */
const DEFAULT_CHARACTER = Object.freeze({
  characterId: DEFAULT_CHARACTER_ID,
  displayName: '埃克拉',
  englishName: 'Eckera',
  visualResource: 'builtin.companion-placeholder',
});

const PLACEHOLDER_VISUAL = Object.freeze({
  kind: 'css-placeholder',
  resourceKey: 'companion-placeholder',
  label: '占位视觉',
});

// References are opaque built-in keys, never paths, URLs, scripts or permissions.
function getBuiltinVisualResource(reference) {
  return reference === DEFAULT_CHARACTER.visualResource ? PLACEHOLDER_VISUAL : null;
}

function storedCharacterId(value) {
  return typeof value === 'string' && value.trim() ? value : DEFAULT_CHARACTER_ID;
}

function characterPresentation(value) {
  const requestedCharacterId = storedCharacterId(value);
  return {
    ...DEFAULT_CHARACTER,
    requestedCharacterId,
    fallback: requestedCharacterId !== DEFAULT_CHARACTER_ID,
    visual: getBuiltinVisualResource(DEFAULT_CHARACTER.visualResource),
  };
}

module.exports = { DEFAULT_CHARACTER_ID, DEFAULT_CHARACTER, getBuiltinVisualResource, storedCharacterId, characterPresentation };
