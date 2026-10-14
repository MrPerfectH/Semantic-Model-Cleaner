const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const root = process.argv[2], staticRoot = path.join(root,'src/semantic_model_cleaner/static');
const template = fs.readFileSync(path.join(root,'src/semantic_model_cleaner/templates/index_v2.html'),'utf8');
function section(start,end) { return template.slice(template.indexOf(start),template.indexOf(end,template.indexOf(start))); }
function node() { return {value:'',checked:false,disabled:false,hidden:false,children:[],classList:{contains:()=>false},replaceChildren(){this.children=[];},appendChild(child){this.children.push(child);},click(){}}; }
const tick = () => new Promise(resolve=>setImmediate(resolve));
(async()=>{
  // Real first-run controller: multiple models, connected report candidates, and stale replies.
  const nodes = new Map(), requests=[];
  const a={name:'A',path:'/project/A.SemanticModel'},b={name:'B',path:'/project/B.SemanticModel'};
  const reports=[{name:'Overview',path:'/project/A/Overview.Report'},{name:'Overview',path:'/project/B/Overview.Report'}];
  const c={initialConfig:{defaultRoot:'/project',availableModels:[a,b],availableReports:reports},chosenModels:[],chosenReports:[],
    $:id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);},document:{createElement:()=>node()},
    renderPills(){},runAnalyze(){},apiPost:(url,body)=>new Promise(resolve=>requests.push({url,body,resolve}))};c.window=c;
  vm.createContext(c);vm.runInContext(fs.readFileSync(path.join(staticRoot,'first-run.js'),'utf8'),c);
  assert.equal(c.chosenModels.length,0); assert.equal(requests.length,0);
  c.$('projectModelSelect').value=a.path;c.$('projectModelSelect').onchange();
  assert.deepEqual(Array.from(requests[0].body.report_paths),reports.map(r=>r.path));
  requests[0].resolve({reportBinding:{selected:[reports[0]]}});await tick();
  assert.equal(c.chosenReports[0].path,reports[0].path);
  c.$('projectModelSelect').value=b.path;c.$('projectModelSelect').onchange();
  assert.equal(c.chosenReports.length,0,'Old selection must disappear while resolving the new model');
  assert.deepEqual(Array.from(requests[1].body.report_paths),reports.map(r=>r.path));
  c.$('projectModelSelect').value=a.path;c.$('projectModelSelect').onchange();
  requests[1].resolve({reportBinding:{selected:[reports[1]]}});await tick();
  assert.equal(c.chosenReports.length,0,'Late replies cannot restore another model reports');
  requests[2].resolve({reportBinding:{selected:[reports[0]]}});await tick();
  assert.equal(c.chosenReports[0].path,reports[0].path);

  // A project load after model-only analysis must bind the newly discovered model's reports.
  c.$('scopeModelOnly').checked=true;c.renderPills();assert.equal(c.chosenReports.length,0);
  const changedProject=c.smcDiscoverProject('/next-project');
  assert.equal(requests[3].url,'/api/discover');
  requests[3].resolve({models:[b],reports:[reports[1]]});await changedProject;await tick();
  assert.equal(c.$('scopeModelOnly').checked,false,'A different discovered model resets explicit model-only mode');
  assert.equal(requests[4].url,'/api/scope');assert.deepEqual(Array.from(requests[4].body.report_paths),[reports[1].path]);
  requests[4].resolve({reportBinding:{selected:[reports[1]]}});await tick();
  assert.equal(c.chosenReports[0].path,reports[1].path);
  // Refreshing that same project preserves its intentional model-only selection.
  c.$('scopeModelOnly').checked=true;c.renderPills();
  const sameProject=c.smcDiscoverProject('/next-project');
  requests[5].resolve({models:[b],reports:[reports[1]]});await sameProject;await tick();
  assert.equal(c.$('scopeModelOnly').checked,true);assert.equal(c.chosenReports.length,0);assert.equal(requests.length,6);
  for (const file of ['first-run.js','workspace-navigation.js']) {
    const text=fs.readFileSync(path.join(staticRoot,file),'utf8');
    assert(!/[\u00c2\u00c3\ufffd]|\u00e2\u20ac/.test(text),'UTF-8 corruption in '+file);
    assert(text.includes('\u00b7')&&text.includes('\u2014'),'Expected Unicode punctuation in '+file);
  }
  assert(fs.readFileSync(path.join(staticRoot,'first-run.js'),'utf8').includes('\u2026'));

  // Refresh and post-review refresh use exact model-only scope. No Apply is called.
  const refresh={chosenModels:[a],chosenReports:[],logEntry(){},smcModelOnly:()=>true,calls:[],loads:[],disclaimers:0,
    apiPost:async(url,body)=>{refresh.calls.push({url,body});return {items:[]};},
    loadResults:(data,preserve)=>refresh.loads.push({data,preserve}),showPostRefreshDisclaimer:()=>refresh.disclaimers++};refresh.window=refresh;
  vm.createContext(refresh);vm.runInContext(section('async function reAnalyze(opts) {',"$('btnToggleSetup').onclick"),refresh);
  assert.equal((await refresh.reAnalyze({})).ok,true);
  assert.equal((await refresh.reAnalyze({showPostDeleteDisclaimer:true})).ok,true);
  assert.equal(refresh.disclaimers,1);
  assert(refresh.calls.every(c=>c.url==='/api/analyze'&&c.body.report_selection==='exact'&&c.body.report_paths.length===0));
  assert(refresh.loads.every(c=>c.preserve===true));
  refresh.smcModelOnly=()=>false;assert.equal((await refresh.reAnalyze({})).ok,false);assert.equal(refresh.calls.length,2);

  // The generic width controller must target the findings grid, not the earlier inventory.
  const issueGrid={querySelectorAll:()=>[{},{}]}, inventoryGrid={querySelectorAll:()=>[{}]};
  const gridContext={$:()=>({querySelector:selector=>selector==='table.reports-table'?issueGrid:inventoryGrid})};
  vm.createContext(gridContext);vm.runInContext(section('function getTableSectionInfo(', 'function readStoredColumnWidths('),gridContext);
  assert.equal(gridContext.getTableSectionInfo('reportsTableSection').table,issueGrid);
  assert.equal(gridContext.getTableSectionInfo('tableSection').table,inventoryGrid);

  // Zero-finding reports remain in the snapshot; same names retain separate schema counts.
  const inventory={allAnalyzedReports:reports,allReportIssues:[{report:'Overview',reportPath:reports[1].path}],allReportSchema:{reports:[
    {reportPath:reports[0].path,counts:{valid:2,invalid:0,not_validated:0},fileCount:2,complete:true},
    {reportPath:reports[1].path,counts:{valid:0,invalid:1,not_validated:3},fileCount:4,complete:false}]}};
  vm.createContext(inventory);
  vm.runInContext(section('function reportInventoryRows() {','function renderReportInventory() {')+section('function reportReferenceId(reference)', 'function getReportPathForReference'),inventory);
  const rows=inventory.reportInventoryRows();assert.equal(rows.length,2);assert.deepEqual(Array.from(rows,r=>r.findings),[0,1]);
  assert.equal(rows[0].schema.counts.valid,2);assert.equal(rows[1].schema.counts.invalid,1);
  assert(inventory.reportReferenceLabel(reports[0].path).includes(reports[0].path));
  inventory.chosenReports=[];assert.equal(inventory.reportInventoryRows().length,2,'Pending scope edits cannot rewrite analyzed report inventory');
  inventory.allReportSchema=null;assert.equal(inventory.reportInventoryRows()[0].schema,null,'Missing evidence must not look valid');
  inventory.allReportIssues=[];assert.equal(inventory.reportInventoryRows().length,2,'All-clean analysis still has reports');

  ['viewer-dax-format.js','viewer-code-tokens.js','definition-reader.js'].forEach(f=>require(path.join(staticRoot,f)));
  const model={type:'Measure',name:'Revenue',table:'Sales',sourceKind:'model'};
  const localA={type:'Measure',name:'Local',table:'A',sourceKind:'report',sourceFile:'/A/definition/reportExtensions.json'};
  const localB={...localA,table:'B',sourceFile:'/B/definition/reportExtensions.json'};
  const onlyB={...localB,name:'Only B'};
  const items=[model,localA,localB,onlyB];
  const classify=(text,selected,sourceItems=items)=>SmcDefinition.tokens(text,'dax',SmcDefinition.measureHomes(sourceItems,selected));
  assert.equal(classify('[Revenue]',model)[0].kind,'measure');
  assert.equal(classify('[Local]',model)[0].kind,'reference');
  assert.equal(classify("A[Local]",localA)[0].kind,'measure');
  assert.equal(classify("B[Local]",localA)[0].kind,'reference');
  assert.equal(classify('[Only B]',localA)[0].kind,'reference');
  assert.equal(classify('B[Local]',localB)[0].kind,'measure');
  assert.equal(classify('[Revenue]',localA,[...items,{...localA,name:'Revenue'}])[0].kind,'reference','Ambiguous model/local collision remains neutral');
  assert.equal(classify('[constructor]',model)[0].kind,'reference');
  const escaped={...model,name:'A]B',table:"Ta'ble"}, text="'Ta''ble'[A]]B]";
  assert.equal(classify(text,model,[escaped])[0].kind,'measure');assert.equal(classify(text,model,[escaped])[0].text,text);
  console.log('PASS: discovered candidates, model-only refresh, clean report inventory, scoped measure highlighting');
})().catch(error=>{console.error(error);process.exitCode=1;});
