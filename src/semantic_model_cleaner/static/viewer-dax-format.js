/* DAX formatter and inliner. Pure functions, no DOM, no network.
   Layout follows the SQLBI DAX Formatter rules (https://docs.sqlbi.com/dax-style/dax-format):
   upper-case function names, 4-space indent, closing parenthesis under the function name,
   VAR / RETURN on their own lines, an operator starts the continuation line.
   'short' puts every argument of a multi-argument call on its own line.
   'long' keeps a call on one line while it fits in LONG_LIMIT characters.

   Pipeline: tokenize -> parse into a tree -> (optionally) replace measure references with the
   parsed body of that measure -> print to lines. Every line records the fold regions that open
   on it, so a view can collapse a region without re-parsing. */
(function (g) {
  'use strict';

  var LONG_LIMIT = 80, MAX_INDENT = 6, INDENT = '    ', CAP = 200000;
  var KEYWORDS = { VAR: 1, RETURN: 1, DEFINE: 1, MEASURE: 1, EVALUATE: 1, IN: 1, NOT: 1, TRUE: 1, FALSE: 1 };
  /* Words that look like calls but are written upper-case only when they are DAX functions we know.
     Anything else with a following "(" is also treated as a function (user-defined functions). */

  /* ---------- tokenizer ---------- */
  function tokenize(src) {
    var out = [], i = 0, n = src.length, guard = 0, m;
    var refRe = /^(?:(?:'(?:[^']|'')+'|[A-Za-z_\u0080-￿][A-Za-z0-9_.\u0080-￿]*)\s*)?\[(?:[^\]\r\n]|\]\])+\]/;
    var numRe = /^(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)/;
    var wordRe = /^[A-Za-z_\u0080-￿][A-Za-z0-9_.\u0080-￿]*/;
    var opRe = /^(?:<=|>=|<>|==|&&|\|\||\+|-|\*|\/|\^|&|=|<|>|!)/;
    while (i < n) {
      if (++guard > 400000) throw new Error('LOOP-GUARD: tokenize');
      var c = src.charAt(i), rest = src.slice(i);
      if (/\s/.test(c)) { i++; continue; }
      if (c === '/' && src.charAt(i + 1) === '/' || c === '-' && src.charAt(i + 1) === '-') {
        var e = src.indexOf('\n', i); if (e < 0) e = n;
        out.push({ t: 'cmt', v: src.slice(i, e).replace(/\s+$/, ''), line: true }); i = e; continue;
      }
      if (c === '/' && src.charAt(i + 1) === '*') {
        var e2 = src.indexOf('*/', i + 2); e2 = e2 < 0 ? n : e2 + 2;
        out.push({ t: 'cmt', v: src.slice(i, e2) }); i = e2; continue;
      }
      if (c === '"') {
        var j = i + 1;
        while (j < n) { if (src.charAt(j) === '"') { if (src.charAt(j + 1) === '"') { j += 2; continue; } break; } j++; }
        out.push({ t: 'str', v: src.slice(i, Math.min(j + 1, n)) }); i = j + 1; continue;
      }
      if ((m = refRe.exec(rest))) { out.push({ t: 'ref', v: m[0] }); i += m[0].length; continue; }
      if (c === "'") {
        var k = i + 1;
        while (k < n) { if (src.charAt(k) === "'") { if (src.charAt(k + 1) === "'") { k += 2; continue; } break; } k++; }
        out.push({ t: 'word', v: src.slice(i, Math.min(k + 1, n)) }); i = k + 1; continue;
      }
      if ((m = numRe.exec(rest))) { out.push({ t: 'num', v: m[0] }); i += m[0].length; continue; }
      if ((m = wordRe.exec(rest))) { out.push({ t: 'word', v: m[0] }); i += m[0].length; continue; }
      if (c === '(' || c === ')' || c === '{' || c === '}') { out.push({ t: c, v: c }); i++; continue; }
      if (c === ',' || c === ';') { out.push({ t: ',', v: c }); i++; continue; }
      if ((m = opRe.exec(rest))) { out.push({ t: 'op', v: m[0] }); i += m[0].length; continue; }
      out.push({ t: 'other', v: c }); i++;
    }
    return out;
  }

  /* ---------- parser ----------
     A node is one of:
       { k:'atom', t:'ref'|'str'|'num'|'word'|'kw'|'cmt'|'op', v }
       { k:'call', name, args:[seq], open:'(' }      function call; each arg is a sequence
       { k:'group', open:'(', seq }                   plain parenthesis
       { k:'brace', args:[seq] }                      table constructor { ... }
       { k:'inline', name, node }                     measure body spliced in by inlineTree
     A sequence is an array of nodes. */
  function parse(tokens) {
    var pos = 0, guard = 0;
    function seqUntil(close) {
      var seq = [];
      while (pos < tokens.length) {
        if (++guard > 400000) throw new Error('LOOP-GUARD: parse');
        var tk = tokens[pos];
        if (tk.t === close || tk.t === ')' || tk.t === '}') { if (tk.t === close) return seq; pos++; continue; }
        if (tk.t === ',') { return seq; }
        seq.push(node());
      }
      return seq;
    }
    function args(close) {
      var list = [];
      for (;;) {
        list.push(seqUntil(close));
        if (pos < tokens.length && tokens[pos].t === ',') { pos++; continue; }
        break;
      }
      if (pos < tokens.length && tokens[pos].t === close) pos++;
      if (list.length === 1 && !list[0].length) return [];
      return list;
    }
    function node() {
      var tk = tokens[pos++];
      if (tk.t === 'word') {
        if (pos < tokens.length && tokens[pos].t === '(' && !/^'/.test(tk.v)) {
          pos++;
          return { k: 'call', name: tk.v, args: args(')') };
        }
        if (KEYWORDS[tk.v.toUpperCase()]) return { k: 'atom', t: 'kw', v: tk.v.toUpperCase() };
        return { k: 'atom', t: 'word', v: tk.v };
      }
      if (tk.t === '(') return { k: 'group', seq: joinCommas(args(')')) };
      if (tk.t === '{') return { k: 'brace', args: args('}') };
      return { k: 'atom', t: tk.t, v: tk.v, line: tk.line };
    }
    /* A parenthesis that holds a comma list (tuple) keeps the list as arguments. */
    function joinCommas(list) { return list; }
    var top = [];
    while (pos < tokens.length) {
      if (++guard > 400000) throw new Error('LOOP-GUARD: parse top');
      if (tokens[pos].t === ',' || tokens[pos].t === ')' || tokens[pos].t === '}') { pos++; continue; }
      top.push(node());
    }
    return top;
  }

  /* ---------- inlining ----------
     resolve(name) -> { name, dax } for a measure reference, or null. Returns the tree plus the
     bookkeeping the view needs to explain what happened. */
  function inlineTree(seq, resolve, state, stack) {
    var out = [];
    seq.forEach(function (n) {
      if (n.k === 'atom' && n.t === 'ref') {
        var r = resolve(n.v);
        if (!r || !String(r.dax || '').trim()) { out.push(n); return; }
        if (stack.indexOf(r.name) >= 0) { state.cycles[r.name] = true; out.push(n); return; }
        if (state.size > CAP) { state.capped = true; out.push(n); return; }
        state.count[r.name] = true;
        var body = String(r.dax).trim();
        state.size += body.length;
        var inner = inlineTree(parse(tokenize(body)), resolve, state, stack.concat(r.name));
        out.push({ k: 'inline', name: r.name, raw: n.v, seq: inner });
      } else if (n.k === 'call') {
        out.push({ k: 'call', name: n.name, args: n.args.map(function (a) { return inlineTree(a, resolve, state, stack); }) });
      } else if (n.k === 'group') {
        out.push({ k: 'group', seq: n.seq.map(function (a) { return inlineTree(a, resolve, state, stack); }) });
      } else if (n.k === 'brace') {
        out.push({ k: 'brace', args: n.args.map(function (a) { return inlineTree(a, resolve, state, stack); }) });
      } else out.push(n);
    });
    return out;
  }

  /* ---------- printer ----------
     The printer builds a list of lines. A line is { indent, parts:[segment] }.
     A segment is { v, k } where k is fn | kw | str | ref | num | cmt | op | txt | inl.
     An 'inl' segment is the chip that names an inlined measure; it and the space after it are
     marked ghost, so they show on screen but are left out of the copied text.
     Fold regions: { id, kind:'measure'|'block', name, from, to, openPart, closePart }.
     `from` / `to` are line indexes; openPart / closePart index the "(" and ")" segments. */
  function print(top, opts) {
    var style = opts && opts.style === 'short' ? 'short' : 'long';
    var lines = [], regions = [], cur = null, mdepth = 0;

    function newLine(indent) { cur = { indent: indent, parts: [] }; lines.push(cur); return cur; }
    function startLine(indent) { if (cur && !cur.parts.length) { cur.indent = indent; return cur; } return newLine(indent); }
    function put(v, k, ghost) {
      if (!cur) newLine(0);
      if (k === 'cmt' && v.indexOf('\n') >= 0) {            // a block comment spanning lines: one printed line per source line
        var rows = v.split(/\r?\n/), first = true, at = -1;
        rows.forEach(function (row) {
          if (!first) newLine(cur.indent);
          at = put(first ? row : row.replace(/^\s+/, ''), 'cmt'); first = false;
        });
        return at;
      }
      var seg = { v: v, k: k }; if (ghost) seg.ghost = true;
      cur.parts.push(seg); return cur.parts.length - 1;
    }
    /* Deeply nested code (inlined measures stack up fast) would leave no room for anything, so only the
       first MAX_INDENT levels count against the line limit. */
    function lw() { return cur ? Math.min(cur.indent, MAX_INDENT) * INDENT.length + cur.parts.reduce(function (w, p) { return w + p.v.length; }, 0) : 0; }
    function atomKind(n) { return { kw: 'kw', str: 'str', ref: 'ref', num: 'num', cmt: 'cmt', op: 'op' }[n.t] || 'txt'; }
    function fnName(name) { return /^[A-Za-z_][A-Za-z0-9_.]*$/.test(name) ? name.toUpperCase() : name; }
    function isKw(n, v) { return n.k === 'atom' && n.t === 'kw' && n.v === v; }
    function isOp(n) { return n.k === 'atom' && n.t === 'op' && !n.unary; }

    /* A unary sign has no operand before it; mark it so it hugs the next token. */
    function markUnary(seq) {
      seq.forEach(function (n, i) {
        if (n.k === 'atom' && n.t === 'op' && (n.v === '-' || n.v === '+' || n.v === '!')) {
          var p = seq[i - 1];
          if (!p || (p.k === 'atom' && (p.t === 'op' || p.t === 'kw'))) n.unary = true;
        }
        if (n.k === 'call' || n.k === 'brace') n.args.forEach(markUnary);
        else if (n.k === 'group') n.seq.forEach(markUnary);
        else if (n.k === 'inline') markUnary(n.seq);
      });
    }

    /* ----- single-line form: an array of segments, or null when the node cannot be one line ----- */
    function flat(n) {
      if (n.k === 'atom') return n.t === 'cmt' && (n.line || n.v.indexOf('\n') >= 0) ? null : [{ v: n.v, k: atomKind(n) }];
      if (n.k === 'inline') return null;
      var open = n.k === 'call' ? fnName(n.name) + ' (' : n.k === 'group' ? '(' : '{';
      var close = n.k === 'brace' ? '}' : ')';
      var list = n.k === 'group' ? n.seq : n.args;
      var parts = [{ v: open, k: n.k === 'call' ? 'fn' : 'txt' }];
      if (!list.length) { parts.push({ v: close, k: 'txt' }); return n.k === 'call' ? [{ v: fnName(n.name), k: 'fn' }, { v: ' ()', k: 'txt' }] : parts; }
      parts.push({ v: ' ', k: 'txt' });
      for (var i = 0; i < list.length; i++) {
        var s = flatSeq(list[i]); if (!s) return null;
        if (i) parts.push({ v: ', ', k: 'txt' });
        parts = parts.concat(s);
      }
      parts.push({ v: ' ' + close, k: 'txt' });
      return parts;
    }
    function flatSeq(seq) {
      var out = [];
      for (var i = 0; i < seq.length; i++) {
        var n = seq[i];
        if (isKw(n, 'VAR') || isKw(n, 'RETURN')) return null;
        var f = flat(n); if (!f) return null;
        if (i && !(seq[i - 1].k === 'atom' && seq[i - 1].unary)) out.push({ v: ' ', k: 'txt' });
        out = out.concat(f);
      }
      return out;
    }
    function width(parts) { return parts.reduce(function (w, p) { return w + p.v.length; }, 0); }
    /* SQLBI short style: a call stays inline only with one argument that holds no call. */
    function shortOk(seq) {
      return seq.every(function (n) {
        if (n.k === 'atom') return true;
        if (n.k === 'call') return n.args.length <= 1 && n.args.every(function (a) { return a.every(function (x) { return x.k === 'atom'; }); });
        if (n.k === 'group') return n.seq.length <= 1 && n.seq.every(shortOk);
        return false;
      });
    }
    function fits(seq, reserve) {
      var f = flatSeq(seq);
      return f && lw() + width(f) + (reserve || 0) <= LONG_LIMIT && (style === 'long' || shortOk(seq)) ? f : null;
    }
    function emit(parts) { parts.forEach(function (p) { put(p.v, p.k); }); }

    function openRegion(kind, name, label) {
      var r = { id: regions.length + 1, kind: kind, name: name, label: label || name, from: lines.length - 1, openLine: lines.length - 1, to: lines.length - 1, openPart: cur.parts.length - 1, closePart: -1 };
      regions.push(r); return r;
    }
    function closeRegion(r) { r.to = lines.length - 1; r.closePart = cur.parts.length - 1; }

    /* ----- sequences ----- */
    function seq(items, indent, reserve) {
      if (items.some(function (n) { return isKw(n, 'VAR') || isKw(n, 'RETURN'); })) return varSeq(items, indent);
      var f = fits(items, reserve); if (f) { emit(f); return; }
      splitSeq(items, indent);
    }
    function varSeq(items, indent) {
      var i = 0;
      while (i < items.length) {
        var n = items[i];
        if (isKw(n, 'VAR')) {
          startLine(indent); put('VAR', 'kw'); put(' ', 'txt');
          if (items[i + 1]) put(items[i + 1].v || '', 'txt');
          var j = i + 2;
          if (items[j] && items[j].k === 'atom' && items[j].v === '=') { put(' =', 'op'); j++; }
          var body = [];
          while (j < items.length && !isKw(items[j], 'VAR') && !isKw(items[j], 'RETURN')) body.push(items[j++]);
          var f = body.length && fits(body, 0);
          if (f) { put(' ', 'txt'); emit(f); }
          else { startLine(indent + 1); seq(body, indent + 1); }
          i = j; continue;
        }
        if (isKw(n, 'RETURN')) {
          startLine(indent); put('RETURN', 'kw');
          var rest = items.slice(i + 1);
          if (rest.length) { startLine(indent + 1); seq(rest, indent + 1); }
          return;
        }
        if (n.k === 'atom' && n.t === 'cmt') { startLine(indent); put(n.v, 'cmt'); i++; continue; }
        startLine(indent); node(n, indent); i++;
      }
    }
    /* Too long for one line: each operand on its own row, the operator first on the next row. */
    function splitSeq(items, indent) {
      var chunks = [[]], ops = [];
      items.forEach(function (n) {
        if (isOp(n) && chunks[chunks.length - 1].length) { ops.push(n); chunks.push([]); }
        else chunks[chunks.length - 1].push(n);
      });
      chunks.forEach(function (chunk, ci) {
        if (ci) { startLine(indent); put(ops[ci - 1].v, 'op'); put(' ', 'txt'); }
        chunk.forEach(function (n, ni) {
          if (n.k === 'atom' && n.t === 'cmt') {
            if (cur && cur.parts.length) put(' ', 'txt');
            put(n.v, 'cmt'); if (n.line) startLine(indent); return;
          }
          if (ni && !(chunk[ni - 1].k === 'atom' && chunk[ni - 1].unary) && !(chunk[ni - 1].k === 'atom' && chunk[ni - 1].t === 'cmt')) put(' ', 'txt');
          node(n, indent);
        });
      });
    }

    /* ----- nodes ----- */
    function node(n, indent) {
      if (n.k === 'atom') { put(n.v, atomKind(n)); return; }
      if (n.k === 'inline') return inlineBlock(n, indent);
      var f = n.k === 'call' ? fits([n], 1) : null;
      if (n.k !== 'call') f = fits([n], 1);
      if (f) { emit(f); return; }
      var list = n.k === 'group' ? n.seq : n.args;
      var close = n.k === 'brace' ? '}' : ')';
      if (n.k === 'call') { put(fnName(n.name), 'fn'); put(' (', 'txt'); } else put(n.k === 'group' ? '(' : '{', 'txt');
      var r = openRegion('block', n.k === 'call' ? fnName(n.name) : close === '}' ? '{' : '(');
      list.forEach(function (a, idx) {
        startLine(indent + 1);
        seq(a, indent + 1, idx < list.length - 1 ? 1 : 0);
        if (idx < list.length - 1) put(',', 'txt');
      });
      startLine(indent); put(close, 'txt'); closeRegion(r);
    }
    function inlineBlock(n, indent) {
      mdepth++;
      /* The label sits on its own line, the "(" on the line below it. The region starts at the label,
         so its fold arrow sits next to the name. */
      cur.parts[put(n.raw, 'inl', true)].depth = mdepth;
      var labelLine = lines.length - 1;
      startLine(indent); put('(', 'txt');
      var r = openRegion('measure', n.name, n.raw); r.depth = mdepth; r.from = labelLine;
      var f = fits(n.seq, 4);
      if (f && n.seq.length) { put(' ', 'txt'); emit(f); put(' )', 'txt'); closeRegion(r); mdepth--; return; }
      startLine(indent + 1); seq(n.seq, indent + 1);
      startLine(indent); put(')', 'txt'); closeRegion(r);
      mdepth--;
    }

    markUnary(top);
    newLine(0);
    seq(top, 0, 0);
    while (lines.length > 1 && !lines[lines.length - 1].parts.length) lines.pop();
    return { lines: lines, regions: regions.filter(function (r) { return r.closePart >= 0; }) };
  }

  /* Plain DAX lines: ghost labels are dropped. A label line that held nothing else disappears,
     and one that followed an operator hands that operator to the "(" line below ("- (" stays together). */
  function plainLines(printed) {
    var out = [], carry = null;
    printed.lines.forEach(function (l) {
      var parts = l.parts.filter(function (p) { return !p.ghost; });
      var labelOnly = l.parts.length && l.parts[l.parts.length - 1].ghost;
      if (carry) { parts = carry.concat(parts); carry = null; }
      if (labelOnly) {
        if (!parts.length) return;
        var last = parts[parts.length - 1];
        carry = /\s$/.test(last.v) ? parts : parts.concat([{ v: ' ', k: 'txt' }]); return;
      }
      out.push({ indent: l.indent, parts: parts });
    });
    return out;
  }

  /* Plain DAX text: all regions expanded, ghost chips left out. */
  function toText(printed) {
    return plainLines(printed).map(function (l) {
      return Array(l.indent + 1).join(INDENT) + l.parts.map(function (p) { return p.v; }).join('');
    }).join('\n').replace(/[ \t]+$/gm, '');
  }

  /* ---------- public API ---------- */
  function format(dax, opts) {
    var tree = parse(tokenize(String(dax || '')));
    return print(tree, opts);
  }
  function formatInlined(dax, name, resolve, opts) {
    var state = { count: {}, cycles: {}, capped: false, size: String(dax || '').length };
    var tree = inlineTree(parse(tokenize(String(dax || ''))), resolve, state, [name]);
    var printed = print(tree, opts);
    printed.count = Object.keys(state.count).length;
    printed.cycles = Object.keys(state.cycles);
    printed.capped = state.capped;
    return printed;
  }

  g.DaxFormat = { tokenize: tokenize, parse: parse, format: format, formatInlined: formatInlined, toText: toText, plainLines: plainLines };
  if (typeof module !== 'undefined' && module.exports) module.exports = g.DaxFormat;
})(typeof window !== 'undefined' ? window : globalThis);
