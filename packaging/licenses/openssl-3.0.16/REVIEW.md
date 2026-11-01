# OpenSSL 3.0.16: bounded macOS runtime notice review

The inspected macOS artifact's bundled `libcrypto.3.dylib` contains the version
string `OpenSSL 3.0.16 11 Feb 2025`. Its companion `libssl.3.dylib` is in the same
backend directory. These are Python runtime libraries, not Chromium/BoringSSL.
The observed signed-artifact SHA-256 values were:

- libcrypto.3.dylib: `b0870cfab796f3bece2020eb0f1dc238066ba8ddcda2af46fc56d94381819539`
- libssl.3.dylib: `cb7e1ca42b1c46292d833ae6dd37d2f40f52624b93080431821afd3ce3921e09`

The adjacent LICENSE, AUTHORS, ACKNOWLEDGEMENTS and README are unchanged upstream
files from the exact `openssl-3.0.16` tag. URLs and SHA-256 values are recorded in
`provenance.json`. The checked upstream root has no separate NOTICE file. This
retains its Apache-2.0 text and attribution without inventing upstream notices.
It is not a complete review of every optional component, patch or native dependency.

The collector accepts this fallback only for a same-directory macOS runtime pair
with an unambiguous 3.0.16 version marker. Other versions require review. It
records the actual build-input library hashes; signing can change dylib bytes,
so those hashes are not treated as expected post-signing hashes. Notice file
hashes are checked both when collecting and against the final backend manifest.
All other unresolved native distribution/source obligations remain open.

## Separate security issue: not resolved by retaining licenses

OpenSSL 3.0 reached public end of life on 2026-09-07:
https://openssl-library.org/post/2026-09-16-eol30/

Official later advisories include High-severity issues affecting 3.0.16:

- CVE-2025-15467, fixed in 3.0.19: untrusted CMS/PKCS#7 AEAD EnvelopedData parsing.
  https://openssl-library.org/news/secadv/20260127.txt
- CVE-2026-45447, fixed in 3.0.21: PKCS7_verify on malicious PKCS#7/S/MIME input.
  https://openssl-library.org/news/secadv/20260609.txt
- CVE-2026-84782, fixed in extended-support 3.0.23: a DTLS retransmission path.
  https://openssl-library.org/news/secadv/20260929.txt

Those paths are not implied merely by using Python HTTPS. The last advisory also
lists CVE-2026-35189 (Low), malicious certificate CRLDP processing during ordinary
TLS handshakes causing memory pressure/DoS. Exposure through configured endpoints,
proxies and dependencies is not established by this notice review. No exploit or
compromise has been demonstrated. A supported runtime/security-update plan needs
separate review before production release; no runtime is upgraded by this change.
