/* Static metadata inspection only. No M evaluator, connector calls or model writes. */
(function(g){
  'use strict';
  var keywords=new Set('let in each if then else try otherwise error as is meta type nullable optional true false null and or not section shared'.split(' '));
  var types=new Set('any anynonnull binary date datetime datetimezone duration logical none number record table text time list function'.split(' '));
  function tokens(code){
    var out=[], warnings=[], re=/\s+|\/\/[^\r\n]*|\/\*[\s\S]*?\*\/|#"(?:[^"]|"")*"|"(?:[^"]|"")*"|(?:#[A-Za-z_]+|[A-Za-z_][\w]*)(?:\.[A-Za-z_][\w]*)*|\d+(?:\.\d+)?|=>|[^]/g,m;
    while((m=re.exec(code))){var s=m[0];if(/^\s|^\/\/|^\/\*/.test(s))continue;var kind=/^#"/.test(s)?'id':/^"/.test(s)?'string':/^[A-Za-z_#]/.test(s)?'id':'punct';
      var value=kind==='id'&&s.startsWith('#"')?s.slice(2,-1).replace(/""/g,'"').replace(/#\(([^)]+)\)/g,function(all,x){if(x==='#')return '#';if(/^[0-9a-f]{4,8}$/i.test(x)&&parseInt(x,16)<=0x10ffff)return String.fromCodePoint(parseInt(x,16));warnings.push('Unsupported identifier escape '+all);return all;}):s;
      out.push({value:value,raw:s,kind:kind,start:m.index,end:re.lastIndex});
    }
    if(/\/\*/.test(code)&&!out.length&& !/\*\//.test(code))warnings.push('Unclosed comment');
    return {tokens:out,warnings:warnings};
  }
  g.PowerQuery={tokens:tokens};
})(typeof window !== 'undefined' ? window : globalThis);

(function(g) { g.ViewerDaxTokens = function (dax) {
      var H = (this.app.model || {}).msrHome || {}, out = [], names = Object.create(null);
      Object.keys(H).forEach(function (name) { names[name.toLowerCase()] = name; });
      var re = /(\/\/[^\n]*|--[^\n]*|\/\*[\s\S]*?\*\/)|("(?:[^"]|"")*")|((?:(?:'(?:[^']|'')+'|[A-Za-z_\u0080-\uffff][A-Za-z0-9_.\u0080-\uffff]*)\s*)?\[(?:[^\]\r\n]|\]\])+\])/g;
      var pushTxt = function (s) {
        if (!s) return;
        var fre = /\b[A-Za-z_][A-Za-z0-9._]*(?=\s*\()|\b(VAR|RETURN|DEFINE|MEASURE|EVALUATE|IN|NOT|TRUE|FALSE)\b/gi;
        var l = 0, x;
        while ((x = fre.exec(s))) {
          if (x.index > l) out.push({ txt: s.slice(l, x.index) });
          if (x[1] != null) out.push({ kw: x[0] }); else out.push({ fn: x[0] });
          l = x.index + x[0].length;
        }
        if (l < s.length) out.push({ txt: s.slice(l) });
      };
      var last = 0, m, __g = 0;
      while ((m = re.exec(dax))) {
        if (++__g > 50000) throw new Error('LOOP-GUARD: daxToks');
        if (m.index > last) pushTxt(dax.slice(last, m.index));
        if (m[1] != null) out.push({ cmt: m[0] });
        else if (m[2] != null) out.push({ str: m[0] });
        else {
          var ref = m[0], parts = ref.match(/^((?:'(?:[^']|'')+'|[A-Za-z_\u0080-\uffff][A-Za-z0-9_.\u0080-\uffff]*)\s*)?(\[(?:[^\]\r\n]|\]\])+\])$/);
          var pre = parts && parts[1] ? parts[1].trim() : '';
          var inner = parts ? parts[2].slice(1, -1).replace(/\]\]/g, ']').trim() : '';
          var canonical = names[inner.toLowerCase()];
          var table = pre[0] === "'" ? pre.slice(1, -1).replace(/''/g, "'") : pre;
          if (canonical && (!pre || H[canonical].toLowerCase() === table.toLowerCase())) out.push({ msr: canonical, raw: ref });
          else out.push({ col: ref });
        }
        last = m.index + m[0].length;
      }
      if (last < dax.length) pushTxt(dax.slice(last));
      return out;
    }; })(typeof window !== 'undefined' ? window : globalThis);
