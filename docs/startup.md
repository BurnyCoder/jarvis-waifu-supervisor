# Dashboard startup and browser readiness

This page describes only the process-to-browser startup contract. See the
[README](../README.md) for installation, configuration, privacy, enforcement,
and normal dashboard use.

## Startup modes

| Invocation | Dashboard browser behavior |
|---|---|
| `uv run python main.py` | Starts the UI after UAC; open the logged URL manually. |
| `uv run python main.py --open-browser` | Requests one browser tab after the configured server answers `/status`. |
| `uv run python main.py --dry-hosts --open-browser` | Exercises the same UI startup without UAC or hosts-file writes. |
| `uv run python main.py --smoke` | Starts no scheduler loops, server, readiness worker, or browser, even if `--open-browser` is also present. |
| `Start Deep Work.bat` | Self-elevates, checks `uv`, and passes `--open-browser` to Python. |

The Python administrator relaunch reconstructs the original argument list, so
`--open-browser` survives UAC. `UI_PORT` is loaded once through the normal
`.env` configuration path; the batch file stores neither a port nor a delay.

## Sequence

1. Parse arguments, complete any UAC relaunch, load configuration, initialize
   timestamped logging, and wire the application collaborators.
2. Register shutdown cleanup and start the scheduler threads for a UI run.
3. Construct Werkzeug's threaded server for `127.0.0.1:<UI_PORT>`. The
   constructor binds and activates the socket before returning; a port conflict
   therefore ends startup before any browser worker exists.
4. Log `control panel listening: <URL>`. If requested, start one named daemon
   readiness worker, then enter the server's request loop.
5. The worker requests `/status` directly over loopback. Connection failures
   retry until the 30-second [`time.monotonic`](https://docs.python.org/3.13/library/time.html#time.monotonic)
   deadline. Each request timeout is capped by the time remaining.
6. Any completed HTTP response, including a non-2xx response, proves the local
   server is reachable. The worker then calls
   [`webbrowser.open_new_tab`](https://docs.python.org/3.13/library/webbrowser.html#webbrowser.open_new_tab)
   exactly once for the root dashboard URL.
7. The server continues until shutdown. Exiting the server signals a pending
   worker to cancel; the worker checks that signal before probing and opening.

The implementation uses Python's
[`HTTPConnection`](https://docs.python.org/3.13/library/http.client.html#http.client.HTTPConnection)
instead of proxy-aware URL helpers, and Werkzeug's separately usable
[`make_server` factory](https://github.com/pallets/werkzeug/blob/3.1.8/src/werkzeug/serving.py).

## Failure behavior

- A bind failure starts no browser worker. Resolve the port conflict or choose
  another valid `UI_PORT`, then restart.
- A readiness timeout logs the loopback URL and does not open a possibly
  unreachable tab. The already bound server keeps running.
- If the OS browser call returns false, raises, or its worker cannot start, the
  error and manual URL are logged while the server keeps running.
- The server remains intentionally limited to `127.0.0.1`; readiness handling
  does not add network exposure, authentication, or CSRF protection. Werkzeug's
  [serving documentation](https://werkzeug.palletsprojects.com/en/stable/serving/)
  describes this as a development server.

## Verification

Use the [dashboard-readiness procedure](verification.md#dashboard-readiness)
for the isolated-port command, expected log order, browser-failure checks, and
focused automated tests. That guide owns executable verification steps so this
startup contract cannot drift from a duplicated transcript.
