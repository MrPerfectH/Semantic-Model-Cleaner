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
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label, timeout = 30000) {
  const end = Date.now() + timeout;
  let last;
  while (Date.now() < end) {
    try { const value = await check(); if (value) return value; } catch (error) { last = error; }
    await sleep(150);
  }
  throw new Error(`Timed out waiting for ${label}${last ? `: ${last.message}` : ''}`);
}
async function portClosed(url) {
  for (let i = 0; i < 100; i++) {
    try { await fetch(url); await sleep(100); } catch { return true; }
  }
  return false;
}

exports.run = async () => {
  const project = process.env.SMC_TEST_PROJECT, second = process.env.SMC_TEST_SECOND_PROJECT;
  const artifacts = process.env.SMC_TEST_ARTIFACTS;
  const before = await snapshot(project), beforeSecond = await snapshot(second);
  const extension = vscode.extensions.getExtension('MrPerfectH.semantic-model-cleaner');
  assert.ok(extension, 'Cleaner extension must be installed');
  assert.equal(extension.packageJSON.version, process.env.SMC_TEST_EXPECT_VERSION);
  if (process.env.SMC_TEST_EXPECT_EXTENSIONS)
    assert.ok(extension.extensionPath.startsWith(process.env.SMC_TEST_EXPECT_EXTENSIONS), extension.extensionPath);
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${process.env.SMC_TEST_CDP_PORT}`);
  const checks = [];
  const pass = name => { checks.push(name); console.log('PASS', name); };
  try {
    await vscode.commands.executeCommand('semanticModelCleaner.scope.focus');
    const shell = browser.contexts().flatMap(context => context.pages()).find(page => /workbench/.test(page.url()));
    assert.ok(shell, 'Desktop workbench must exist');
    const consoleLines = [];
    shell.on('console', message => consoleLines.push(`${message.type()} ${message.text()}`.slice(0, 600)));
    shell.on('requestfailed', request => consoleLines.push(`requestfailed ${request.url()} ${request.failure()?.errorText}`));
    shell.on('response', response => { if (/127\.0\.0\.1/.test(response.url())) consoleLines.push(`response ${response.status()} ${response.url()}`); });
    for (const context of browser.contexts()) {
      context.on('requestfailed', request => consoleLines.push(`ctx requestfailed ${request.url()} ${request.failure()?.errorText}`));
      context.on('response', response => { if (/127\.0\.0\.1/.test(response.url())) consoleLines.push(`ctx response ${response.status()} ${response.url()}`); });
      context.on('console', message => consoleLines.push(`ctx ${message.type()} ${message.text()}`.slice(0, 600)));
    }
    exports.consoleLines = consoleLines;
    const sidebar = shell.locator('[id="workbench.parts.sidebar"]');
    const sidebarText = () => sidebar.innerText();
    const row = label => sidebar.locator('.monaco-list-row').filter({
      has: shell.locator('.label-name', { hasText: new RegExp(`^\\s*${label}\\s*$`) }) }).first();
    const checkbox = label => row(label).locator('.custom-view-tree-node-item-checkbox, [role="checkbox"]').first();
    const shot = name => shell.screenshot({ path: path.join(artifacts, name) });

    // 1. Native pane before any server: explicit Open Cleaner only.
    await sidebar.getByRole('button', { name: 'Open Cleaner' }).waitFor();
    await shot('1-sidebar-welcome.png');
    pass('native Analysis Scope welcome before launch');
    // Cold Choose must start the installed package and await real engine discovery.
    await vscode.commands.executeCommand('workbench.view.explorer');
    const coldChoose = vscode.commands.executeCommand('semanticModelCleaner.chooseModel');
    const quickInput = shell.locator('.quick-input-widget');
    await quickInput.waitFor({ state: 'visible' });
    await quickInput.getByText('TestModel', { exact: true }).waitFor();
    await quickInput.getByText('ProductQA', { exact: true }).waitFor();
    await shell.keyboard.press('Escape');
    await coldChoose;
    pass('cold Choose starts engine and discovers both models; cancel leaves model unselected');

    const findFrame = async (exclude = '') => until(() => {
      for (const context of browser.contexts()) for (const page of context.pages()) {
        const frame = page.frames().find(f => /^http:\/\/127\.0\.0\.1:\d+\/(\?.*)?$/.test(f.url()) && !([exclude].flat().filter(Boolean).some(origin => f.url().startsWith(origin))));
        if (frame) return frame;
      }
    }, 'Cleaner iframe');
    let frame = await findFrame();
    const origin = new URL(frame.url()).origin;
    const banner = () => frame.locator('#smcHostScope').innerText();

    // 2. Two models: no implicit choice, no in-page scope drawer.
    await until(async () => /Semantic model\s*choose one/.test(await sidebarText()), 'explicit model choice');
    for (const label of ['TestModel', 'ProductQA']) await row(label).waitFor();
    await until(async () => (await banner()).includes('Choose a semantic model in the Cleaner sidebar'), 'empty banner');
    assert.equal(await frame.evaluate(() => allItems.length), 0, 'Choose must not analyze');
    assert.equal(await frame.locator('#scopeDrawer').isVisible(), false);
    assert.equal(await frame.locator('#setupSection').isVisible(), false);
    assert.equal(await frame.locator('#welcomeCard').isVisible(), false);
    await shot('2-multi-model-choice.png');
    pass('two models require explicit choice; editor has no scope drawer');
    assert.equal(await frame.locator('#railCompare, #compareFlow, .ui-switch-link').count(), 0);
    assert.equal(await frame.getByText('Classic layout', { exact: true }).count(), 0);
    pass('Compare and Classic controls absent in packaged host');

    // 3. Choose a model: every connected report selected by default.
    await row('TestModel').click();
    await until(async () => /Reports\s*2 of 2 selected/.test(await sidebarText()), 'default all connected');
    const text = await sidebarText();
    for (const expected of ['TestReport', 'Sales Overview', 'Legacy Draft', 'binding not verified', '2 reports use other models'])
      assert.ok(text.includes(expected), expected);
    assert.equal(await checkbox('Sales Overview').getAttribute('aria-checked'), 'true');
    await until(async () => (await banner()).includes('Ready: TestModel · 2 of 2 reports'), 'ready banner');
    await shot('3-default-all-connected.png');
    pass('chosen model defaults to all connected reports; unverified and other-model reports shown');

    // 4. Deselect one report and analyze exactly that subset.
    await checkbox('Sales Overview').click();
    await until(async () => /Reports\s*1 of 2 selected/.test(await sidebarText()), 'deselection');
    await until(async () => (await banner()).includes('Ready: TestModel · 1 of 2 reports'), 'subset banner');
    await row('Analyze').click();
    await until(async () => (await banner()).includes('Analyzed: TestModel · 1 of 2 reports'), 'subset analysis', 60000);
    await until(async () => (await sidebarText()).includes('results current'), 'sidebar results current');
    const subset = await frame.evaluate(() => ({
      reports: chosenReports.map(r => r.name), items: allItems.length,
      safe: allItems.filter(i => i.deleteSafety === 'Safe').length,
      limitations: allAnalysisLimitations.limitations.map(l => l.id)
    }));
    assert.deepEqual(subset.reports, ['TestReport']);
    assert.ok(subset.items > 0);
    assert.equal(subset.safe, 0, 'unselected connected report must withhold Safe');
    assert.ok(subset.limitations.includes('report_scan:not_selected'));
    await shot('4-subset-analyzed.png');
    pass('analyze exact subset (1 of 2); unselected report withholds Safe');

    // 5. Changing the sidebar makes displayed results stale and inert.
    await checkbox('Sales Overview').click();
    await until(async () => (await banner()).includes('Results are out of date'), 'stale banner');
    assert.equal(await frame.evaluate(() => document.getElementById('viewToolbar').inert), true);
    await until(async () => (await sidebarText()).includes('results stale'), 'sidebar stale');
    await shot('5-stale-results.png');
    pass('scope change marks results stale and blocks actions on them');
    await row('Analyze').click();
    await until(async () => (await banner()).includes('Analyzed: TestModel · 2 of 2 reports'), 'full analysis', 60000);
    assert.equal(await frame.evaluate(() => document.getElementById('viewToolbar').inert), false);
    const full = await frame.evaluate(() => ({ safe: allItems.filter(i => i.deleteSafety === 'Safe').length,
      limitations: allAnalysisLimitations.limitations.map(l => l.id) }));
    assert.ok(full.safe > 0); assert.ok(!full.limitations.includes('report_scan:not_selected'));
    pass('full selection analysis restores current results');

    // 6. Zero reports: model-only analysis.
    await vscode.commands.executeCommand('semanticModelCleaner.clearReports');
    await until(async () => /Reports\s*0 of 2 selected/.test(await sidebarText()), 'zero selected');
    await until(async () => (await sidebarText()).includes('model only (0 of 2 reports)'), 'model-only analyze label');
    await row('Analyze').click();
    await until(async () => (await banner()).includes('Analyzed: TestModel · model only (0 of 2 reports)'), 'model-only analysis', 60000);
    const modelOnly = await frame.evaluate(() => ({ reports: chosenReports.length, items: allItems.length,
      safe: allItems.filter(i => i.deleteSafety === 'Safe').length,
      limitations: allAnalysisLimitations.limitations.map(l => l.id) }));
    assert.equal(modelOnly.reports, 0); assert.ok(modelOnly.items > 0); assert.equal(modelOnly.safe, 0);
    assert.ok(modelOnly.limitations.includes('report_scan:not_requested'));
    await shot('6-model-only.png');
    pass('zero reports runs model-only analysis with usage unknown');
    await vscode.commands.executeCommand('semanticModelCleaner.selectAllReports');
    await until(async () => /Reports\s*2 of 2 selected/.test(await sidebarText()), 'select all');

    // 7. Switch model: reports reset to that model's connected reports.
    await row('ProductQA').click();
    await until(async () => /Semantic model\s*ProductQA/.test(await sidebarText()) && /Reports\s*2 of 2 selected/.test(await sidebarText()), 'ProductQA reports');
    for (const expected of ['Executive', 'Operations']) await row(expected).waitFor();
    assert.equal(await row('Sales Overview').count(), 0);
    await until(async () => (await banner()).includes('Results are out of date'), 'stale after model switch');
    await row('Analyze').click();
    await until(async () => (await banner()).includes('Analyzed: ProductQA · 2 of 2 reports'), 'ProductQA analysis', 60000);
    assert.deepEqual(await frame.evaluate(() => chosenModels.map(m => m.name)), ['ProductQA']);
    await shot('7-model-switch.png');
    pass('model switch resets reports, marks stale, analyzes new model');

    // 8. Change during a running analysis never shows mismatched results.
    await checkbox('Operations').click();
    await until(async () => /Reports\s*1 of 2 selected/.test(await sidebarText()), 'deselect Operations');
    await row('Analyze').click();
    await checkbox('Operations').click();
    await until(async () => !(await sidebarText()).includes('analyzing'), 'analysis settles', 60000);
    await sleep(500);
    const raced = await banner();
    assert.ok(raced.includes('Results are out of date') || raced.includes('Scope changed during analysis') ||
      raced.includes('Analyzed: ProductQA · 2 of 2 reports'), raced);
    assert.ok(!raced.includes('Analyzed: ProductQA · 1 of 2'), raced);
    pass('scope change during analysis discards or marks the run stale');

    // 9. Restart keeps the model and report choices of the same folder.
    await checkbox('Executive').click();
    await until(async () => /Reports\s*1 of 2 selected/.test(await sidebarText()), 'deselect Executive');
    await vscode.commands.executeCommand('semanticModelCleaner.restart');
    assert.ok(await portClosed(origin + '/'), 'restart closes old port');
    frame = await findFrame(origin);
    await until(async () => /Semantic model\s*ProductQA/.test(await sidebarText()) && /Reports\s*1 of 2 selected/.test(await sidebarText()), 'restored after restart');
    assert.equal(await checkbox('Executive').getAttribute('aria-checked'), 'false');
    await until(async () => (await frame.locator('#smcHostScope').innerText()).includes('Ready: ProductQA · 1 of 2 reports'), 'banner after restart');
    pass('restart closes old port and keeps same-folder choices');

    // 10. Another folder wipes state; its sole model is auto-selected.
    const restartedOrigin = new URL(frame.url()).origin;
    await vscode.commands.executeCommand('semanticModelCleaner.open', vscode.Uri.file(second));
    assert.ok(await portClosed(restartedOrigin + '/'), 'folder switch closes old port');
    frame = await findFrame(restartedOrigin);
    await until(async () => /Semantic model\s*TestModel/.test(await sidebarText()) && /Reports\s*1 of 1 selected/.test(await sidebarText()), 'second folder auto model');
    assert.equal(await row('ProductQA').count(), 0);
    await until(async () => (await frame.locator('#smcHostScope').innerText()).includes('Ready: TestModel · 1 of 1 report'), 'second folder banner');
    await row('Analyze').click();
    await until(async () => (await frame.locator('#smcHostScope').innerText()).includes('Analyzed: TestModel · 1 of 1 report'), 'second folder analysis', 60000);
    await shot('8-second-folder.png');
    pass('workspace switch resets scope; sole model auto-selected and analyzed');

    // 11. Stop returns the pane to its welcome state and closes the port.
    const lastOrigin = new URL(frame.url()).origin;
    await vscode.commands.executeCommand('semanticModelCleaner.stop');
    assert.ok(await portClosed(lastOrigin + '/'), 'stop closes port');
    await sidebar.getByRole('button', { name: 'Open Cleaner' }).waitFor();
    pass('stop closes port and returns pane to welcome');

    // Cold Analyze after Stop uses the workspace folder, with an explicit model picker.
    const coldAnalyze = vscode.commands.executeCommand('semanticModelCleaner.analyze');
    await quickInput.waitFor({ state: 'visible' });
    await quickInput.locator('input').fill('TestModel');
    await shell.keyboard.press('Enter');
    await coldAnalyze;
    // Use the native completion state: Electron can retain/disconnect old OOPIF
    // targets after repeated Stop/Open, making a cached iframe an unreliable probe.
    await until(async () => /Semantic model\s*TestModel/.test(await sidebarText()) &&
      /Reports\s*2 of 2 selected/.test(await sidebarText()) && (await sidebarText()).includes('results current'),
      'cold command analysis completion in native scope', 60000);
    pass('cold Analyze starts, awaits discovery and analyzes only the explicit model choice');
    await shot('9-cold-analyze.png');
    await vscode.commands.executeCommand('semanticModelCleaner.stop');
    await sidebar.getByRole('button', { name: 'Open Cleaner' }).waitFor();

    assert.deepEqual(await snapshot(project), before, 'Project must remain unchanged');
    assert.deepEqual(await snapshot(second), beforeSecond, 'Second project must remain unchanged');
    pass('projects unchanged');
    await fs.writeFile(path.join(artifacts, 'result.json'), JSON.stringify({
      host: process.platform, vscode: vscode.version, appName: vscode.env.appName,
      extensionVersion: extension.packageJSON.version, extensionPath: extension.extensionPath,
      installedFromVsix: !!process.env.SMC_TEST_EXPECT_EXTENSIONS, trusted: vscode.workspace.isTrusted,
      projectUnchanged: true, checks,
      boundary: 'Disposable desktop host with isolated profile and extensions directory; Workspace Trust disabled for unattended runs.'
    }, null, 2));
    console.log('SMC real extension-host/browser integration passed.');
  } catch (error) {
    try {
      const shell = browser.contexts().flatMap(context => context.pages()).find(page => /workbench/.test(page.url()));
      if (shell) await shell.screenshot({ path: path.join(artifacts, 'failure.png') });
      const frames = [];
      for (const context of browser.contexts()) for (const page of context.pages()) {
        frames.push('PAGE ' + page.url());
        for (const f of page.frames()) frames.push('  FRAME ' + f.url() + ' :: ' +
          (await f.locator('body').innerText({ timeout: 2000 }).catch(() => '')).slice(0, 400).replace(/\s+/g, ' '));
      }
      for (const context of browser.contexts()) for (const page of context.pages()) for (const f of page.frames())
        if (/fake\.html/.test(f.url())) {
          const src = await f.evaluate(() => document.querySelector('iframe')?.src).catch(e => e.message);
          frames.push('IFRAME SRC ' + src);
          const probe = await fetch(src, { headers: { 'Sec-Fetch-Dest': 'iframe', 'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Site': 'cross-site' } })
            .then(async r => `${r.status} ${r.headers.get('content-security-policy')} ${(await r.text()).slice(0, 200).replace(/\s+/g, ' ')}`)
            .catch(e => 'fetch failed ' + e.message);
          frames.push('NODE PROBE ' + probe);
        }
      frames.push(...(exports.consoleLines || []).filter(line => !/AgentHost|ChatModel|channel/.test(line)).slice(-60));
      await fs.writeFile(path.join(artifacts, 'failure-frames.txt'), frames.join('\n'));
      if (shell) await fs.writeFile(path.join(artifacts, 'failure-sidebar.txt'),
        JSON.stringify(await shell.locator('[id="workbench.parts.sidebar"]').innerText()));
    } catch { /* best effort */ }
    throw error;
  } finally {
    await vscode.commands.executeCommand('semanticModelCleaner.stop');
    await browser.close();
  }
};
