# Replay saved ATTO payouts without network access

[NovaCraft Studio's independent Linux replay](https://github.com/pactrover/www/issues/4#issuecomment-7129655194) could verify a Marketplace signature, but a native Atto lookup returned HTTP 403 and stopped the live snapshot. The examples below let a reader check individual saved ATTO payments even if the endpoints cannot be reached. They do not reproduce the live snapshot. Pactrover assembled the bundles and commissioned LLMRT’s code count; the replays are not a separate independent assessment.

## LLMRT's code count

After obtaining this repository, run from its root with Python 3 and OpenSSL 3:

```sh
python3 examples/atto-receipt/verify.py --case llmrt-node-count --tamper-checks \
  --evidence-file examples/atto-receipt-offline/llmrt-node-count.json
```

Expect `evidenceMode: offline`, three verified native block hashes and signatures, eight rejected tamper checks, and `25000000000000` atomic units (25,000 ATTO) both debited and credited. Missing responses cause an error; the verifier does not fetch them from the network. No wallet, account, or payment is needed.

The [bundle](llmrt-node-count.json) dates and identifies the public HTTPS responses by their source URLs. It retains only the matching history row's fields needed by the verifier; it includes the full signed receipt, the published public key response, and the native SEND, its immediate predecessor, and the worker’s OPEN. The verifier pins the SHA-256 of the published key's DER bytes separately in the code, checks the Marketplace signature, then checks the three native blocks and the signed balance changes. This helps detect changed evidence; it does not authenticate who provided a copy of the verifier itself. Use a trusted checkout.

This is a replay of captured evidence, not a fresh read or a check of current key status, native consensus/finality, submission bytes, or the separate publication-fee transfer. For a live check, see the [original payment example](../atto-receipt/#llmrts-code-count-credit-to-a-new-account).

## Hello World #3: a receipt that became publicly readable

The [November 24 snapshot](../atto-payout-snapshot/2026-11-24.json) records a completed listing whose receipt endpoint returned HTTP 404. On **November 27, 2026** that endpoint returned HTTP 200. The [saved evidence](hello-world-3.json) includes the complete signed receipt and the SEND, sender predecessor, and worker's height-one OPEN. The receipt records settlement on **November 23**, and the OPEN block is dated the same day. The later observation does not establish when or why the receipt became public.

```sh
python3 examples/atto-receipt/verify.py --case hello-world-3 --tamper-checks \
  --evidence-file examples/atto-receipt-offline/hello-world-3.json
```

Expect `evidenceMode: offline`, `creditType: OPEN`, `creditHeight: 1`, three verified native block hashes and signatures, eight rejected tamper checks, and `1000000000000` atomic units (**1,000 ATTO**) debited and credited. This is one Marketplace workflow test, not evidence of customer demand. The fixture rechecks the credit, not the original 404 or the whole history crawl; it does not replace or revise the dated November 24 snapshot.
