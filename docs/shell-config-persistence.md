# Desktop configuration persistence

The shell owns live configuration writes through `ShellConfigStore`. It serializes atomic FileView saves, retains the last valid configuration during invalid or missing external reads, rolls back failed saves, and exposes errors through a desktop notification and `shell configPersistenceState` IPC. The UI can remain responsive during saving; a failure must never leave an apparently saved layout active indefinitely.

FileView caches text passed to `setText`, even on an unsuccessful write. Recovery reloads the real file on a later event-loop turn so retrying exactly the same edit is not silently treated as an unchanged buffer. A settings mutation cannot overwrite an unreadable configuration with defaults. First startup with a genuinely missing file can still initialize a configuration from defaults.

The documented FileView completion signals are `saved` and `saveFailed`: https://quickshell.org/docs/v0.3.1/types/Quickshell.Io/FileView/.

## External editors and agents

Prefer `omarchy bar set`, `omarchy bar put`, and the plugin IPC for their supported operations. For other configuration changes:

1. `omarchy shell config-edit snapshot /tmp/shell-base.json`
2. Copy the snapshot to a separate edited file and change only the intended fields.
3. `omarchy shell config-edit apply /tmp/shell-base.json /tmp/shell-edited.json`

The command refuses a stale snapshot, refuses plugin order or membership changes by default, and waits for save completion before claiming success. `--allow-layout-change` is for explicitly intended plugin additions, removals, replacements, or moves. The current live snapshot is still required. JSON object key order may change without changing plugin order; the ordered layout arrays determine positions.

Set `protectPluginOrder: true` in the live configuration to protect the running desktop from external whole-file layout overwrites too. External reads retain the current plugin membership and placement, merge settings for matching plugin IDs, and atomically repair the file. User changes through the live shell APIs still work, including intentional moves and plugin installation. This protection requires the shell to be running with a previously loaded valid layout; it cannot intercept a file replacement while the shell is stopped. It protects layout, not unrelated settings from a stale full-file writer.

Do not restore an old complete shell.json to undo a small plugin change. Do not use `chattr +i`: the shell needs to save user preferences. Do not restart/reload to reconcile a difference between live and disk state until the intended state has been preserved. Direct external file writes do not participate in compare-and-set; concurrent tools should use the live shell writer.

## Tests

`test/shell.d/config-persistence-test.sh` exercises the real store using an offscreen Quickshell process and temporary files. It covers partial JSON, failed atomic writes, retry after repairing permissions, repeated saves, stale snapshots, order protection, and disappearance of a previously loaded file. No live desktop configuration is changed by this test.
