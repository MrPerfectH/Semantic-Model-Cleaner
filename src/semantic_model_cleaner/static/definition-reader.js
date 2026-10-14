/* Display-only adapter for the MIT Viewer tokenizers/formatter. */
(function (g) {
  'use strict';
  function tokens(source, language) {
    if (language === 'm') {
      var lex = g.PowerQuery.tokens(source), at = 0, out = [];
      lex.tokens.forEach(function (t) {
        if (t.start > at) out.push({text:source.slice(at,t.start),kind:'comment'});
        out.push({text:source.slice(t.start,t.end),kind:t.kind === 'string' ? 'm-string' : /^(let|in|each|if|then|else|meta|as|type)$/.test(t.value) ? 'm-keyword' : 'text'});
        at=t.end;
      });
      if (at < source.length) out.push({text:source.slice(at),kind:'comment'});
      return out;
    }
    return g.ViewerDaxTokens.call({app:{model:{msrHome:{}}}},source).map(function (t) {
      var kind = t.cmt != null ? 'comment' : t.str != null ? 'string' : t.col != null ? 'reference' : t.msr != null ? 'measure' : t.fn != null ? 'function' : t.kw != null ? 'keyword' : 'text';
      return {kind:kind,text:t.raw != null ? t.raw : t.cmt != null ? t.cmt : t.str != null ? t.str : t.col != null ? t.col : t.fn != null ? t.fn : t.kw != null ? t.kw : t.txt || ''};
    });
  }
  function presentation(source, language, formatted) {
    source = String(source || '');
    if (!formatted || language === 'm') return {text:source,formatted:false};
    try {
      if (source.length > 200000) return {text:source,formatted:false,error:'Source exceeds the formatter limit. Showing exact source.'};
      return {text:g.DaxFormat.toText(g.DaxFormat.format(source,{style:'long'})),formatted:true};
    } catch (e) { return {text:source,formatted:false,error:'Formatting unavailable. Showing exact source: ' + e.message}; }
  }
  function render(pre, source, language, formatted) {
    if (!pre) return;
    var result = presentation(source,language,formatted);
    pre.replaceChildren(); pre.classList.add('viewer-code-reader'); pre.dataset.formatted = String(result.formatted);
    pre.dataset.sourceLength = String(source.length); pre.setAttribute('aria-label',(result.formatted ? 'Formatted DAX' : language === 'm' ? 'M source' : 'DAX source') + ' · read only');
    var line = document.createElement('span'); line.className = 'viewer-code-line'; pre.appendChild(line);
    tokens(result.text,language).forEach(function (token) {
      var parts = token.text.split('\n');
      parts.forEach(function (part,index) {
        if (index) { pre.appendChild(document.createTextNode('\n')); line=document.createElement('span');line.className='viewer-code-line';pre.appendChild(line); }
        var span=document.createElement('span'); span.className='viewer-'+token.kind; span.textContent=part; line.appendChild(span);
      });
    });
    return result;
  }
  g.SmcDefinition = {tokens:tokens,presentation:presentation,render:render};
})(typeof window !== 'undefined' ? window : globalThis);
