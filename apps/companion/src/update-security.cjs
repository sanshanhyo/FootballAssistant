'use strict';
const crypto = require('node:crypto');
const REPOSITORY = 'sanshanhyo/FootballAssistant';
const PREFIX = `/${REPOSITORY}/releases/download/`;
function trustedReleaseUrl(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.hostname !== 'github.com' || url.port || url.username || url.password || url.search || url.hash || !url.pathname.startsWith(PREFIX) || url.pathname.slice(PREFIX.length).split('/').length !== 2 || /%|\\/.test(url.pathname)) throw new Error('Untrusted release URL');
  return url.href;
}
function versionParts(value) {
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-alpha\.(0|[1-9]\d*))?$/.exec(value);
  if (!match || match.slice(1).filter(Boolean).some(x => !Number.isSafeInteger(Number(x)))) throw new Error('Unsupported version; use X.Y.Z or X.Y.Z-alpha.N');
  return [Number(match[1]), Number(match[2]), Number(match[3]), match[4] === undefined ? Infinity : Number(match[4])];
}
function compareVersions(a, b) {
  const left = versionParts(a), right = versionParts(b);
  for (let i = 0; i < left.length; i++) if (left[i] !== right[i]) return left[i] > right[i] ? 1 : -1;
  return 0;
}
function verifyManifest(envelope, publicKey, context) {
  if (!envelope || typeof envelope.payload !== 'string' || typeof envelope.signature !== 'string') throw new Error('Missing signed manifest');
  const key = crypto.createPublicKey(publicKey);
  if (key.asymmetricKeyType !== 'ed25519' || !crypto.verify(null, Buffer.from(envelope.payload, 'utf8'), key, Buffer.from(envelope.signature, 'base64'))) throw new Error('Invalid manifest signature');
  const manifest = JSON.parse(envelope.payload);
  if (manifest.schema !== 1 || manifest.channel !== 'alpha') throw new Error('Unsupported update manifest');
  const comparison = compareVersions(manifest.version, context.currentVersion);
  if (comparison < 0) throw new Error('Update is older (downgrade rejected)');
  if (!Number.isFinite(Date.parse(manifest.expiresAt)) || Date.parse(manifest.expiresAt) <= (context.now ?? Date.now())) throw new Error('Update manifest expired');
  // A package may migrate configuration, but only from explicitly accepted schemas.
  if (![context.configSchema, context.backendProtocol, context.bridgeProtocol, manifest.backendProtocol, manifest.bridgeProtocol].every(Number.isSafeInteger) || !Array.isArray(manifest.configSchemas) || !manifest.configSchemas.includes(context.configSchema) || manifest.backendProtocol !== context.backendProtocol || manifest.bridgeProtocol !== context.bridgeProtocol) throw new Error('Incompatible config or protocol; coordinated migration required');
  if (!Array.isArray(manifest.artifacts)) throw new Error('Missing update artifacts');
  const matches = manifest.artifacts.filter(a => a.platform === context.platform && a.arch === context.arch);
  if (matches.length !== 1) throw new Error('No unique artifact for this platform/architecture');
  const artifact = matches[0];
  trustedReleaseUrl(artifact.url);
  if (!/^[a-f0-9]{64}$/.test(artifact.sha256) || !Number.isSafeInteger(artifact.size) || artifact.size <= 0 || artifact.size > 2 * 1024 ** 3) throw new Error('Invalid artifact digest/size');
  if (!['zip', 'dmg', 'exe'].includes(artifact.format)) throw new Error('Unsupported artifact format');
  return { isCurrent: comparison === 0, version: manifest.version, expiresAt: manifest.expiresAt, artifact, releaseUrl: `https://github.com/${REPOSITORY}/releases/tag/${encodeURIComponent(manifest.version)}` };
}
module.exports = { REPOSITORY, trustedReleaseUrl, compareVersions, verifyManifest };
