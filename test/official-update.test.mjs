// Guards for the official desktop update handoff (lib/official-update.wscript).
//
// Background: NSIS "RMDir /r" follows directory junctions. dsh-purge unpacks
// app.asar into resources\app and creates the junction resources\app\runtime ->
// ..\runtime. The official installer wipes the old install tree, follows that
// junction and empties resources\runtime, so the desktop host dies on startup
// with ENOENT resources\runtime\office-skills\office\SKILL.md.
//
// The handoff must therefore (a) remove the junction before the installer runs
// and (b) keep a runtime snapshot outside the install tree so a half-finished
// update can be rolled back to a bootable state.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { officialRestartScript, planOfficialRestart } from "../lib/desktop.js";
import { isWshAscii } from "../lib/official-update.js";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WSCRIPT = path.join(HERE, "..", "lib", "official-update.wscript");
const body = fs.readFileSync(WSCRIPT, "utf8");

let passed = 0;
async function check(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log(`✓ ${name}`);
  } catch (error) {
    console.error(`✗ ${name}\n  ${error.message}`);
    process.exitCode = 1;
  }
}

// Order helpers: the installer must run strictly after the guard steps.
const idx = (needle) => body.indexOf(needle);
const installerCall = idx("var code = runInstaller(true);");
const lastInstallerCall = body.lastIndexOf("runInstaller(true)");

await check("wscript stays ASCII (the loader rejects non-ASCII bodies)", () => {
  for (let i = 0; i < body.length; i += 1) {
    assert.ok(body.charCodeAt(i) <= 127, `non-ASCII char at ${i}`);
  }
});

await check("all placeholders are still present", () => {
  for (const key of ["__EXE_JSON__", "__INSTALLER_JSON__", "__RESOURCES_JSON__", "__INSTALL_DIR_JSON__", "__LOG_JSON__"]) {
    assert.ok(body.includes(key), `missing placeholder ${key}`);
  }
});

await check("junction is dropped with rmdir (no /s, link only)", () => {
  assert.ok(body.includes('cmd /c rmdir "'), "missing junction removal command");
  assert.ok(!/rmdir\s+"\s*"\s*\/s/i.test(body), "must not use recursive rmdir on a junction");
  assert.ok(body.includes("function dropJunction("), "missing dropJunction helper");
});

await check("junction is dropped before the installer runs", () => {
  assert.ok(installerCall > 0, "installer call not found");
  const dropApp = idx("dropJunction(appDir + '\\\\runtime');");
  const dropPrev = idx("dropJunction(prev + '\\\\runtime');");
  assert.ok(dropApp > 0, "appDir junction is never dropped");
  assert.ok(dropPrev > 0, "moved app junction is never dropped");
  assert.ok(dropApp < installerCall, "junction must go before the installer runs");
  assert.ok(dropPrev < installerCall, "moved app junction must go before the installer runs");
});

await check("runtime payload is snapshotted outside the install tree", () => {
  assert.ok(body.includes("function snapshotRuntime("), "missing snapshotRuntime helper");
  assert.ok(body.includes("var runtimeBak = installDir + '.runtime-bak';"),
    "runtime backup must live outside the install tree");
  const snap = idx("snapshotRuntime();");
  assert.ok(snap > 0, "snapshotRuntime is never called");
  assert.ok(snap < installerCall, "snapshot must happen before the installer runs");
});

await check("runtime completeness is verified against the host's real reads", () => {
  assert.ok(body.includes("primary-runtime\\\\runtime.json"), "missing primary runtime manifest check");
  assert.ok(body.includes("office-skills\\\\office\\\\SKILL.md"), "missing office skill check");
  assert.ok(body.includes("function runtimeComplete("), "missing runtimeComplete helper");
});

await check("an empty runtime after the update is rolled back", () => {
  assert.ok(body.includes("function restoreRuntime("), "missing restoreRuntime helper");
  const restore = body.lastIndexOf("else { restoreRuntime(); log('runtime-missing-after-update'); }");
  assert.ok(restore > 0, "success branch does not restore a missing runtime");
  assert.ok(restore > lastInstallerCall, "restore must run after the installer");
  assert.ok(body.includes("if (runtimeComplete(runtimeDir)) dropRuntimeBak(); else restoreRuntime();"),
    "failure branch does not reconcile the runtime");
});

await check("the restored runtime version is written to the update log", () => {
  assert.ok(body.includes("function runtimeVersion("), "missing runtimeVersion helper");
  assert.ok(body.includes("log('runtime-restored ' + runtimeVersion(runtimeDir));"),
    "restore does not log the runtime version");
});

await check("desktop officialRestartScript stays ASCII and plans wscript", () => {
  const dummyExe = "D:\\APPALL\\DeepSeekHarness\\DeepSeek Harness.exe";
  const dummyAsar = "D:\\APPALL\\DeepSeekHarness\\resources\\app.asar";
  const dummyHome = "C:\\Users\\dummy\\.dsh";
  const script = officialRestartScript(dummyExe, dummyAsar, dummyHome);
  assert.ok(isWshAscii(script), "officialRestartScript contains non-ASCII characters");
  const plan = planOfficialRestart({ wshJs: true, scriptAscii: isWshAscii(script) });
  assert.equal(plan.kind, "wscript", "official restart did not select wscript");
});

console.log(`\n${passed} official-update checks passed`);
