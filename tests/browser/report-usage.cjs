// Run against a disposable Cleaner server. Uses its bundled demo; never calls Apply.
const {chromium}=require(process.env.SMC_PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{const browser=await chromium.launch({headless:true});try {
  const page=await browser.newPage({viewport:{width:1280,height:800}}), errors=[],blocked=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/api/**',route=>{const request=route.request(),url=new URL(request.url()).pathname;
    if (!['GET','HEAD'].includes(request.method()) && !['/api/demo','/api/scope','/api/analyze','/api/analysis-jobs'].includes(url)) {blocked.push(url);return route.abort();}
    return route.continue();
  });
  await page.goto(process.env.SMC_BASE_URL,{waitUntil:'networkidle'});
  await page.evaluate(()=>{smcCloseScope();switchView('refs');});
  const state=()=>page.locator('#reportUsageStatus').getAttribute('data-state');
  assert.equal(await state(),'unloaded');
  assert.equal((await page.locator('#tabRefs').textContent()).trim(),'Report usage');
  assert.equal(await page.locator('#tabRefsCount').innerText(),'');
  assert.equal(await page.locator('.policy-dialog,[data-review-finding],#policyContent').count(),0);
  assert.equal(await page.getByRole('button',{name:/^(Review policy|Review decisions|Record decision|Saved decisions|Naming rules)$/}).count(),0);
  assert.equal(await page.evaluate(()=>typeof smcNamingDrafts),'undefined');
  assert.equal((await page.request.get(new URL('/static/policy-workspace.js',process.env.SMC_BASE_URL).href)).status(),404);
  await page.evaluate(()=>smcLoadDemo()); await page.waitForFunction(()=>chosenModels.length===1 && chosenReports.length>0);
  assert.equal(await page.locator('[data-scope-step]').count(),3);
  await page.locator('[data-scope-step="1"]').click();await page.locator('[data-scope-step="2"]').click();
  await page.locator('#btnAnalyze').click();await page.waitForFunction(()=>allItems.length>0);
  await page.evaluate(()=>{smcCloseScope();switchView('refs');});
  assert.equal(await state(),'ready');
  const loaded=await page.evaluate(()=>({raw:allRefs.length,total:allRefs.filter(SmcReportUsage.isReportRow).length,filtered:filteredRefs.length,scope:{model_paths:chosenModels.map(m=>m.path),report_paths:chosenReports.map(r=>r.path)}}));
  assert(loaded.total>0);assert.equal(loaded.filtered,loaded.total);
  const syncResponse=await page.evaluate(async scope=>{const response=await smcFetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(scope)});return {ok:response.ok,data:await response.json()};},loaded.scope);assert(syncResponse.ok,JSON.stringify(syncResponse));
  const snapshot=syncResponse.data;
  await require('./compact-results.cjs')(page);
  // Scan details must lead to visible content, including informational zero-impact rows.
  for(const kind of ['zero','informational','impacted','zero','informational']){
    const count=kind==='zero'?0:1,affected=kind==='impacted'?1:0;
    const limits={distinctCount:count,affectedItemCount:affected,sharedCount:0,limitations:count?[{feature:'Synthetic coverage',scope:'item',affectedItemCount:affected,location:'synthetic.tmdl',checked:'Supported metadata',unchecked:'Synthetic unsupported metadata',effect:affected?'Review affected item':'No cleanup recommendations changed'}]:[]};
    await page.evaluate(data=>{loadResults(data);switchView('details');},{...snapshot,analysisLimitations:limits});
    assert.equal(await page.locator('#overviewLimitations').isVisible(),!!count,kind);
    if(count){
      await page.locator('#overviewLimitations').click();
      assert(await page.locator('#analysisLimitationsBanner').isVisible(),kind);
      assert(await page.locator('#analysisLimitationsHint').isVisible(),kind);
      assert((await page.locator('#analysisLimitationsHint').innerText()).includes(affected?'affected item':'Informational'),kind);
      assert.equal(await page.locator('#analysisLimitationsList .limitation-card').count(),1);
    }else{assert(await page.locator('#tableSection').isVisible());assert(!(await page.locator('#tabLimitations').isVisible()));}
  }
  await page.evaluate(data=>{loadResults(data);switchView('details');},snapshot);

  await page.evaluate(data=>{smcRenderResultOverview({...data,analysisLimitations:{affectedItemCount:1,sharedCount:1},reportHealth:{totalIssueCount:1}});allWarnings=[{code:'UNRESOLVED_NAMEOF_TARGET',message:'Synthetic unresolved field'}];renderWarnings();},snapshot);
  assert((await page.locator('#overviewLimitations').innerText()).includes('Coverage limitations'));
  assert(await page.locator('#warningBanner').isVisible());
  assert(await page.locator('#overviewReportFindings').isVisible());
  await page.evaluate(data=>{loadResults(data);switchView('refs');},snapshot);
assert.equal(snapshot.references.filter(r=>r.report||r.reportPath).length,loaded.total);
  const refresh=await page.evaluate(()=>reAnalyze({}));assert(refresh.ok);
  assert.equal(await page.evaluate(()=>filteredRefs.length),loaded.total);
  await page.locator('#filterSearch').fill('no-such-field-usage');await page.evaluate(()=>applyFilters());
  assert.equal(await state(),'filtered-empty');assert((await page.locator('#reportUsageStatus').innerText()).includes('0 of '+loaded.total));
  await page.locator('#reportUsageClear').click();assert.equal(await state(),'ready');
  assert.equal(await page.evaluate(()=>filteredRefs.length),loaded.total);
  // Render a synthetic zero-use snapshot with analyzed reports and raw placeholders retained.
  const empty=JSON.parse(JSON.stringify(snapshot));empty.references=empty.references.filter(r=>!r.report&&!r.reportPath);
  await page.evaluate(data=>loadResults(data),empty);assert.equal(await state(),'empty');
  assert.equal(await page.evaluate(()=>allRefs.length),empty.references.length);
  const missing=JSON.parse(JSON.stringify(snapshot));delete missing.references;
  await page.evaluate(data=>loadResults(data),missing);assert.equal(await state(),'unavailable');
  await page.evaluate(data=>loadResults(data),snapshot);assert.equal(await state(),'ready');
  // A real intercepted transport failure must be distinct from successful zero usage.
  let release;const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/analysis-jobs',async route=>{await gate;await route.fulfill({status:503,json:{error:'Synthetic analysis unavailable'}});});
  await page.evaluate(()=>{window.usageRefresh=reAnalyze({});});await page.waitForFunction(()=>document.getElementById('reportUsageStatus').dataset.state==='loading');
  assert.equal(await page.evaluate(()=>allRefs.length),snapshot.references.length);
  release();assert.equal((await page.evaluate(()=>usageRefresh)).ok,false);assert.equal(await state(),'error');
  assert((await page.locator('#reportUsageStatus').innerText()).includes('Previous analysis'));
  assert.equal(await page.evaluate(()=>allRefs.length),snapshot.references.length);
  await page.unroute('**/api/analysis-jobs');
  await page.evaluate(()=>{smcOpenScope();$('scopeModelOnly').checked=true;$('scopeModelOnly').onchange();});
  assert.equal((await page.evaluate(()=>reAnalyze({}))).ok,true);
  await page.evaluate(()=>{smcCloseScope();switchView('refs');});assert.equal(await state(),'model-only');
  assert.equal(await page.evaluate(()=>filteredRefs.length),0);
  assert.deepEqual(errors,[]);assert.deepEqual(blocked,[]);
  const receipt={host:process.env.COMPUTERNAME,loaded,states:['unloaded','ready','filtered-empty','empty','unavailable','loading','error','model-only'],syncAndAsyncParity:true,refreshParity:true,policyUiAbsent:true,standaloneWizard:true,errors,blocked};
  if(process.env.SMC_EVIDENCE_DIR){fs.writeFileSync(path.join(process.env.SMC_EVIDENCE_DIR,'report-usage-browser.json'),JSON.stringify(receipt,null,2));await page.screenshot({path:path.join(process.env.SMC_EVIDENCE_DIR,'report-usage-model-only.png'),fullPage:true});}
  console.log('REPORT USAGE BROWSER PASS',JSON.stringify({raw:loaded.raw,total:loaded.total,states:receipt.states}));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
