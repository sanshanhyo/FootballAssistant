'use strict';
// Independent process: never trust builder's exit handling or a green outer step.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
function assertEvidence(data) {
  for (const flag of ['passed', 'actualNativeInstaller', 'actualDownload', 'actualRelaunch', 'settingsPreserved', 'healthAcknowledged']) assert.equal(data[flag], true, `Missing positive evidence: ${flag}`);
  assert.equal(data.initialVersion, '0.0.1-alpha.1'); assert.equal(data.targetVersion, '0.0.2-alpha.1');
  assert.equal(data.productionReadiness, false); assert.equal(data.authenticodeValidated, false);
  assert.ok(Array.isArray(data.events)); assert.ok(Array.isArray(data.requests));
  assert.ok(data.events.some(e => e.step === 'launch' && e.appVersion === data.initialVersion));
  assert.ok(data.events.some(e => e.step === 'launch' && e.appVersion === data.targetVersion && e.argvUpdated === true && e.recovery === 'awaiting_health'));
  assert.ok(data.events.some(e => e.step === 'target_healthy' && e.appVersion === data.targetVersion && e.settingsPreserved === true && e.recovery === 'healthy'));
  assert.ok(data.requests.some(r => r.method === 'GET' && r.path.endsWith('.exe')));
  return true;
}
if (require.main === module) {
  try {
    if (!process.env.RUNNER_TEMP) throw Error('Missing disposable runner evidence directory');
    assertEvidence(JSON.parse(fs.readFileSync(path.join(process.env.RUNNER_TEMP, 'companion-smoke-update-fixture.json'), 'utf8')));
    console.log('Verified actual two-version HTTP download, NSIS relaunch, retained settings and healthy journal evidence.');
  } catch (error) { console.error(`Native update evidence validation failed: ${error.message}`); process.exit(1); }
}
module.exports = { assertEvidence };
