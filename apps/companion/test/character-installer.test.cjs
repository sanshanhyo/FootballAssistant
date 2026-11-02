'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const zlib = require('node:zlib');
const { parseCharacterZip, validatePng, LIMITS } = require('../src/character-installer.cjs');
function crc32(bytes) { let crc = 0xffffffff; for (const b of bytes) { crc ^= b; for (let k = 0; k < 8; k++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0); } return (crc ^ 0xffffffff) >>> 0; }
function chunk(type, data) { const out = Buffer.alloc(12 + data.length); out.writeUInt32BE(data.length); out.write(type, 4); data.copy(out, 8); out.writeUInt32BE(crc32(out.subarray(4, out.length - 4)), out.length - 4); return out; }
function png({ width = 1, height = 1, filter = 0, raw, color = 6, interlace = 0 } = {}) {
  const header = Buffer.alloc(13); header.writeUInt32BE(width); header.writeUInt32BE(height, 4); header[8] = 8; header[9] = color; header[12] = interlace;
  return Buffer.concat([Buffer.from('89504e470d0a1a0a', 'hex'), chunk('IHDR', header), chunk('IDAT', zlib.deflateSync(raw || Buffer.from([filter, 1, 2, 3, 255]))), chunk('IEND', Buffer.alloc(0))]);
}
const normal = () => [{ name: 'manifest.json', data: Buffer.from('{}') }, { name: 'persona.md', data: Buffer.from('Friendly football companion') }, { name: 'assets/portrait.png', data: png() }];
function zip(entries, method = 8) {
  const locals = [], centrals = []; let offset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.name), data = entry.data || Buffer.alloc(0), packed = method === 8 ? zlib.deflateRawSync(data) : data;
    const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50); local.writeUInt16LE(20, 4); local.writeUInt16LE(method, 8); local.writeUInt32LE(crc32(data), 14); local.writeUInt32LE(packed.length, 18); local.writeUInt32LE(data.length, 22); local.writeUInt16LE(name.length, 26);
    const central = Buffer.alloc(46); central.writeUInt32LE(0x02014b50); central.writeUInt16LE(0x314, 4); central.writeUInt16LE(20, 6); central.writeUInt16LE(method, 10); central.writeUInt32LE(crc32(data), 16); central.writeUInt32LE(packed.length, 20); central.writeUInt32LE(data.length, 24); central.writeUInt16LE(name.length, 28); central.writeUInt32LE(entry.attrs ?? (0x81a4 * 65536), 38); central.writeUInt32LE(offset, 42);
    locals.push(local, name, packed); centrals.push(central, name); offset += local.length + name.length + packed.length;
  }
  const central = Buffer.concat(centrals), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(central.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, central, end]);
}
function centralAt(buffer) { return buffer.readUInt32LE(buffer.length - 6); }
test('valid stored and deflated packages return owned data buffers', () => {
  for (const method of [0, 8]) {
    const archive = zip(normal(), method), files = parseCharacterZip(archive);
    assert.equal(files.size, 3); assert.equal(files.get('persona.md').toString(), 'Friendly football companion');
    assert.deepEqual(validatePng(files.get('assets/portrait.png')), { width: 1, height: 1 });
    archive.fill(0); assert.equal(files.get('manifest.json').toString(), '{}');
  }
});
test('optional regular assets directory is accepted', () => {
  const entries = normal(); entries.unshift({ name: 'assets/', attrs: 0x41ed * 65536 + 0x10 });
  assert.equal(parseCharacterZip(zip(entries)).size, 3);
});
test('rejects traversal, absolute, backslash, alternate stream, unicode and unexpected executable names', () => {
  for (const name of ['\ufeffpersona.md', '../persona.md', '/persona.md', 'C:/persona.md', 'assets\\portrait.png', 'assets/../portrait.png', 'persona.md:script', 'personа.md', 'run.js', 'credentials.json', 'http://evil.test/x']) {
    const entries = normal(); entries[1].name = name; assert.throws(() => parseCharacterZip(zip(entries)), /Invalid character package/);
  }
});
test('rejects exact and case-insensitive duplicate entries', () => {
  for (const name of ['persona.md', 'PERSONA.MD']) assert.throws(() => parseCharacterZip(zip([...normal(), { name, data: Buffer.from('x') }])), /colliding/);
});
test('rejects symlink, device, directory-file mismatch and reparse attributes', () => {
  for (const attrs of [0xa1ff * 65536, 0x21ff * 65536, 0x41ed * 65536, 0x400, 0x10]) {
    const entries = normal(); entries[1].attrs = attrs; assert.throws(() => parseCharacterZip(zip(entries)), /links or special/);
  }
});
test('rejects unsupported methods, encryption, descriptors and ZIP64 sizes', () => {
  for (const flags of [1, 8, 0x40]) { const b = zip(normal()); b.writeUInt16LE(flags, centralAt(b) + 8); assert.throws(() => parseCharacterZip(b), /unsupported ZIP/); }
  { const b = zip(normal()); b.writeUInt16LE(99, centralAt(b) + 10); assert.throws(() => parseCharacterZip(b), /unsupported ZIP/); }
  { const b = zip(normal()); b.writeUInt32LE(0xffffffff, centralAt(b) + 24); assert.throws(() => parseCharacterZip(b), /unsupported ZIP/); }
});
test('rejects local/central mismatch, corruption, overlapping and appended archives', () => {
  { const b = zip(normal()); b[14] ^= 1; assert.throws(() => parseCharacterZip(b), /header mismatch/); }
  { const b = zip(normal(), 0); b[30 + 'manifest.json'.length] ^= 1; assert.throws(() => parseCharacterZip(b), /CRC/); }
  { const b = zip(normal()); const second = centralAt(b) + 46 + 'manifest.json'.length; b.writeUInt32LE(0, second + 42); assert.throws(() => parseCharacterZip(b)); }
  assert.throws(() => parseCharacterZip(Buffer.concat([zip(normal()), Buffer.from('junk')])));
  assert.throws(() => parseCharacterZip(zip(normal()).subarray(0, 80)));
});
test('enforces archive, entry-count and actual expanded-data limits', () => {
  assert.throws(() => parseCharacterZip(Buffer.alloc(LIMITS.archive + 1)), /size limit/);
  assert.throws(() => parseCharacterZip(zip([...normal(), ...Array.from({ length: 6 }, (_, i) => ({ name: `${i}.txt` }))])), /layout/);
  const entries = normal(); entries[1].data = Buffer.alloc(1024 * 1024, 65); const b = zip(entries), c = centralAt(b) + 46 + 'manifest.json'.length;
  const local = b.readUInt32LE(c + 42); b.writeUInt32LE(8, c + 24); b.writeUInt32LE(8, local + 22);
  assert.throws(() => parseCharacterZip(b), /oversized compressed/);
  const oversize = zip(normal()); oversize.writeUInt32LE(LIMITS.unpacked + 1, centralAt(oversize) + 24);
  assert.throws(() => parseCharacterZip(oversize), /expanded archive/);
});
test('PNG rejects bad signature, CRC, dimensions, scanlines, truncation and trailing data', () => {
  const signature = png(); signature[0] = 0; assert.throws(() => validatePng(signature), /signature/);
  const crc = png(); crc[29] ^= 1; assert.throws(() => validatePng(crc), /CRC/);
  for (const options of [{ width: 0 }, { width: 5000 }, { width: 4096, height: 4096 }]) assert.throws(() => validatePng(png(options)), /dimensions/);
  assert.throws(() => validatePng(png({ filter: 5 })), /scanline/);
  assert.throws(() => validatePng(png({ raw: Buffer.alloc(500) })), /oversized compressed/);
  assert.throws(() => validatePng(png({ interlace: 1 })), /noninterlaced/);
  assert.throws(() => validatePng(png({ color: 3 })), /RGB/);
  assert.throws(() => validatePng(png().subarray(0, -1)));
  assert.throws(() => validatePng(Buffer.concat([png(), Buffer.from('x')])), /ending/);
});
test('PNG rejects animated and unknown critical chunks', () => {
  const base = png(), header = base.subarray(0, 33), tail = base.subarray(33);
  for (const name of ['acTL', 'ABCD']) assert.throws(() => validatePng(Buffer.concat([header, chunk(name, Buffer.alloc(8)), tail])), /unsupported PNG/);
});

test('PNG rejects duplicate palettes and trailing compressed streams', () => {
  const base = png(), header = base.subarray(0, 33), tail = base.subarray(33);
  const palette = chunk('PLTE', Buffer.from([0, 0, 0]));
  assert.throws(() => validatePng(Buffer.concat([header, palette, palette, tail])), /palette/);
  const compressed = Buffer.concat([zlib.deflateSync(Buffer.from([0, 0, 0, 0, 255])), zlib.deflateSync(Buffer.from([1]))]);
  assert.throws(() => validatePng(Buffer.concat([header, chunk('IDAT', compressed), chunk('IEND', Buffer.alloc(0))])), /compressed/);
});
