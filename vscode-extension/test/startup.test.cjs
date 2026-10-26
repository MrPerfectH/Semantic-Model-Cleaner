const { test } = require('node:test');
const assert = require('node:assert/strict');
const Module = require('node:module');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'smc-startup-'));
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return { promise, resolve }; };
const disposable = () => ({ dispose() {} });
let host;
class Cancelled extends Error {}
class ServerManager {
  async start(_config, _ancestors, _log, onExit) { host.starts++; host.exit=onExit; if(host.startFailure)throw new Error(host.startFailure); return { port: 1234, request: async (_, body) => {
    host.requests.push(body); if (host.discovery) await host.discovery.promise;
    if (host.failure) throw new Error(host.failure);
    return { project: root, models: [{name:'Alpha',path:'Alpha.SemanticModel'}, {name:'Beta',path:'Beta.SemanticModel'}],
      model: body.model_path || null, modelExclusions: [], reports: [], unverifiedReports: [], otherReportCount: 0 };
  } }; }
  async stop() { host.stops++; }
}
const vscode = {
  ViewColumn:{One:1}, UIKind:{Desktop:1,Web:2}, env:{uiKind:1}, StatusBarAlignment:{Left:1},
  TreeItemCollapsibleState:{None:0,Collapsed:1,Expanded:2}, TreeItemCheckboxState:{Unchecked:0,Checked:1},
  EventEmitter:class { constructor(){this.event=()=>disposable();} fire(){} dispose(){} },
  TreeItem:class { constructor(label,collapsibleState){Object.assign(this,{label,collapsibleState});} },
  ThemeIcon:class { constructor(id){this.id=id;} },
  workspace:{isTrusted:true, workspaceFolders:[], getConfiguration(){host.reads++;return {get:(key,fallback)=>key==='executable'?'smc-web':fallback};}},
  commands:{registerCommand(name,fn){host.commands.set(name,fn);return disposable();},async executeCommand(name){host.executed.push(name);}},
  window:{createTreeView:()=>({...disposable(),onDidChangeCheckboxState:()=>disposable()}),registerTreeDataProvider:()=>disposable(),
    createOutputChannel:()=>({...disposable(),clear(){},append(){},show(){}}),createStatusBarItem:()=>({...disposable(),show(){}}),
    showErrorMessage:async message=>{host.errors.push(message);},
    showOpenDialog:async()=>{host.folders++;return host.folderPicker ? host.folderPicker.promise : [uri];},
    showQuickPick:async items=>{host.pickers++;host.items=items;return host.modelPicker ? host.modelPicker.promise : host.choice ? items.find(x=>x.path===host.choice) : undefined;},
    createWebviewPanel:()=>{host.panels++;return host.panel={...disposable(),reveal(){},onDidDispose(){},webview:{onDidReceiveMessage(fn){host.receive=fn;},postMessage(message){host.messages.push(message);}}};}}
};
const uri={scheme:'file',fsPath:root,toString:()=>root};
const original=Module._load;
Module._load=function(name,...args){
  if(name==='vscode')return vscode;
  if(name==='./server' && args[0]?.filename.endsWith('extension.js'))return {Cancelled,ServerManager};
  if(name==='./panel' && args[0]?.filename.endsWith('extension.js'))return {HOST_SCOPE:'scope',getAncestors:async()=>{if(host.ancestors)await host.ancestors.promise;return [];},
    showApp(){host.receive({type:'smc-page-ready'});},showMessage(){}};
  return original.call(this,name,...args);
};
const extension=require('../dist/extension');Module._load=original;
function setup(){host={commands:new Map(),executed:[],errors:[],messages:[],requests:[],starts:0,stops:0,reads:0,panels:0,folders:0,pickers:0};
  vscode.workspace.isTrusted=true;vscode.workspace.workspaceFolders=[{uri}];vscode.env.remoteName=undefined;vscode.env.uiKind=1;
  extension.activate({subscriptions:[]});return host;}
const command=name=>host.commands.get('semanticModelCleaner.'+name)();
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function until(check){
  // Startup awaits real filesystem I/O; immediate turns are not a time budget.
  const deadline=performance.now()+5000;
  while(!check()){
    assert.ok(performance.now()<deadline,'condition not reached within 5000 ms');
    await new Promise(resolve=>setTimeout(resolve,5));
  }
}
const analyzed=()=>host.messages.filter(m=>m.analyze);

test('cold Choose waits for discovery, reveals native scope and picks explicitly without analysis',async()=>{
  setup();host.discovery=deferred();host.choice='Beta.SemanticModel';
  const pending=command('chooseModel');await until(()=>host.requests.length===1);
  assert.equal(host.pickers,0);assert.equal(analyzed().length,0);
  host.discovery.resolve();await pending;
  assert.equal(host.starts,1);assert.equal(host.pickers,1);assert.equal(host.items.length,2);
  assert.equal(host.requests.at(-1).model_path,'Beta.SemanticModel');assert.equal(analyzed().length,0);
  assert.ok(host.executed.includes('semanticModelCleaner.scope.focus'));assert.deepEqual(host.errors,[]);
  await extension.deactivate();
});
test('cold Analyze waits, asks among multiple models, then analyzes only explicit selection',async()=>{
  setup();host.choice='Alpha.SemanticModel';await command('analyze');
  assert.equal(host.pickers,1);assert.equal(analyzed().length,1);
  assert.equal(host.executed.filter(name=>name==='semanticModelCleaner.scope.focus').length,1, 'one focus before the native model picker');
  assert.equal(analyzed()[0].scope.model.path,'Alpha.SemanticModel');assert.deepEqual(host.errors,[]);
  await extension.deactivate();
});
test('Open never analyzes; commands during startup share it and await discovery',async()=>{
  setup();host.discovery=deferred();const opening=command('open');await until(()=>host.requests.length===1);
  const choose=command('chooseModel');await tick();assert.equal(host.pickers,0);
  host.discovery.resolve();await Promise.all([opening,choose]);assert.equal(host.starts,1);assert.equal(host.pickers,1);
  assert.equal(analyzed().length,0);assert.deepEqual(host.errors,[]);await extension.deactivate();
});
test('canceled folder picker ends cold Analyze with no launch, selection, or error',async()=>{
  setup();vscode.workspace.workspaceFolders=[];host.folderPicker=deferred();const pending=command('analyze');
  await until(()=>host.folders===1);host.folderPicker.resolve(undefined);await pending;
  assert.equal(host.starts,0);assert.equal(host.pickers,0);assert.equal(host.reads,0);assert.deepEqual(host.errors,[]);
  await extension.deactivate();
});
test('Stop during startup prevents a late Analyze and server launch',async()=>{
  setup();host.ancestors=deferred();const pending=command('analyze');await until(()=>host.panels===1);
  await command('stop');host.ancestors.resolve();await pending;
  assert.equal(host.starts,0);assert.equal(host.reads,0);assert.equal(host.pickers,0);assert.equal(analyzed().length,0);
  await extension.deactivate();
});
test('Stop during discovery prevents late model picker and analysis',async()=>{
  setup();host.discovery=deferred();const pending=command('analyze');await until(()=>host.requests.length===1);
  await command('stop');host.discovery.resolve();await pending;
  assert.equal(host.pickers,0);assert.equal(analyzed().length,0);assert.deepEqual(host.errors,[]);await extension.deactivate();
});
test('opening another folder during discovery abandons the old Analyze action',async()=>{
  setup();host.discovery=deferred();const pending=command('analyze');await until(()=>host.requests.length===1);
  const other=path.join(root,'other');fs.mkdirSync(other,{recursive:true});
  const next=host.commands.get('semanticModelCleaner.open')({scheme:'file',fsPath:other,toString:()=>other});
  await until(()=>host.requests.length===2);host.discovery.resolve();await Promise.all([pending,next]);
  assert.equal(host.starts,2);assert.equal(host.pickers,0);assert.equal(analyzed().length,0);assert.deepEqual(host.errors,[]);
  await extension.deactivate();
});
test('Stop while a model picker is open ignores the late choice',async()=>{
  setup();host.modelPicker=deferred();const pending=command('analyze');await until(()=>host.pickers===1);
  await command('stop');host.modelPicker.resolve({path:'Alpha.SemanticModel'});await pending;
  assert.equal(host.requests.length,1);assert.equal(analyzed().length,0);await extension.deactivate();
});
test('trust lost during startup blocks configuration and launch',async()=>{
  setup();host.ancestors=deferred();const pending=command('analyze');await until(()=>host.panels===1);
  vscode.workspace.isTrusted=false;host.ancestors.resolve();await pending;
  assert.equal(host.starts,0);assert.equal(host.reads,0);assert.match(host.errors[0],/Trust this workspace/);await extension.deactivate();
});
test('canceling Analyze model choice never analyzes',async()=>{
  setup();await command('analyze');assert.equal(host.pickers,1);assert.equal(analyzed().length,0);assert.deepEqual(host.errors,[]);
  await extension.deactivate();
});
test('scope commands check trust and remote support before folder, settings and spawn',async()=>{
  for(const blocked of ['trust','remote','web']){
    setup();vscode.workspace.isTrusted=blocked!=='trust';vscode.env.remoteName=blocked==='remote'?'ssh-remote':undefined;vscode.env.uiKind=blocked==='web'?2:1;
    for(const name of ['chooseModel','analyze','selectModel','selectAllReports','clearReports','refreshScope'])await command(name);
    assert.equal(host.errors.length,6);assert.equal(host.starts,0);assert.equal(host.reads,0);assert.equal(host.folders,0);assert.equal(host.panels,0);
    await extension.deactivate();
  }
});
test('trust lost while picking a folder blocks settings and process startup',async()=>{
  setup();vscode.workspace.workspaceFolders=[];host.folderPicker=deferred();const pending=command('chooseModel');
  await until(()=>host.folders===1);vscode.workspace.isTrusted=false;host.folderPicker.resolve([uri]);await pending;
  assert.equal(host.starts,0);assert.equal(host.reads,0);assert.match(host.errors[0],/Trust this workspace/);await extension.deactivate();
});
test('discovery failure reports retry and logs instead of an old startup prerequisite',async()=>{
  setup();host.failure='Discovery unavailable';await command('analyze');assert.match(host.errors[0],/Discovery unavailable.*Refresh Models and Reports.*Show Logs/);
  assert.equal(analyzed().length,0);await extension.deactivate();
});

for(const action of ['chooseModel','analyze']){
  test(`${action} queued during the initial folder picker continues after discovery`,async()=>{
    setup();vscode.workspace.workspaceFolders=[];host.folderPicker=deferred();host.discovery=deferred();
    host.choice='Beta.SemanticModel';const opening=command('open');await until(()=>host.folders===1);
    const pending=command(action);host.folderPicker.resolve([uri]);await until(()=>host.requests.length===1);
    assert.equal(host.pickers,0);assert.equal(analyzed().length,0);
    host.discovery.resolve();await Promise.all([opening,pending]);
    assert.equal(host.starts,1);assert.equal(host.pickers,1);
    assert.equal(host.requests.at(-1).model_path,'Beta.SemanticModel');
    assert.equal(analyzed().length,action==='analyze'?1:0);assert.deepEqual(host.errors,[]);
    await extension.deactivate();
  });
}
for(const interruption of ['cancel','stop','switch','trust']){
  test(`queued Choose during folder selection respects ${interruption}`,async()=>{
    setup();vscode.workspace.workspaceFolders=[];host.folderPicker=deferred();host.choice='Alpha.SemanticModel';
    const opening=command('open');await until(()=>host.folders===1);const pending=command('chooseModel');
    if(interruption==='stop')await command('stop');
    if(interruption==='trust')vscode.workspace.isTrusted=false;
    if(interruption==='switch'){
      const other=path.join(root,'switched');fs.mkdirSync(other,{recursive:true});
      await host.commands.get('semanticModelCleaner.open')({scheme:'file',fsPath:other,toString:()=>other});
    }
    host.folderPicker.resolve(interruption==='cancel'?undefined:[uri]);await Promise.all([opening,pending]);
    assert.equal(host.pickers,0);assert.equal(analyzed().length,0);
    assert.equal(host.starts,interruption==='switch'?1:0);
    if(interruption==='trust')assert.ok(host.errors.every(message=>/Trust this workspace/.test(message)));
    else assert.deepEqual(host.errors,[]);
    await extension.deactivate();
  });
}
for(const failure of ['start','exit']){
  test(`Open and Choose retry the same folder after ${failure} without analysis`,async()=>{
    setup();
    if(failure==='start')host.startFailure='Launch failed';
    await command('open');
    if(failure==='start'){assert.match(host.errors[0],/Launch failed/);host.startFailure=undefined;}
    else host.exit();
    await command('open');assert.equal(host.starts,2);assert.equal(host.pickers,0);assert.equal(analyzed().length,0);
    host.exit();host.choice='Alpha.SemanticModel';await command('chooseModel');
    assert.equal(host.starts,3);assert.equal(host.pickers,1);assert.equal(host.requests.at(-1).model_path,'Alpha.SemanticModel');
    assert.equal(analyzed().length,0);await extension.deactivate();
  });
}
process.on('exit',()=>fs.rmSync(root,{recursive:true,force:true}));
