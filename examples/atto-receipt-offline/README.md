# Replay one ATTO payout without network access

[NovaCraft Studio's independent Linux replay](https://github.com/pactrover/www/issues/4#issuecomment-7129655194) could verify a Marketplace signature, but a native Atto lookup returned HTTP 403 and stopped the live snapshot. This example lets a reader check **one saved ATTO payment** even if the endpoints cannot be reached. It does not bypass access controls or reproduce the live snapshot. Pactrover commissioned LLMRT’s code count and assembled this bundle; it is not a separate independent assessment.

After obtaining this repository, run from its root with Python 3 and OpenSSL 3:

```sh
python3 examples/atto-receipt/verify.py --case llmrt-node-count --tamper-checks \
  --evidence-file examples/atto-receipt-offline/llmrt-node-count.json
```

Expect `evidenceMode: offline`, three verified native block hashes and signatures, eight rejected tamper checks, and `25000000000000` atomic units (25,000 ATTO) both debited and credited. Missing responses cause an error; the verifier does not fetch them from the network. No wallet, account, or payment is needed.

The [bundle](llmrt-node-count.json) dates and identifies the public HTTPS responses by their source URLs. It retains only the matching history row's fields needed by the verifier; it includes the full signed receipt, the published public key response, and the native SEND, its immediate predecessor, and the worker’s OPEN. The verifier pins the SHA-256 of the published key's DER bytes separately in the code, checks the Marketplace signature, then checks the three native blocks and the signed balance changes. This helps detect changed evidence; it does not authenticate who provided a copy of the verifier itself. Use a trusted checkout.

This is a replay of captured evidence, not a fresh read or a check of current key status, native consensus/finality, submission bytes, or the separate publication-fee transfer. For a live check, see the [original payment example](../atto-receipt/#llmrts-code-count-credit-to-a-new-account).
