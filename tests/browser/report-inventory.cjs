// Reusable check against a running analyzed Reports page; never calls Apply.
// Reports leads with what is missing from the model, then every finding row.
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
      const lead = await page.locator('#missingItemsHost .mi-kpis').boundingBox();
      assert(lead && lead.y >= 0 && lead.y + lead.height < 800, 'Error summary must be visible without scrolling: ' + JSON.stringify(lead));
    }
    assert.equal(summary.direction, 'row'); assert.equal(summary.wrap, 'wrap');
    assert(summary.subrows.every(display=>display==='none'));
    if (summary.display !== 'none') assert(summary.rows.every(row=>row.right<=summary.right+1));
    const state = await page.evaluate(() => ({
      sentence: $('reportsFindingSummary').textContent,
      items: (window.smcMissingItems ? document.querySelectorAll('#missingItemsHost .mi-row').length : -1),
      expected: allReportIssues.some(i => i.missingItemKey) ? new Set(allReportIssues.map(i => i.missingItemKey).filter(Boolean)).size : 0,
      oldPanels: [...document.querySelectorAll('#reportsTableSection #reportHealthBanner, #reportsTableSection .schema-evidence, #reportInventory')].filter(n => n.offsetParent !== null).length,
      pageWidth: document.documentElement.scrollWidth, viewport: innerWidth,
    }));
    assert(state.sentence.length > 0, 'Reports must open with a plain summary sentence');
    assert.equal(state.items, state.expected, 'One row per missing model item');
    assert.equal(state.oldPanels, 0, 'Raw findings, schema evidence and the report table are not on the Reports screen');
    assert(state.pageWidth <= state.viewport + 1, JSON.stringify(state));
    assert.equal(await page.evaluate(() => getTableSectionInfo('reportsTableSection').table.classList.contains('reports-table')), true);
    await page.locator('#inventoryColumnMenu summary').click();
    assert.equal(await page.locator('#inventoryColumnOptions label').count(),6,'Chooser must contain only the seven-column findings grid');
    await page.locator('#inventoryColumnMenu summary').click();
    results.push({viewport:width,summary,state});
  }
  return results;
};
