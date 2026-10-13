const vscode = require('vscode');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright-core');
async function snapshot(root) {
  const entries = await fs.readdir(root, { withFileTypes: true });
  const result = {};
  for (const entry of entries) {
    const file = path.join(root, entry.name);
    if (entry.isDirectory()) Object.assign(result, await snapshot(file));
    else result[file] = crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
  }
  return result;
}
exports.run = async () => {
  const project = process.env.SMC_TEST_PROJECT;
  const before = await snapshot(project);
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${process.env.SMC_TEST_CDP_PORT}`);
  try {
    await vscode.commands.executeCommand('semanticModelCleaner.open', vscode.Uri.file(project));
    let frame, page;
    for (let i = 0; i < 100 && !frame; i++) {
      for (const context of browser.contexts()) for (const candidate of context.pages()) {
        const found = candidate.frames().find(f => /^http:\/\/127\.0\.0\.1:\d+\/$/.test(f.url()));
        if (found) { frame = found; page = candidate; break; }
      }
      if (!frame) await new Promise(resolve => setTimeout(resolve, 200));
    }
    if (!frame) {
      for (const context of browser.contexts()) for (const page of context.pages()) {
        console.error('PAGE', page.url(), (await page.locator('body').innerText()).slice(-3000));
        for (const f of page.frames()) console.error('FRAME', f.url(), (await f.locator('body').innerText().catch(() => '')).slice(0, 1000));
      }
      throw new Error('Cleaner iframe not loaded in the real VS Code host.');
    }
    await frame.waitForFunction(() => typeof window.smcFetch === 'function');
    const discovery = await frame.evaluate(async () => {
      const r = await window.smcFetch('/api/discover');
      return { status: r.status, body: await r.json() };
    });
    assert.equal(discovery.status, 200);
    assert.ok(discovery.body.models?.length > 0, JSON.stringify(discovery.body));
    assert.ok(JSON.stringify(discovery.body).includes(project));
    assert.equal(await frame.locator('meta[name="smc-local-token"]').count(), 1);
    assert.ok((await frame.locator('body').innerText()).includes('Semantic Model Cleaner'));
    // Browser-native confirm is sandboxed. Exercise real in-page consent,
    // including cancel/Escape, without executing a model write.
    for (const action of ['Cancel', 'Confirm', 'Escape']) {
      await frame.evaluate(() => { window.__smokeDecision = null;
        void window.smcConfirm('Disposable confirmation test').then(value => { window.__smokeDecision = value; }); });
      const dialog = frame.getByRole('dialog', { name: 'Confirm action', exact: true });
      await dialog.waitFor();
      if (action === 'Escape') await dialog.press('Escape');
      else await dialog.getByRole('button', { name: action, exact: true }).click();
      await frame.waitForFunction(() => window.__smokeDecision !== null);
      assert.equal(await frame.evaluate(() => window.__smokeDecision), action === 'Confirm');
    }
    // Startup must populate even the single-model selector and connected Reports.
    await frame.waitForFunction(() => chosenModels.length === 1 && chosenReports.length > 0);
    assert.equal(await frame.locator('#projectModelSelect option').count(), 2);
    assert.equal(await frame.locator('#projectModelSelect').inputValue(), discovery.body.models[0].path);
    await vscode.commands.executeCommand('notifications.clearAll');
    await frame.locator('#btnAnalyze').click();
    await frame.locator('#viewToolbar').waitFor({ state: 'visible', timeout: 20000 });
    assert.ok((await frame.locator('body').innerText()).includes('Revenue'));
    const oldUrl = frame.url();
    await page.screenshot({ path: path.join(process.env.SMC_TEST_ARTIFACTS, 'cleaner-vscode.png') });
    await vscode.commands.executeCommand('semanticModelCleaner.restart');
    await assert.rejects(fetch(oldUrl));
    await vscode.commands.executeCommand('semanticModelCleaner.stop');
    await vscode.commands.executeCommand('semanticModelCleaner.open', vscode.Uri.file(project));
    // Find the new document, then verify closing the panel actually shuts its
    // port, rather than only trusting a successful close-editor command.
    let reopened;
    for (let i = 0; i < 50 && !reopened; i++) {
      reopened = page.frames().find(f => /^http:\/\/127\.0\.0\.1:\d+\/$/.test(f.url()));
      if (!reopened) await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(reopened, 'Reopened Cleaner document must exist');
    const reopenedUrl = reopened.url();
    await vscode.commands.executeCommand('workbench.action.closeActiveEditor');
    let closed = false;
    for (let i = 0; i < 50 && !closed; i++) {
      try { await fetch(reopenedUrl); await new Promise(resolve => setTimeout(resolve, 100)); }
      catch { closed = true; }
    }
    assert.ok(closed, 'Panel disposal must close its owned server port');
    assert.deepEqual(await snapshot(project), before, 'Demo project must remain unchanged');
    const multiProject = process.env.SMC_TEST_MULTI_PROJECT;
    const multiBefore = await snapshot(multiProject);
    await vscode.commands.executeCommand('semanticModelCleaner.open', vscode.Uri.file(multiProject));
    let multiFrame;
    for (let i = 0; i < 100 && !multiFrame; i++) {
      multiFrame = page.frames().find(f => /^http:\/\/127\.0\.0\.1:\d+\/$/.test(f.url()));
      if (!multiFrame) await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(multiFrame, 'Repository Cleaner document must load');
    await multiFrame.waitForFunction(() => initialConfig.availableModels.length === 2);
    await multiFrame.evaluate(() => window.smcOpenScope());
    for (const [modelName, relative] of [['Primary', 'Models/Primary.SemanticModel'], ['Secondary', 'Department/Secondary.SemanticModel']]) {
      await multiFrame.locator('#projectModelSelect').selectOption(path.join(multiProject, relative));
      await multiFrame.waitForFunction(name => chosenReports.length === 1 && chosenReports[0].name === name, modelName);
      assert.equal(await multiFrame.locator('#btnAnalyze').isEnabled(), true);
    }
    await multiFrame.locator('#btnRefreshProject').click();
    await multiFrame.waitForFunction(() => document.querySelector('#projectModelSelect').options.length === 3 && chosenModels.length === 0);
    await page.screenshot({ path: path.join(process.env.SMC_TEST_ARTIFACTS, 'repository-discovery-vscode.png') });
    assert.deepEqual(await snapshot(multiProject), multiBefore, 'Repository discovery must not change project files');
    await fs.writeFile(path.join(process.env.SMC_TEST_ARTIFACTS, 'result.json'), JSON.stringify({
      host: process.platform, vscode: vscode.version, trusted: vscode.workspace.isTrusted,
      discoveryStatus: discovery.status, projectUnchanged: true,
      checks: ['single-model startup populated', 'mixed-layout repository models discovered', 'model selection filters connected Reports', 'repository refresh', 'real webview rendered', 'same-origin authenticated discovery', 'in-page confirm/cancel/Escape',
        'Analyze button renders demo results', 'restart closes old port', 'stop/reopen/close closes port'],
      boundary: 'Disposable development extension host; trust gate unit-tested, Marketplace/installed VSIX acceptance not claimed.'
    }, null, 2));
    console.log('SMC real extension-host/browser integration passed.');
  } finally {
    await vscode.commands.executeCommand('semanticModelCleaner.stop');
    await browser.close();
  }
};
