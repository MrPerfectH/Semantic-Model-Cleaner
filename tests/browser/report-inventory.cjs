// Reusable check against a running analyzed Reports page; never calls Apply.
const assert = require('node:assert/strict');
module.exports = async function verifyReportInventory(page) {
  const results = [];
  for (const width of [1280, 720]) {
    await page.setViewportSize({width, height:800});
    await page.evaluate(() => { switchView('reports'); applyTableWidths('reportsTableSection', calculateDefaultWidths('reportsTableSection')); });
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
    results.push({viewport:width,headers,layout});
  }
  return results;
};
