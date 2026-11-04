'use strict';
// Intentionally narrow data-only ZIP format: stored/deflated, non-ZIP64,
// non-encrypted entries with sizes in local headers (no data descriptors).
const zlib = require('node:zlib');
const LIMITS = Object.freeze({ archive: 16 * 1024 * 1024, unpacked: 32 * 1024 * 1024, entries: 8, dimension: 4096, pixels: 16_000_000 });
const FILES = new Set(['manifest.json', 'persona.md', 'assets/portrait.png']);
const CRC_TABLE = Array.from({ length: 256 }, (_, n) => { for (let k = 0; k < 8; k++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1; return n >>> 0; });
function crc32(bytes) { let n = 0xffffffff; for (const byte of bytes) n = CRC_TABLE[(n ^ byte) & 255] ^ (n >>> 8); return (n ^ 0xffffffff) >>> 0; }
function reject(message) { throw Error(`Invalid character package: ${message}`); }
function boundedInflate(bytes, size, raw = false) {
  try {
    const result = (raw ? zlib.inflateRawSync : zlib.inflateSync)(bytes, { maxOutputLength: Math.max(1, size), info: true });
    if (result.buffer.length !== size || result.engine.bytesWritten !== bytes.length) reject('compressed length mismatch');
    return result.buffer;
  } catch (error) { reject(`invalid or oversized compressed data (${error.code || 'format'})`); }
}
function validatePng(bytes) {
  if (!Buffer.isBuffer(bytes) || bytes.length > LIMITS.unpacked || bytes.length < 57 || !bytes.subarray(0, 8).equals(Buffer.from('89504e470d0a1a0a', 'hex'))) reject('invalid PNG signature');
  let at = 8, header = null, ended = false, seenData = false, closedData = false, seenPalette = false;
  const data = [];
  while (at < bytes.length) {
    if (at + 12 > bytes.length) reject('truncated PNG chunk');
    const length = bytes.readUInt32BE(at), end = at + 12 + length;
    if (end > bytes.length) reject('truncated PNG payload');
    const kind = bytes.toString('latin1', at + 4, at + 8);
    if (!/^[A-Za-z]{4}$/.test(kind) || kind[2] !== kind[2].toUpperCase()) reject('invalid PNG chunk type');
    if (crc32(bytes.subarray(at + 4, end - 4)) !== bytes.readUInt32BE(end - 4)) reject('PNG CRC mismatch');
    const payload = bytes.subarray(at + 8, end - 4);
    if (!header && kind !== 'IHDR') reject('PNG must start with IHDR');
    if (kind === 'IHDR') {
      if (header || length !== 13) reject('invalid PNG header');
      const width = payload.readUInt32BE(0), height = payload.readUInt32BE(4), color = payload[9];
      if (!width || !height || width > LIMITS.dimension || height > LIMITS.dimension || width * height > LIMITS.pixels) reject('PNG dimensions exceed limit');
      // Narrow interoperable first-version image contract; no APNG/interlacing.
      if (payload[8] !== 8 || ![2, 6].includes(color) || payload[10] || payload[11] || payload[12]) reject('PNG requires noninterlaced 8-bit RGB/RGBA');
      header = { width, height, channels: color === 6 ? 4 : 3 };
    } else if (kind === 'IDAT') {
      if (closedData) reject('PNG IDAT chunks must be consecutive');
      seenData = true; data.push(payload);
    } else if (kind === 'IEND') {
      if (length || !seenData || end !== bytes.length) reject('invalid PNG ending');
      ended = true;
    } else {
      if (seenData) closedData = true;
      // Strip neither metadata nor content silently. Reject executable/animated or
      // unknown critical extensions; ordinary ancillary metadata remains inert.
      if (['acTL', 'fcTL', 'fdAT'].includes(kind) || (kind[0] === kind[0].toUpperCase() && kind !== 'PLTE')) reject('unsupported PNG extension');
      if (kind === 'PLTE') {
        if (seenPalette || seenData || length === 0 || length > 768 || length % 3) reject('invalid PNG palette');
        seenPalette = true;
      }
    }
    at = end;
  }
  if (!ended) reject('PNG missing IEND');
  const stride = header.width * header.channels + 1;
  const pixels = boundedInflate(Buffer.concat(data), stride * header.height);
  for (let row = 0; row < header.height; row++) if (pixels[row * stride] > 4) reject('invalid PNG scanline filter');
  return Object.freeze({ width: header.width, height: header.height });
}
function parseCharacterZip(bytes) {
  if (!Buffer.isBuffer(bytes) || bytes.length < 22 || bytes.length > LIMITS.archive) reject('archive size limit');
  // No archive comments: deterministic EOCD avoids ambiguous appended archives.
  const eocd = bytes.length - 22;
  if (bytes.readUInt32LE(eocd) !== 0x06054b50 || bytes.readUInt16LE(eocd + 20)) reject('missing ZIP end record or archive comment');
  const count = bytes.readUInt16LE(eocd + 10), centralSize = bytes.readUInt32LE(eocd + 12), centralAt = bytes.readUInt32LE(eocd + 16);
  if (bytes.readUInt16LE(eocd + 4) || bytes.readUInt16LE(eocd + 6) || bytes.readUInt16LE(eocd + 8) !== count || count < 3 || count > LIMITS.entries || centralAt + centralSize !== eocd) reject('unsupported ZIP layout');
  let at = centralAt, total = 0;
  const names = new Set(), output = new Map(), ranges = [];
  for (let i = 0; i < count; i++) {
    if (at + 46 > eocd || bytes.readUInt32LE(at) !== 0x02014b50) reject('invalid ZIP directory');
    const flags = bytes.readUInt16LE(at + 8), method = bytes.readUInt16LE(at + 10), crc = bytes.readUInt32LE(at + 16);
    const compressed = bytes.readUInt32LE(at + 20), size = bytes.readUInt32LE(at + 24), nameLength = bytes.readUInt16LE(at + 28), extraLength = bytes.readUInt16LE(at + 30), commentLength = bytes.readUInt16LE(at + 32), local = bytes.readUInt32LE(at + 42);
    if (flags & ~0x800 || ![0, 8].includes(method) || bytes.readUInt16LE(at + 6) > 20 || bytes.readUInt16LE(at + 34) || [compressed, size, local].includes(0xffffffff)) reject('unsupported ZIP flags, method or version');
    const end = at + 46 + nameLength + extraLength + commentLength;
    if (end > eocd || !nameLength) reject('invalid ZIP entry length');
    const nameBytes = bytes.subarray(at + 46, at + 46 + nameLength);
    let name;
    try { name = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(nameBytes); } catch { reject('invalid UTF-8 filename'); }
    const folded = name.normalize('NFC').toLowerCase();
    if (names.has(folded)) reject('duplicate or colliding filename');
    names.add(folded);
    if (!(FILES.has(name) || name === 'assets/')) reject('unexpected file or unsafe path');
    // Check all Unix file types regardless of creator OS; reject DOS reparse bits.
    const attrs = bytes.readUInt32LE(at + 38), type = (attrs >>> 16) & 0xf000, directory = name.endsWith('/');
    if ((type && type !== (directory ? 0x4000 : 0x8000)) || (attrs & 0x400) || (!directory && (attrs & 0x10))) reject('links or special entries forbidden');
    // Reject extras entirely: avoids ZIP64, Unix links and conflicting Unicode paths.
    if (extraLength || commentLength) reject('ZIP extra fields and comments are unsupported');
    total += size;
    if (total > LIMITS.unpacked || size > LIMITS.unpacked || compressed > LIMITS.archive || (directory && size)) reject('expanded archive size limit');
    if (local + 30 > centralAt || bytes.readUInt32LE(local) !== 0x04034b50) reject('invalid local header');
    const localNameLength = bytes.readUInt16LE(local + 26), localExtra = bytes.readUInt16LE(local + 28), start = local + 30 + localNameLength + localExtra, finish = start + compressed;
    if (finish > centralAt || localExtra || localNameLength !== nameLength || !bytes.subarray(local + 30, start).equals(nameBytes) || bytes.readUInt16LE(local + 4) > 20 || bytes.readUInt16LE(local + 6) !== flags || bytes.readUInt16LE(local + 8) !== method || bytes.readUInt32LE(local + 14) !== crc || bytes.readUInt32LE(local + 18) !== compressed || bytes.readUInt32LE(local + 22) !== size) reject('local and central header mismatch');
    ranges.push([local, finish]);
    const packed = bytes.subarray(start, finish);
    const payload = method === 8 ? boundedInflate(packed, size, true) : Buffer.from(packed);
    if (payload.length !== size || crc32(payload) !== crc) reject('ZIP CRC or size mismatch');
    if (!directory) output.set(name, payload);
    at = end;
  }
  ranges.sort((a, b) => a[0] - b[0]);
  let cursor = 0;
  for (const [start, end] of ranges) { if (start !== cursor) reject('overlapping entries or hidden ZIP content'); cursor = end; }
  if (cursor !== centralAt || at !== eocd || output.size !== FILES.size || [...FILES].some(name => !output.has(name))) reject('incomplete or ambiguous package');
  validatePng(output.get('assets/portrait.png'));
  return output;
}
module.exports = { parseCharacterZip, validatePng, LIMITS };
