'use strict';
// Manual release-preparation only. This script never publishes or generates keys.
// The signing key arrives via protected Actions Secret; never log it or write it.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { compareVersions } = require('../src/update-security.cjs');
async function main() {
  const appRoot = path.resolve(__dirname, '..');
  const { version } = JSON.parse(fs.readFileSync(path.join(appRoot, 'package.json'), 'utf8'));
  compareVersions(version, version);
  if (!/^[0-9]+\.[0-9]+\.[0-9]+-alpha\.[0-9]+$/.test(version)) throw Error('Alpha version required');
  const trust = require('../src/update-trust.cjs');
  if (!trust.productionTrust?.publicKey || !process.env.FA_ALPHA_UPDATE_SIGNING_KEY) throw Error('Reviewed public key and signing secret are required');
  const privateKey = crypto.createPrivateKey(process.env.FA_ALPHA_UPDATE_SIGNING_KEY);
  if (privateKey.asymmetricKeyType !== 'ed25519') throw Error('Ed25519 signing key required');
  const publicDer = crypto.createPublicKey(privateKey).export({ type: 'spki', format: 'der' });
  const pinnedDer = crypto.createPublicKey(trust.productionTrust.publicKey).export({ type: 'spki', format: 'der' });
  if (!publicDer.equals(pinnedDer)) throw Error('Signing key does not match the reviewed client public key');
  const name = `FootballAssistant-${version}-Setup-x64.exe`;
  const artifact = path.join(appRoot, 'dist', name);
  const stat = fs.lstatSync(artifact);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size <= 0 || stat.size > 2 * 1024 ** 3) throw Error('Expected bounded regular NSIS installer');
  const digest = crypto.createHash('sha256');
  for await (const chunk of fs.createReadStream(artifact)) digest.update(chunk);
  const payload = JSON.stringify({ schema: 1, channel: 'alpha', version,
    expiresAt: new Date(Date.now() + 14 * 86400000).toISOString(), configSchemas: [1], backendProtocol: 1, bridgeProtocol: 1,
    artifacts: [{ platform: 'win32', arch: 'x64', format: 'exe', installerType: 'nsis', size: stat.size,
      sha256: digest.digest('hex'), url: `https://github.com/sanshanhyo/FootballAssistant/releases/download/${version}/${name}` }] });
  const signature = crypto.sign(null, Buffer.from(payload), privateKey).toString('base64');
  fs.writeFileSync(path.join(appRoot, 'dist', 'alpha-update.json'), JSON.stringify({ payload, signature }) + '\n', { mode: 0o600 });
  // Only public release metadata, never key material.
  process.stdout.write(`Signed Alpha manifest prepared for ${version}; not published.\n`);
}
main().catch(() => { process.stderr.write('Alpha manifest signing failed; verify reviewed trust configuration, installer and protected signing secret.\n'); process.exitCode = 1; });
