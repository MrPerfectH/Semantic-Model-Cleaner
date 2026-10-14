const {chromium}=require(process.env.SMC_PLAYWRIGHT_MODULE || 'playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=process.env.SMC_EVIDENCE_DIR;
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/embedded-test',route=>route.fulfill({status:200,contentType:'text/html',body:fs.readFileSync(path.join(root,'embedded-page.html'),'utf8')}));
 await page.goto(process.env.SMC_BASE_URL + '/embedded-test',{waitUntil:'networkidle'});
 assert(await page.locator('body').evaluate(el=>el.classList.contains('sidebar-owned-scope')));
 assert.equal(await page.locator('#scopeModelOnly').count(),0);
 await page.evaluate(()=>smcOpenScope());
 assert.equal(await page.locator('#scopeDrawer').isVisible(),false);
 assert.equal(await page.locator('#scopeChip').isVisible(),false);
 assert.equal(await page.locator('.object-scope-strip').isVisible(),false);
 assert.equal(await page.locator('#viewTabs>button:not(.detail-tab)').count(),4);
 await page.getByRole('button',{name:'Settings',exact:true}).click();
 assert.equal(await page.locator('#workspaceSettings').isVisible(),true);
 assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(root,'embedded-browser-evidence.json'),JSON.stringify({host:process.env.COMPUTERNAME,mode:'rendered sidebar-owned host page',noInPageScope:true,mainEntries:4,settingsSeparate:true,nativeInstalledAcceptance:false,errors},null,2));
 console.log('EMBEDDED PRESENTATION PASS');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
