// Reusable check against a running analyzed Reports page; never calls Apply.
const assert = require('node:assert/strict');
module.exports = async function verifyReportInventory(page) {
  const results = [];
  for (const width of [1280, 900, 720]) {
    await page.setViewportSize({width, height:800});
    await page.evaluate(() => { switchView('reports'); applyTableWidths('reportsTableSection', calculateDefaultWidths('reportsTableSection')); });
    await page.evaluate(() => { scrollTo(0, 0); document.querySelectorAll('*').forEach(node => { if (node.scrollTop) node.scrollTop = 0; }); });
    const summary = await page.locator('#summarySection').evaluate(node => ({height:node.getBoundingClientRect().height,display:getComputedStyle(node).display,direction:getComputedStyle(node).flexDirection,wrap:getComputedStyle(node).flexWrap,subrows:[...node.querySelectorAll('.rail-subrow')].map(row=>getComputedStyle(row).display),rows:[...node.querySelectorAll('.rail-row:not(.rail-subrow)')].map(row=>({top:row.getBoundingClientRect().top,right:row.getBoundingClientRect().right})),right:node.getBoundingClientRect().right}));
    if (width === 1280) {
      assert(summary.height > 0 && summary.height < 100, JSON.stringify(summary));
      const inventory = await page.locator('#reportInventory thead').boundingBox();
      assert(inventory.y >= 0 && inventory.y + inventory.height < 800, JSON.stringify(inventory));
    }
    assert.equal(summary.direction, 'row'); assert.equal(summary.wrap, 'wrap');
    assert(summary.subrows.every(display=>display==='none'));
    if (summary.display !== 'none') assert(summary.rows.every(row=>row.right<=summary.right+1));
    const headers = await page.locator('#reportInventory thead th').evaluateAll(nodes => nodes.map(node => ({label:node.textContent.trim(),display:getComputedStyle(node).display,width:node.getBoundingClientRect().width})));
    assert.deepEqual(headers.map(h=>h.label), ['Report','Finding rows','Valid','Invalid','Not validated','Schema coverage']);
    assert(headers.every(h=>h.display !== 'none' && h.width > 0), JSON.stringify(headers));
    const layout = await page.locator('#reportInventory').evaluate(node => ({width:node.clientWidth,scrollWidth:node.scrollWidth,overflow:getComputedStyle(node).overflowX,pageWidth:document.documentElement.scrollWidth,viewport:innerWidth}));
    assert(layout.width > 0 && layout.pageWidth <= layout.viewport + 1, JSON.stringify(layout));
    if (layout.scrollWidth > layout.width) assert(['auto','scroll'].includes(layout.overflow));
    assert.equal(await page.evaluate(() => getTableSectionInfo('reportsTableSection').table.classList.contains('reports-table')), true);
    await page.locator('#inventoryColumnMenu summary').click();
    assert.equal(await page.locator('#inventoryColumnOptions label').count(),6,'Chooser must contain only the seven-column findings grid');
    await page.locator('#inventoryColumnMenu summary').click();
    results.push({viewport:width,summary,headers,layout});
  }
  return results;
};
