// Placeholders are filled by official-update.js. Quit the official client, run the downloaded installer, then reopen.
var exe = __EXE_JSON__;
var installer = __INSTALLER_JSON__;
var resources = __RESOURCES_JSON__;
var installDir = __INSTALL_DIR_JSON__;
if (installDir.length > 3) installDir = installDir.replace(/[\\\/]+$/, '');
var logPath = __LOG_JSON__;
var fso = new ActiveXObject('Scripting.FileSystemObject');
var sh = new ActiveXObject('WScript.Shell');
try {
  var tempDir = fso.GetSpecialFolder(2).Path;
  sh.CurrentDirectory = tempDir;
} catch (cwdErr) {}
var wmi = GetObject('winmgmts:\\\\.\\root\\cimv2');
function z(n) { return (n < 10 ? '0' : '') + n; }
function stamp() { var d = new Date(); return d.getFullYear() + '-' + z(d.getMonth() + 1) + '-' + z(d.getDate()) + 'T' + z(d.getHours()) + ':' + z(d.getMinutes()) + ':' + z(d.getSeconds()); }
function log(m) { var f = fso.OpenTextFile(logPath, 8, true); f.WriteLine(stamp() + ' ' + m); f.Close(); }
function samePath(a, b) { return String(a || '').replace(/\//g, '\\').toLowerCase() === String(b || '').replace(/\//g, '\\').toLowerCase(); }
function isSubPath(p, dir) {
  if (!p || !dir) return false;
  var lp = String(p).replace(/\//g, '\\').toLowerCase();
  var ld = String(dir).replace(/\//g, '\\').toLowerCase();
  if (ld.charAt(ld.length - 1) !== '\\') ld += '\\';
  return lp.indexOf(ld) === 0 || samePath(lp, String(dir).replace(/\//g, '\\').toLowerCase());
}
function pids() {
  var out = [];
  try {
    var e = new Enumerator(wmi.ExecQuery("SELECT ProcessId, ExecutablePath FROM Win32_Process"));
    for (; !e.atEnd(); e.moveNext()) {
      var p = e.item();
      if (!p || !p.ExecutablePath) continue;
      if (samePath(p.ExecutablePath, exe) || isSubPath(p.ExecutablePath, installDir)) {
        if (p.ProcessId !== 0 && p.ProcessId !== 4) out.push(p.ProcessId);
      }
    }
  } catch (err) {
    var e2 = new Enumerator(wmi.ExecQuery("SELECT ProcessId, ExecutablePath FROM Win32_Process WHERE Name = 'DeepSeek Harness.exe'"));
    for (; !e2.atEnd(); e2.moveNext()) {
      var p2 = e2.item();
      if (samePath(p2.ExecutablePath, exe)) out.push(p2.ProcessId);
    }
  }
  return out;
}
function fileSize(fp) { if (!fso.FileExists(fp)) return -1; return fso.GetFile(fp).Size; }
function fileStamp(fp) { if (!fso.FileExists(fp)) return ''; return String(fso.GetFile(fp).DateLastModified); }
// NSIS RMDir /r follows directory junctions: myDelete recurses into every entry that
// has FILE_ATTRIBUTE_DIRECTORY and never checks FILE_ATTRIBUTE_REPARSE_POINT (NSIS
// 3.11 / 3.13). dsh-purge unpacks app.asar into resources\app and creates the junction
// resources\app\runtime -> ..\runtime, so the official installer wipes the old install
// tree, follows that junction and empties resources\runtime. The desktop host then
// dies on startup with ENOENT resources\runtime\office-skills\office\SKILL.md.
// "rmdir" without /s removes the reparse point only and never touches the target.
function dropJunction(p) {
  try {
    if (!fso.FolderExists(p)) return 'absent';
    var rc = sh.Run('cmd /c rmdir "' + p + '"', 0, true);
    if (rc === 0) { log('drop-junction ' + p); return 'dropped'; }
    log('drop-junction-failed ' + p + ' rc=' + rc);
    return 'failed';
  } catch (dropErr) { log('drop-junction-error ' + p + ' ' + dropErr); return 'error'; }
}
function runtimeComplete(dir) {
  return fso.FileExists(dir + '\\primary-runtime\\runtime.json') &&
         fso.FileExists(dir + '\\office-skills\\office\\SKILL.md');
}
function runtimeVersion(dir) {
  try {
    var rf = fso.OpenTextFile(dir + '\\primary-runtime\\runtime.json', 1);
    var rt = rf.ReadAll(); rf.Close();
    var rm = rt.match(/"desktopVersion"\s*:\s*"([^"]+)"/);
    return rm ? rm[1] : 'unknown';
  } catch (verErr) { return 'unknown'; }
}
var runtimeDir = resources + '\\runtime';
var runtimeBak = installDir + '.runtime-bak';
var runtimeSnapshotted = false;
// Keep the runtime payload outside the install tree while the installer runs, so a
// half-finished update can be rolled back to a bootable state.
function snapshotRuntime() {
  try {
    if (!fso.FolderExists(runtimeDir)) { log('runtime-snapshot-absent'); return; }
    if (!runtimeComplete(runtimeDir)) { log('runtime-snapshot-incomplete'); return; }
    if (fso.FolderExists(runtimeBak)) {
      try { fso.DeleteFolder(runtimeBak, true); } catch (bakErr) { log('runtime-bak-clear ' + bakErr); }
    }
    fso.MoveFolder(runtimeDir, runtimeBak);
    runtimeSnapshotted = true;
    log('runtime-snapshot ' + runtimeVersion(runtimeBak));
  } catch (snapErr) { log('runtime-snapshot-failed ' + snapErr); }
}
function restoreRuntime() {
  if (!runtimeSnapshotted) return;
  try {
    if (fso.FolderExists(runtimeDir)) {
      try { fso.DeleteFolder(runtimeDir, true); } catch (delErr) { log('runtime-clear ' + delErr); }
    }
    fso.MoveFolder(runtimeBak, runtimeDir);
    runtimeSnapshotted = false;
    log('runtime-restored ' + runtimeVersion(runtimeDir));
  } catch (restoreErr) { log('runtime-restore-failed ' + restoreErr); }
}
function dropRuntimeBak() {
  if (!runtimeSnapshotted) return;
  try { if (fso.FolderExists(runtimeBak)) fso.DeleteFolder(runtimeBak, true); } catch (bakErr) { log('runtime-bak-delete ' + bakErr); }
  runtimeSnapshotted = false;
}
log('update-begin');
WScript.Sleep(800);
var list = pids();
log('pids ' + list.join(','));
for (var i = 0; i < list.length; i++) sh.Run('taskkill.exe /F /PID ' + list[i], 0, true);
var deadline = new Date().getTime() + 20000;
var left = list;
while (new Date().getTime() < deadline) { left = pids(); if (left.length === 0) break; WScript.Sleep(200); }
log('left ' + left.length);
var asar = resources + '\\app.asar';
var bak = asar + '.bak';
var appDir = resources + '\\app';
var movedApp = false;
var prev = '';
if (fso.FolderExists(appDir)) {
  prev = appDir + '.dshpurge-prev';
  if (fso.FolderExists(prev)) prev = appDir + '.dshpurge-prev-' + (new Date().getTime());
  for (var n = 0; n < 40; n++) {
    try { fso.MoveFolder(appDir, prev); movedApp = true; log('moved-app'); break; }
    catch (moveErr) { log('move-app ' + (moveErr && moveErr.message ? moveErr.message : moveErr)); WScript.Sleep(250); }
  }
}
// The junction has to go before the installer runs, otherwise NSIS follows it into
// resources\runtime and empties the payload the desktop host needs to boot.
if (prev) dropJunction(prev + '\\runtime');
dropJunction(appDir + '\\runtime');
snapshotRuntime();
var copiedAsar = false;
if (!fso.FileExists(asar) && fso.FileExists(bak)) {
  try { fso.CopyFile(bak, asar, true); copiedAsar = true; log('restored-asar'); }
  catch (restoreErr) { log('restore-asar ' + (restoreErr && restoreErr.message ? restoreErr.message : restoreErr)); }
}
var exeBeforeSize = fileSize(exe);
var exeBeforeStamp = fileStamp(exe);
var asarBeforeSize = fileSize(asar);
function runInstaller(updated) {
  var args = updated ? ' --updated /S /D=' : ' /S /D=';
  return sh.Run('"' + installer + '"' + args + installDir, 0, true);
}
var code = runInstaller(true);
log('installer ' + code);
var exeChanged = fileSize(exe) !== exeBeforeSize || fileStamp(exe) !== exeBeforeStamp;
var asarChanged = fileSize(asar) !== asarBeforeSize;
var ok = exeChanged || asarChanged;
log('changed exe=' + exeChanged + ' asar=' + asarChanged);
if (!ok) {
  code = runInstaller(false);
  log('installer-plain ' + code);
  exeChanged = fileSize(exe) !== exeBeforeSize || fileStamp(exe) !== exeBeforeStamp;
  asarChanged = fileSize(asar) !== asarBeforeSize;
  ok = exeChanged || asarChanged;
  log('changed-plain exe=' + exeChanged + ' asar=' + asarChanged);
}
if (!ok) {
  if (copiedAsar && fso.FileExists(asar)) {
    try { fso.DeleteFile(asar, true); log('rehid-asar'); } catch (hideErr) { log('rehid-asar ' + hideErr); }
  }
  // A concurrent unpack helper may have recreated resources\app. On failure, move the patched dir back.
  if (movedApp && prev && fso.FolderExists(prev)) {
    if (fso.FolderExists(appDir)) {
      dropJunction(appDir + '\\runtime');
      try { fso.DeleteFolder(appDir, true); log('cleared-recreated-app'); } catch (clearErr) { log('cleared-recreated-app ' + clearErr); }
    }
    if (!fso.FolderExists(appDir)) {
      try { fso.MoveFolder(prev, appDir); log('restored-app'); } catch (backErr) { log('restored-app ' + backErr); }
    }
  }
  if (runtimeComplete(runtimeDir)) dropRuntimeBak(); else restoreRuntime();
  try { sh.Environment('PROCESS').Remove('ELECTRON_RUN_AS_NODE'); } catch (ignore) {}
  sh.Run('"' + exe + '"', 1, false);
  log('started-old');
} else {
  if (!movedApp && fso.FolderExists(appDir)) log('move-app-failed');
  // The installer may leave resources\runtime empty (the very bug this guards).
  // Restore the snapshot before the desktop is started again, otherwise the host
  // dies on the first read of resources\runtime\office-skills\office\SKILL.md.
  if (runtimeComplete(runtimeDir)) { dropRuntimeBak(); log('runtime-ok ' + runtimeVersion(runtimeDir)); }
  else { restoreRuntime(); log('runtime-missing-after-update'); }
  try {
    var marker = fso.CreateTextFile(resources + '\\dsh-purge-reapply-asar', true);
    marker.WriteLine('1');
    marker.Close();
    log('marker');
  } catch (markerErr) { log('marker ' + markerErr); }
  try { sh.Environment('PROCESS').Remove('ELECTRON_RUN_AS_NODE'); } catch (ignore2) {}
  sh.Run('"' + exe + '"', 1, false);
  log('started');
}
