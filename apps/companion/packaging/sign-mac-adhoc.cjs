'use strict';
const path = require('node:path');
const fs = require('node:fs/promises');
// Re-sign only our assembled artifact, not a user's app, game or OS component.
// Ad-hoc signs bundle structure; it is NOT Developer ID or Apple notarization.
async function signBuiltMac({ platform = process.platform, sign = options => require('@electron/osx-sign').signAsync(options) } = {}) {
  if (platform !== 'darwin') throw new Error('Ad-hoc bundle signing requires the macOS build runner');
  const app = path.resolve(__dirname, '..', 'dist', 'mac-arm64', 'FootballAssistant.app');
  const info = await fs.lstat(app);
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error('Expected our regular built App directory');
  await sign({ app, platform: 'darwin', identity: '-', identityValidation: false,
    type: 'development', strictVerify: true, preEmbedProvisioningProfile: false, preAutoEntitlements: false,
    optionsForFile: () => ({ hardenedRuntime: true, entitlements: path.join(__dirname, 'entitlements.mac.adhoc.plist') }) });
  process.stdout.write('Built macOS App ad-hoc signature integrity verified; not Developer ID signed or notarized.\n');
}
if (require.main === module) signBuiltMac().catch(error => { console.error(error.message); process.exitCode = 1; });
module.exports = { signBuiltMac };
