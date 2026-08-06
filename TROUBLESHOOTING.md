# Troubleshooting — v1.1.3

## `only '%s', '%b', '%t' are allowed as placeholders, got '%''`

This is the v1.1.2 Massive stage-count SQL defect. Deploy v1.1.3. The wildcard is now supplied as a bound parameter. No data repair is required because the failure occurred before the new symbol batches were processed.

## What healthy recovery looks like

The worker log shows `Processing partition` with stage `massive_reference` and keys such as `symbol-batch-00000`. The UI may temporarily show more Massive partitions than before; each represents roughly 100 symbols from the existing run.

## Protocol integrity

The protocol version remains 1.1.0 and its hash is unchanged. App version 1.1.3 is an operational repair only.
