// Reusable presentation assertions for an analyzed disposable or read-only page.
const assert=require('node:assert/strict');
module.exports=async function verifyCompactResults(page) {
  const layouts=[];
  await page.evaluate(()=>{switchView('details');$('filterSearch').value='';filterState.filterRisk=[];applyFilters();});
  assert.equal(await page.locator('#resultOverview #summarySection').count(),1);
  assert.equal(await page.locator('#resultOverview #resultGuideSection').count(),1);
  assert.equal(await page.locator('#resultOverview .result-count').count(),4);
  assert.equal(await page.locator('.result-facts,.result-overview-heading').count(),0);
  for(const id of ['sumSafe','sumReview','sumCaution','sumKeep','sumTotal']) assert.equal(await page.locator('#'+id).count(),1);
  for(const width of [1280,720]) {
    await page.setViewportSize({width,height:800});
    await page.evaluate(()=>document.querySelectorAll('*').forEach(node=>{if(node.scrollTop)node.scrollTop=0;}));
    const layout=await page.evaluate(()=>({width:innerWidth,tableTop:$('tableSection').getBoundingClientRect().top,headerHeight:$('resultOverview').getBoundingClientRect().height,pageWidth:document.documentElement.scrollWidth,visibleRows:[...$('tableBody').querySelectorAll('tr[data-key]')].filter(row=>{const r=row.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}).length}));
    assert(layout.pageWidth<=width+1,JSON.stringify(layout));
    assert(layout.tableTop <= (width===1280?320:430),JSON.stringify(layout));
    assert(layout.visibleRows >= (width===1280?6:4),JSON.stringify(layout));
    layouts.push(layout);
  }
  await page.setViewportSize({width:1280,height:800});
  const safe=await page.evaluate(()=>allItems.filter(i=>deleteSafetyValue(i)==='Safe').length);
  await page.locator('[data-cleanup="Safe"]').click();
  assert.equal(await page.evaluate(()=>filteredItems.length),safe);
  assert.equal(await page.locator('[data-cleanup="Safe"]').getAttribute('aria-pressed'),'true');
  await page.locator('[data-cleanup="Safe"]').click();
  assert.equal(await page.evaluate(()=>filteredItems.length),await page.evaluate(()=>allItems.length));
  await page.locator('#resultInventory>summary').click();assert(await page.locator('#sumMeasures').isVisible());await page.locator('#resultInventory>summary').click();
  await page.locator('#resultScope>summary').click();assert((await page.locator('#resultScopeBody').innerText()).includes('Other reports and Power BI runtime behavior are not verified'));await page.locator('#resultScope>summary').click();
  await page.locator('#resultGuideSection>summary').click();assert(await page.locator('#resultGuideBody').isVisible());assert((await page.locator('#resultGuideBody').innerText()).includes('Safe is limited to the selected scope'));await page.locator('#resultGuideSection>summary').click();
  if(await page.locator('#overviewLimitations').isVisible()){await page.locator('#overviewLimitations').click();assert(await page.locator('#analysisLimitationsBanner').isVisible());}
  await page.evaluate(()=>switchView('details'));
  return layouts;
};
