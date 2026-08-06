# Troubleshooting — v1.1.4

## `HTTP 400 ... Invalid ticker parameter`

Deploy v1.1.4. Some Alpaca symbols use syntax that Massive's exact ticker filter rejects. The worker now records these symbols in instrument metadata with status `invalid_ticker_parameter` and continues. It does not retry the same permanent input error.

After deployment, use **Retry and resume** once for any partition that already exhausted its attempts.
