const { test } = require('node:test');
const assert = require('node:assert/strict');
const { ScopeState, parseScope } = require('../dist/scope');

const model = (name) => ({ path: `/p/${name}.SemanticModel`, name });
const report = (name) => ({ path: `/p/${name}.Report`, name, status: 'connected' });
const SALES = model('Sales').path, HR = model('HR').path;
// Fake server: Sales has three Reports, HR one. No model chosen when two exist.
function server(models = [model('Sales'), model('HR')]) {
  const calls = [];
  const fetch = async (chosen) => {
    calls.push(chosen);
    if (chosen && !models.some(m => m.path === chosen)) throw Object.assign(new Error('gone'), { status: 409 });
    const selected = chosen ?? (models.length === 1 ? models[0].path : null);
    return { project: '/p', models, modelExclusions: [], model: selected, otherReportCount: 0, unverifiedReports: [],
      reports: selected === SALES ? [report('A'), report('B'), report('C')] : selected === HR ? [report('People')] : [] };
  };
  return { fetch, calls };
}
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

test('sole model is selected with every connected report', async () => {
  const state = new ScopeState(); state.begin('/p');
  await state.load(server([model('Sales')]).fetch);
  const selection = state.selection();
  assert.equal(selection.model.path, SALES);
  assert.deepEqual(selection.reports.map(r => r.name), ['A', 'B', 'C']);
  assert.equal(selection.total, 3);
});
test('multiple models need an explicit choice; switching resets to all connected', async () => {
  const { fetch } = server(); const state = new ScopeState(); state.begin('/p');
  await state.load(fetch);
  assert.equal(state.selection().model, null);
  assert.deepEqual(state.selection().reports, []);
  await state.selectModel(fetch, SALES);
  state.setReport('/p/B.Report', false);
  assert.deepEqual(state.selection().reports.map(r => r.name), ['A', 'C']);
  await state.selectModel(fetch, HR);
  assert.deepEqual(state.selection().reports.map(r => r.name), ['People']);
  await state.selectModel(fetch, SALES);
  assert.equal(state.selection().reports.length, 3, 'a new model choice starts from all connected');
});
test('deselection, zero reports, select all and stable keys', async () => {
  const { fetch } = server(); const state = new ScopeState(); state.begin('/p');
  await state.load(fetch); await state.selectModel(fetch, SALES);
  const all = state.selection().key;
  state.setAll(false);
  assert.deepEqual(state.selection().reports, []);
  assert.equal(state.selection().total, 3);
  assert.notEqual(state.selection().key, all);
  state.setAll(true);
  assert.equal(state.selection().key, all);
  state.setReport('/p/unknown.Report', false);
  assert.equal(state.selection().key, all, 'unknown reports cannot be toggled');
});
test('restart of the same folder keeps the model and deselections; another folder wipes them', async () => {
  const { fetch, calls } = server(); const state = new ScopeState(); state.begin('/p');
  await state.load(fetch); await state.selectModel(fetch, SALES);
  state.setReport('/p/A.Report', false);
  state.detach();
  assert.equal(state.selection(), undefined, 'no selection while stopped');
  state.begin('/p'); await state.load(fetch);
  assert.equal(calls.at(-1), SALES);
  assert.deepEqual(state.selection().reports.map(r => r.name), ['B', 'C']);
  state.begin('/other'); await state.load(fetch);
  assert.equal(calls.at(-1), undefined);
  assert.equal(state.selection().model, null);
});
test('a remembered model that disappeared falls back to the default choice', async () => {
  const first = server(); const state = new ScopeState(); state.begin('/p');
  await state.load(first.fetch); await state.selectModel(first.fetch, SALES);
  state.detach(); state.begin('/p');
  await state.load(server([model('HR')]).fetch);
  assert.equal(state.selection().model.path, HR);
  assert.equal(state.phase, 'ready');
});
test('slow responses for an older folder, server or model never replace newer state', async () => {
  const state = new ScopeState(); state.begin('/old');
  const slow = deferred();
  const old = state.load(() => slow.promise);
  state.begin('/new');
  await state.load(server([model('HR')]).fetch);
  slow.resolve({ project: '/old', models: [model('Sales')], modelExclusions: [], model: SALES,
    reports: [report('A')], unverifiedReports: [], otherReportCount: 0 });
  assert.equal(await old, false);
  assert.equal(state.selection().model.path, HR);
  // Model switch superseded by another switch.
  const { fetch } = server(); state.begin('/p'); await state.load(fetch);
  const late = deferred();
  const first = state.selectModel(async () => { await late.promise; return fetch(SALES); }, SALES);
  await state.selectModel(fetch, HR);
  late.resolve();
  assert.equal(await first, false);
  assert.equal(state.selection().model.path, HR);
  // Stop while loading.
  const pending = deferred();
  const stopped = state.load(() => pending.promise);
  state.detach(); pending.resolve({});
  assert.equal(await stopped, false);
  assert.equal(state.phase, 'idle');
});
test('no selection or toggling while a model switch is loading', async () => {
  const { fetch } = server(); const state = new ScopeState(); state.begin('/p');
  await state.load(fetch); await state.selectModel(fetch, SALES);
  const gate = deferred();
  const switching = state.selectModel(async m => { await gate.promise; return fetch(m); }, HR);
  assert.equal(state.pendingModel, HR);
  gate.resolve(); await switching;
  assert.equal(state.pendingModel, undefined);
  assert.equal(state.selection().model.path, HR);
});
test('server errors become an error phase; malformed payloads are rejected', async () => {
  const state = new ScopeState(); state.begin('/p');
  assert.equal(await state.load(async () => { throw new Error('boom'); }), false);
  assert.equal(state.phase, 'error'); assert.equal(state.error, 'boom');
  for (const bad of [null, {}, { models: [{ path: 1, name: 'x' }], modelExclusions: [], reports: [], unverifiedReports: [], otherReportCount: 0, model: null },
    { models: [], modelExclusions: [], reports: [], unverifiedReports: [], otherReportCount: 0, model: '/not-listed' },
    { models: [model('A')], modelExclusions: [], reports: [{ path: '/r\n', name: 'r', status: 'connected' }], unverifiedReports: [], otherReportCount: 0, model: null }])
    assert.throws(() => parseScope(bad));
});
