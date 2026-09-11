from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize('layout', ['index.html', 'index_v2.html'])
def test_warnings_render_clear_and_preserve_literal_metadata(layout):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for browser renderer regression')
    template = Path(__file__).parents[1] / 'src/semantic_model_cleaner/templates' / layout
    program = r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8');
const fn=html.match(/function renderWarnings\(\) \{[\s\S]*?\n\}/)[0];
function el(){return {children:[], textContent:'', appendChild(x){this.children.push(x)},
  set innerHTML(x){assert.equal(x,'');this.children=[]},
  classList:{hidden:true,toggle(_k,v){this.hidden=v}}};}
const banner=el(), list=el(), context={document:{createElement:el}, $:id=>id==='warningBanner'?banner:list,
  allWarnings:[{message:'<script>unsafe()</script>',artifactPath:'<private>.tmdl'},'Scope warning']};
vm.createContext(context);vm.runInContext(fn,context);context.renderWarnings();
assert.equal(banner.classList.hidden,false);assert.equal(list.children.length,2);
assert.equal(list.children[0].textContent,'<script>unsafe()</script>');
assert.equal(list.children[0].children[0].textContent,'<private>.tmdl');
context.allWarnings=[];context.renderWarnings();
assert.equal(banner.classList.hidden,true);assert.equal(list.children.length,0);
'''
    subprocess.run([node, '-e', program, str(template)], check=True, capture_output=True, text=True)
