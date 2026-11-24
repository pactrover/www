/* Hash adapter for the pinned Nano node's Ed25519 verification routine.
 * For public signature verification only; private-key operations are unsupported. */
#include <stdint.h>
#include <stdlib.h>
#include <crypto/ed25519-donna/ed25519-hash-custom.h>

void ed25519_hash_init(ed25519_hash_context *ctx) {
    if (blake2b_init(ctx, 64) != 0) abort();
}

void ed25519_hash_update(ed25519_hash_context *ctx, const uint8_t *in, size_t size) {
    if (blake2b_update(ctx, in, size) != 0) abort();
}

void ed25519_hash_final(ed25519_hash_context *ctx, uint8_t *out) {
    if (blake2b_final(ctx, out, 64) != 0) abort();
}

void ed25519_hash(uint8_t *out, const uint8_t *in, size_t size) {
    ed25519_hash_context ctx;
    ed25519_hash_init(&ctx);
    ed25519_hash_update(&ctx, in, size);
    ed25519_hash_final(&ctx, out);
}

void ed25519_randombytes_unsafe(void *out, size_t size) {
    /* Single-signature verification never needs randomness. */
    (void)out;
    (void)size;
    abort();
}
