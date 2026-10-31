'use strict';
// PUBLIC trust only. User-approved Windows Ed25519 policy (2026-10-31).
// Private signing material lives only in the owner's private key store and the
// protected FA_ALPHA_UPDATE_SIGNING_KEY Actions Secret; never in the application.
// This authenticates our release channel, not a Windows Authenticode publisher.
// SmartScreen/AppLocker/WDAC remain unchanged and may warn or block execution.
module.exports = Object.freeze({
  productionTrust: Object.freeze({
    trustPolicy: 'ed25519-pinned',
    publicKey: '-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAqkem81H85RqVbk63GZSRR+FirweOMbMvUwsXkNmByf0=\n-----END PUBLIC KEY-----\n',
    publicKeySpkiSha256: '9e686e777a355634920d5dbf6e63bc282dfc8622ff480a75803b9040538bccfb'
  }),
  feedUrl: 'https://github.com/sanshanhyo/FootballAssistant/releases/download/alpha-channel/alpha-update.json'
});
