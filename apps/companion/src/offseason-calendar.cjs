'use strict';
// Only explicit club-scoped ranges are supported; loaded buckets are not a complete calendar.
function calendarEndpoint(clubUid, start, end) {
  if (!Number.isSafeInteger(clubUid) || clubUid <= 0 || clubUid >= 4294967295) throw new Error('Invalid club UID');
  const parse = value => {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error('Invalid calendar date');
    const date = new Date(value + 'T00:00:00Z');
    if (!Number.isFinite(date.valueOf()) || date.toISOString().slice(0, 10) !== value || date.getUTCFullYear() < 1901 || date.getUTCFullYear() > 2100) throw new Error('Invalid calendar date');
    return date;
  };
  const first = parse(start), last = parse(end);
  const days = (last - first) / 86400000;
  if (first.getUTCFullYear() !== last.getUTCFullYear() || days < 0 || days >= 30) throw new Error('Invalid calendar range');
  return `/v1/reader/offseason?club_uid=${clubUid}&start=${start}&end=${end}`;
}
function isCalendarEndpoint(endpoint) {
  if (typeof endpoint !== 'string') return false;
  const match = /^\/v1\/reader\/offseason\?club_uid=([1-9]\d{0,9})&start=(\d{4}-\d{2}-\d{2})&end=(\d{4}-\d{2}-\d{2})$/.exec(endpoint);
  if (!match) return false;
  try { return calendarEndpoint(Number(match[1]), match[2], match[3]) === endpoint; } catch { return false; }
}
module.exports = { calendarEndpoint, isCalendarEndpoint };
