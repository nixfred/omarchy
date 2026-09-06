import QtQuick
import Quickshell.Io

// One writer for shell.json. Keep the last valid configuration through partial
// external edits, serialize saves, and roll back changes that cannot be saved.
Item {
  id: store
  visible: false
  property string path: ""
  property var defaults: ({ version: 1, plugins: [] })
  property var value: defaults
  property var persisted: null
  property var inFlight: null
  property var queued: null
  property bool ready: false
  property bool writable: false
  property string lastError: ""
  readonly property bool saving: inFlight !== null || queued !== null
  onDefaultsChanged: if (persisted === null && !saving) value = clone(defaults)
  signal failed(string message)

  function clone(value) { return JSON.parse(JSON.stringify(value)) }
  function valid(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value) && value.version === 1
  }
  function report(message) {
    var changed = lastError !== message
    lastError = message
    console.warn("shell.json: " + message)
    if (changed) failed(message)
  }
  function preserveOrder(previous, incoming) {
    var next = clone(incoming)
    function entries(before, after) {
      return (before || []).map(function(entry) {
        var match = (after || []).find(function(candidate) { return candidate.id === entry.id })
        return clone(match || entry)
      })
    }
    next.protectPluginOrder = true
    next.plugins = entries(previous.plugins, next.plugins)
    next.bar = next.bar || {}
    if (previous.bar) {
      if (previous.bar.id !== undefined) next.bar.id = previous.bar.id
      else delete next.bar.id
      var oldLayout = previous.bar.layout || {}
      var newLayout = next.bar.layout || {}
      var allIncoming = []
      Object.keys(newLayout).forEach(function(region) { allIncoming = allIncoming.concat(newLayout[region]) })
      next.bar.layout = {}
      Object.keys(oldLayout).forEach(function(region) {
        next.bar.layout[region] = entries(oldLayout[region], allIncoming)
      })
    }
    return next
  }
  function accept(raw) {
    ready = true
    if (saving) return
    try {
      var parsed = JSON.parse(raw)
      if (!valid(parsed)) throw new Error("expected an object with version: 1")
      if (persisted !== null && persisted.protectPluginOrder === true) {
        var protectedValue = preserveOrder(persisted, parsed)
        if (JSON.stringify(protectedValue) !== JSON.stringify(parsed)) {
          writable = true
          console.warn("shell.json: rejected an external plugin layout overwrite; preserving the current order")
          commit(protectedValue, true)
          return
        }
      }
      persisted = clone(parsed)
      value = clone(parsed)
      writable = true
    } catch (error) {
      writable = false
      report("Cannot read configuration; keeping the last valid layout. " + error)
    }
  }
  function commit(next, force) {
    if (!ready || !writable) {
      report("Configuration is not readable; refusing to overwrite it.")
      return false
    }
    if (!valid(next)) {
      report("Invalid configuration; refusing to save it.")
      return false
    }
    var payload = clone(next)
    lastError = ""
    if (!force && !saving && persisted !== null && JSON.stringify(payload) === JSON.stringify(persisted)) return true
    value = payload
    queued = payload
    flushTimer.restart()
    return true
  }
  function compareAndSet(expected, next) {
    if (saving) return "busy: configuration save in progress"
    if (JSON.stringify(expected) !== JSON.stringify(value))
      return "conflict: configuration changed; read a fresh snapshot"
    return commit(next) ? "accepted" : lastError
  }
  function flush() {
    if (inFlight !== null || queued === null) return
    inFlight = queued
    queued = null
    file.setText(JSON.stringify(inFlight, null, 2) + "\n")
  }
  function reload() {
    if (!saving) { ready = false; readTimer.restart() }
  }
  Timer { id: readTimer; interval: 0; onTriggered: file.reload() }
  Timer { id: flushTimer; interval: 0; onTriggered: store.flush() }
  FileView {
    id: file
    path: store.path
    watchChanges: true
    atomicWrites: true
    printErrors: true
    onLoaded: store.accept(text())
    onLoadFailed: function(error) {
      store.ready = true
      if (store.saving) return
      // A genuinely absent file at first launch can be initialized by a user
      // edit. A file lost after loading must not reset a running desktop.
      if (error === FileViewError.FileNotFound && store.persisted === null) {
        store.value = store.clone(store.defaults)
        store.writable = true
      } else {
        store.writable = false
        store.report("Cannot load configuration; keeping the last valid layout (" + error + ").")
      }
    }
    onFileChanged: store.reload()
    onSaved: {
      if (store.inFlight === null) return
      store.lastError = ""
      store.persisted = store.clone(store.inFlight)
      store.inFlight = null
      if (store.queued !== null) {
        // A repeated identical request must not await a saved signal that
        // FileView deliberately omits when there is nothing to write.
        if (JSON.stringify(store.queued) === JSON.stringify(store.persisted)) store.queued = null
        else { flushTimer.restart(); return }
      }
      store.ready = false
      readTimer.restart()
    }
    onSaveFailed: function(error) {
      store.inFlight = null
      store.queued = null
      flushTimer.stop()
      store.value = store.clone(store.persisted || store.defaults)
      store.report("Could not save configuration; the change was reverted. Check file permissions and disk space (" + error + ").")
      // Reload the real disk contents, clearing FileView's unsaved cache so
      // retrying the same change after fixing permissions actually writes.
      store.ready = false
      readTimer.restart()
    }
  }
}
