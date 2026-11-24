import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const vector = JSON.parse(readFileSync(new URL('./example.json', import.meta.url), 'utf8'));
const bytes = text => Buffer.from(text, 'utf8');
const sha256 = input => createHash('sha256').update(input).digest('hex');

// This handles the single flat example, not arbitrary JSON or a full manifest.
function canonicalEntry(entry) {
  return `{${Object.keys(entry).sort().map(key =>
    `${JSON.stringify(key)}:${JSON.stringify(entry[key])}`).join(',')}}`;
}
const rebuild = entry => `[${canonicalEntry(entry)}]`;

function checkPreimage(build, entry = vector.entry, expectedHash = vector.sha256) {
  const actual = bytes(build(entry));
  assert.ok(actual.equals(bytes(vector.preimage)), 'rebuilt UTF-8 preimage differs');
  assert.equal(sha256(actual), expectedHash, 'rebuilt SHA-256 differs');
}

test('the printed bytes match the published SHA-256 (digest-only check)', () => {
  assert.equal(sha256(bytes(vector.preimage)), vector.sha256);
});

test('sorting keys and adding the array brackets rebuilds the exact UTF-8 bytes', () => {
  checkPreimage(rebuild);
  checkPreimage(rebuild, Object.fromEntries(Object.entries(vector.entry).reverse()));
});

test('the digest-only success cannot hide an insertion-order serializer', () => {
  assert.throws(() => checkPreimage(entry => JSON.stringify([entry])), /preimage differs/);
});

test('the canonical object without array brackets is not the preimage', () => {
  assert.throws(() => checkPreimage(canonicalEntry), /preimage differs/);
});

test('explicit JSON null members cannot be dropped', () => {
  const withoutNulls = Object.fromEntries(Object.entries(vector.entry).filter(([, value]) => value !== null));
  assert.throws(() => checkPreimage(rebuild, withoutNulls), /preimage differs/);
});

test('matching bytes are checked against the expected digest separately', () => {
  assert.throws(() => checkPreimage(rebuild, vector.entry, '0'.repeat(64)), /SHA-256 differs/);
});
