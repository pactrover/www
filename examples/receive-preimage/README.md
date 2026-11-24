# Test a `receive.json` serializer, not just its hash

Hashing a preprinted string can match the expected SHA-256 even if your serializer emits different bytes. In the [AgentsHelp receive manifest discussion](https://tools.nyrds.net/board/thread/2811.json), two readers found that a `receive.json` example was easier to reproduce if the construction order was explicit.

This small offline test uses the placeholder entry and expected values published in [`receive.json`](https://agentshelp.me/receive.json), observed on November 24, 2026. It includes **no real payment destination**. Run the following from the repository root with Node.js (no packages, credentials, or network access required; tested with Node.js 26.12.1):

```sh
node --test examples/receive-preimage/preimage.test.mjs
```

To check your own implementation against [`example.json`](example.json):

1. Start with `entry`, **not** the printed `preimage`. Sort the object's keys, keep the explicit `null` values, and serialize compactly. The fixture has flat ASCII keys and scalar values.
2. Wrap that object in a one-element JSON array. Compare the rebuilt UTF-8 bytes directly with the bytes of `preimage`. Do not add a trailing newline.
3. Only after the bytes match, hash the rebuilt bytes with SHA-256 and compare the lowercase hex with `sha256`.

The tests separate hashing the printed bytes from rebuilding them. A serializer that preserves the fixture's input key order fails the byte comparison even while the printed digest check passes. Omitting array brackets or dropping null-valued fields also fails.

This is one test vector, not a general canonical JSON implementation or a verifier for the full manifest. It does not check sorting across multiple entries, non-ASCII input, live DNS, freshness, or recipient identity. It provides no basis for sending funds.
