"""Exercise real asynchronous FileView IO on isolated temporary configuration."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

root = Path(os.environ['ROOT'])
with tempfile.TemporaryDirectory(prefix='omarchy-config-test-') as tmp:
    tmp = Path(tmp)
    (tmp/'ShellConfigStore.qml').symlink_to(root/'shell/services/ShellConfigStore.qml')
    data = tmp/'data'
    data.mkdir()
    config = data/'shell.json'
    baseline = {'version': 1, 'bar': {'layout': {'left': [{'id': 'a'}, {'id': 'b'}], 'center': [], 'right': []}}, 'plugins': []}
    config.write_text(json.dumps(baseline))
    (tmp/'shell.qml').write_text('''import QtQuick
import Quickshell
import Quickshell.Io
ShellRoot {
  ShellConfigStore { id: store; path: Quickshell.env("TEST_CONFIG_PATH") }
  IpcHandler {
    target: "test"
    function state(): string { return JSON.stringify({value: store.value, ready: store.ready, saving: store.saving, writable: store.writable, error: store.lastError}) }
    function save(raw: string): bool { return store.commit(JSON.parse(raw)) }
    function reload(): void { store.reload() }
    function compare(expected: string, next: string): string { return store.compareAndSet(JSON.parse(expected), JSON.parse(next)) }
  }
  IpcHandler {
    target: "shell"
    function listShellConfig(): string { return JSON.stringify(store.value) }
    function configPersistenceState(): string { return JSON.stringify({ready: store.ready, saving: store.saving, writable: store.writable, error: store.lastError}) }
    function compareAndSetShellConfig(expected: string, next: string): string { return store.compareAndSet(JSON.parse(expected), JSON.parse(next)) }
  }
}
''')
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', TEST_CONFIG_PATH=str(config), QS_DISABLE_FILE_WATCHER='1')
    log = (tmp/'log').open('w+')
    process = subprocess.Popen(['quickshell', '-p', str(tmp), '--no-color'], env=env, stdout=log, stderr=subprocess.STDOUT)
    def ipc(method, *args):
        return subprocess.check_output(['quickshell', 'ipc', '-p', str(tmp), '--any-display', 'call', 'test', method, *args], env=env, text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
    def wait_for(check):
        deadline = time.monotonic()+6
        while time.monotonic()<deadline:
            try:
                state=json.loads(ipc('state'))
                if check(state): return state
            except (ValueError, subprocess.SubprocessError): pass
            time.sleep(.05)
        log.flush(); log.seek(0)
        raise AssertionError(log.read())
    def passed(message): print('ok - '+message)
    try:
        wait_for(lambda s:s['ready'] and s['value']==baseline)
        passed('loads existing plugin order')
        config.write_text('{')
        ipc('reload')
        wait_for(lambda s: not s['writable'] and bool(s['error']))
        assert json.loads(ipc('state'))['value']==baseline
        assert ipc('save',json.dumps(baseline))=='false'
        assert config.read_text()=='{'
        passed('partial external JSON retains layout and cannot be overwritten by an unrelated setting')
        config.write_text(json.dumps(baseline)); ipc('reload')
        wait_for(lambda s:s['ready'] and s['writable'])
        candidate=json.loads(json.dumps(baseline)); candidate['idle']={'lock':0}
        data.chmod(0o555)
        assert ipc('save',json.dumps(candidate))=='true'
        failed=wait_for(lambda s:not s['saving'] and 'Could not save' in s['error'])
        assert failed['value']==baseline
        assert json.loads(config.read_text())==baseline
        passed('failed atomic save rolls live layout back and exposes the error')
        data.chmod(0o755)
        # Allow the recovery read to finish, then repeat precisely the failed write.
        wait_for(lambda s:s['ready'] and s['writable'] and not s['saving'])
        assert ipc('save',json.dumps(candidate))=='true'
        wait_for(lambda s:s['ready'] and not s['saving'] and not s['error'] and s['value']==candidate)
        assert json.loads(config.read_text())==candidate
        passed('same edit succeeds after permissions are repaired')
        # Multiple updates before/as writes finish must keep the latest value.
        for i in range(8):
            wait_for(lambda s:s['ready'])
            candidate['idle']['lock']=i
            assert ipc('save',json.dumps(candidate))=='true'
        wait_for(lambda s:s['ready'] and not s['saving'] and s['value']==candidate)
        assert json.loads(config.read_text())==candidate
        assert ipc('save',json.dumps(candidate))=='true'
        wait_for(lambda s:not s['saving'])
        passed('rapid saves and identical repeated edits settle without a stuck queue')
        assert ipc('compare',json.dumps(baseline),json.dumps(baseline)).startswith('conflict:')
        assert json.loads(config.read_text())==candidate
        passed('stale compare-and-set cannot overwrite a later config')
        # Exercise the agent command against this real store, including its
        # default order check and save-completion acknowledgement.
        tools = tmp/'bin'; tools.mkdir()
        wrapper=tools/'omarchy-shell'
        wrapper.write_text('#!/bin/bash\nexec quickshell ipc -p '+str(tmp)+' --any-display call "$@"\n')
        wrapper.chmod(0o755)
        command_env=dict(env, PATH=str(tools)+':'+env['PATH'])
        def command(*args):
            return subprocess.run([str(root/'bin/omarchy-shell-config-edit'),*map(str,args)],env=command_env,text=True,capture_output=True,timeout=8)
        base=tmp/'base.json'; proposed=tmp/'proposed.json'
        assert command('snapshot',base).returncode==0
        edit=json.loads(base.read_text()); edit['bar']['layout']['left'].reverse()
        proposed.write_text(json.dumps(edit))
        denied=command('apply',base,proposed)
        assert denied.returncode==1 and 'order/membership' in denied.stderr, denied
        assert json.loads(config.read_text())==candidate
        edit=json.loads(base.read_text()); edit['idle']['lock']=42
        proposed.write_text(json.dumps(edit))
        accepted=command('apply',base,proposed)
        assert accepted.returncode==0, accepted
        assert json.loads(config.read_text())==edit
        stale=command('apply',base,proposed)
        assert stale.returncode==1 and 'changed since' in stale.stderr, stale
        passed('agent command refuses reordering and stale snapshots, and verifies successful settings saves')
        candidate=edit
        candidate['protectPluginOrder']=True
        assert ipc('save',json.dumps(candidate))=='true'
        wait_for(lambda s:s['ready'] and not s['saving'] and s['value']==candidate)
        external=json.loads(json.dumps(candidate))
        external.pop('protectPluginOrder')
        external['bar']['layout']['left']=[{'id':'b','setting':2},{'id':'old-widget'}]
        external['idle']['lock']=43
        config.write_text(json.dumps(external)); ipc('reload')
        candidate['bar']['layout']['left'][1]['setting']=2
        candidate['idle']['lock']=43
        wait_for(lambda s:s['ready'] and not s['saving'] and s['value']==candidate)
        assert json.loads(config.read_text())==candidate
        passed('external stale layout is repaired while intended setting edits are kept')
        external=json.loads(json.dumps(candidate))
        external['bar']['layout']['left'].reverse()
        config.write_text(json.dumps(external)); ipc('reload')
        wait_for(lambda s:s['ready'] and not s['saving'] and s['value']==candidate and json.loads(config.read_text())==candidate)
        passed('a pure external reorder is repaired even when live settings are unchanged')
        candidate['bar']['layout']['left'].reverse()
        assert ipc('save',json.dumps(candidate))=='true'
        wait_for(lambda s:s['ready'] and not s['saving'] and s['value']==candidate)
        assert json.loads(config.read_text())==candidate
        passed('explicit live layout changes remain available with external order protection')
        config.unlink(); ipc('reload')
        wait_for(lambda s:not s['writable'])
        assert json.loads(ipc('state'))['value']==candidate
        passed('deleted configuration does not reset an already loaded desktop')
    finally:
        data.chmod(0o755)
        process.terminate()
        try: process.wait(timeout=3)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
        log.close()
