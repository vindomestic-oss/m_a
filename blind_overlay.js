/* Blind-test overlay. Injected by blind_test.py after window.BLIND = {...}; into a page produced by
   reader/app.py render_score(). Uses window.__motifApi (motifs, filteredByInv, drawBoxes, ...).
   BLIND = {pieceIdx, nPieces, items:[{id, query, variant, label}]} */
(function () {
  var B = window.BLIND, api = window.__motifApi;
  if (!B || !api) { return; }
  var dict = document.getElementById('motif-dict');
  var scoreHost = document.getElementById('score-pages');
  if (dict && dict.parentNode) { dict.parentNode.style.display = 'none'; }

  var t0 = Date.now();
  var ratings = {}, views = {}, tRate = {}, shownCount = {};
  var colored = [];                       // [el, original fill attr]
  var activeId = null;

  function resetColors() {
    colored.forEach(function (p) {
      if (p[1] === null) { p[0].removeAttribute('fill'); } else { p[0].setAttribute('fill', p[1]); }
    });
    colored = [];
  }
  function colorOccs(occs, color) {
    occs.forEach(function (occ) {
      occ.forEach(function (id) {
        var el = document.getElementById(id);
        if (!el) { return; }
        colored.push([el, el.getAttribute('fill')]);
        el.setAttribute('fill', color);
      });
    });
  }
  function el(tag, css, html) {
    var e = document.createElement(tag);
    if (css) { e.style.cssText = css; }
    if (html !== undefined) { e.innerHTML = html; }
    return e;
  }
  function scrollToOcc(occ) {
    if (!occ || !occ[0]) { return; }
    var n = document.getElementById(occ[0]);
    if (n) { n.scrollIntoView({behavior: 'smooth', block: 'center'}); }
  }

  var panel = el('div', 'font:13px sans-serif;color:#222;margin:0 0 14px;padding:10px 14px;' +
    'background:#fafafa;border:1px solid #ddd;border-radius:5px');
  panel.appendChild(el('div', 'font-weight:bold;font-size:14px;margin-bottom:4px',
    'Piece ' + (B.pieceIdx + 1) + ' of ' + B.nPieces));
  panel.appendChild(el('div', 'font-size:12px;color:#555;margin-bottom:8px', B.binary ?
    'Tick every motif that you consider <b>relevant</b> for this piece (any number, from none to all). ' +
    'Click a row to see its first and last occurrence in the score.' :
    'Rate how relevant each motif is for this piece: <b>0</b> = not relevant, <b>4</b> = surely relevant. ' +
    'Click a row to see its first and last occurrence in the score (the label shows which variant is meant).'));
  var tbl = el('table', 'border-collapse:collapse;width:100%');
  panel.id = 'blind-panel';
  panel.appendChild(tbl);

  var rows = {};
  B.items.forEach(function (it, k) {
    var idx = -1;
    api.motifs.forEach(function (m, i) { if (idx < 0 && m.queryStr === it.query) { idx = i; } });
    it._idx = idx;
    var tr = el('tr', 'border-bottom:1px solid #e6e6e6;cursor:pointer');
    var color = idx >= 0 ? api.motifs[idx].color : '#999';
    tr.appendChild(el('td', 'padding:6px 10px 6px 0;white-space:nowrap;font-weight:bold',
      '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:' + color +
      ';margin-right:6px"></span>' + String.fromCharCode(65 + k)));
    var svgCell = '';
    if (idx >= 0 && dict) {
      var src = dict.querySelector('tr[data-midx="' + idx + '"] td:nth-child(2)');
      if (src) { svgCell = src.innerHTML; }
    }
    tr.appendChild(el('td', 'padding:2px 14px 2px 0;zoom:' + (B.items.length > 8 ? '1.5' : '2.2'), idx >= 0 ? svgCell : '<i style="color:#c00">motif not found</i>'));
    tr.appendChild(el('td', 'padding:6px 14px 6px 0;font-size:12px;color:#444;white-space:nowrap',
      '<span style="background:#eef;border-radius:3px;padding:2px 6px">' + it.label + '</span>'));
    var nav = el('td', 'padding:6px 14px 6px 0;font-size:11px;white-space:nowrap');
    var aF = el('a', 'color:#1a5fb4;cursor:pointer;margin-right:8px', '&#9664; first');
    var aL = el('a', 'color:#1a5fb4;cursor:pointer', 'last &#9654;');
    nav.appendChild(aF); nav.appendChild(aL); tr.appendChild(nav);
    var rate = el('td', 'padding:6px 0;white-space:nowrap;text-align:right');
    if (B.binary) {
      var lab1 = el('label', 'cursor:pointer;font-size:14px');
      var cb = document.createElement('input');
      cb.type = 'checkbox'; cb.style.cssText = 'cursor:pointer;margin-right:6px;transform:scale(1.4)';
      cb.addEventListener('change', function () {
        ratings[it.id] = cb.checked ? 1 : 0; tRate[it.id] = Date.now() - t0; refresh();
      });
      lab1.appendChild(cb); lab1.appendChild(document.createTextNode('relevant'));
      lab1.addEventListener('click', function (e) { e.stopPropagation(); });
      rate.appendChild(lab1);
    }
    for (var v = 0; v <= 4 && !B.binary; v++) {
      (function (v) {
        var lab = el('label', 'margin-left:10px;cursor:pointer;font-size:14px');
        var inp = document.createElement('input');
        inp.type = 'radio'; inp.name = 'r_' + it.id; inp.value = v;
        inp.style.cssText = 'cursor:pointer;margin-right:2px';
        inp.addEventListener('change', function () {
          ratings[it.id] = v; tRate[it.id] = Date.now() - t0; refresh();
        });
        lab.appendChild(inp); lab.appendChild(document.createTextNode(String(v)));
        lab.addEventListener('click', function (e) { e.stopPropagation(); });
        rate.appendChild(lab);
      })(v);
    }
    tr.appendChild(rate);
    tbl.appendChild(tr);
    rows[it.id] = tr;

    function occsOf() {
      if (idx < 0) { return []; }
      var fr = api.filteredByInv(api.motifs[idx], it.variant);
      shownCount[it.id] = fr.occs.length;
      return fr.occs;
    }
    function show(focus) {
      var occs = occsOf();
      if (!occs.length) { return; }
      var sel = occs.length > 1 ? [occs[0], occs[occs.length - 1]] : [occs[0]];
      api.clearRects(); resetColors();
      Object.keys(rows).forEach(function (k2) { rows[k2].style.background = ''; });
      tr.style.background = '#e8f0fe'; activeId = it.id;
      colorOccs(sel, color);
      api.drawBoxes({occs: sel, color: color, repeat_pairs: [], is_volta: false, noNumbers: true});
      views[it.id] = (views[it.id] || 0) + 1;
      scrollToOcc(focus === 'last' ? sel[sel.length - 1] : sel[0]);
    }
    occsOf();                                   // record the actual count shown for this variant
    tr.addEventListener('click', function () { show('first'); });
    aF.addEventListener('click', function (e) { e.stopPropagation(); show('first'); });
    aL.addEventListener('click', function (e) { e.stopPropagation(); show('last'); });
  });

  if (scoreHost && scoreHost.parentNode) { scoreHost.parentNode.insertBefore(panel, scoreHost); }
  else { document.body.insertBefore(panel, document.body.firstChild); }

  // bottom bar
  document.body.style.paddingBottom = '70px';
  var bar = el('div', 'position:fixed;left:0;right:0;bottom:0;height:52px;background:#fff;' +
    'border-top:2px solid #ccc;display:flex;align-items:center;justify-content:space-between;' +
    'padding:0 24px;z-index:9000;font:14px sans-serif');
  var status = el('span', 'color:#555');
  var btn = el('button', 'font:bold 14px sans-serif;padding:8px 22px;border:1px solid #1a5fb4;' +
    'border-radius:5px;background:#1a5fb4;color:#fff;cursor:pointer');
  btn.textContent = (B.pieceIdx + 1 >= B.nPieces) ? 'Finish' : 'Next piece ▶';
  bar.appendChild(status); bar.appendChild(btn); document.body.appendChild(bar);

  function needed() { return B.items.filter(function (it) { return it._idx >= 0; }); }
  function refresh() {
    var n = needed(), done = n.filter(function (it) { return ratings[it.id] !== undefined; }).length;
    if (B.binary) {
      var yes = n.filter(function (it) { return ratings[it.id] === 1; }).length;
      status.textContent = 'Marked relevant: ' + yes + ' of ' + n.length;
      btn.disabled = false; btn.style.opacity = '1'; btn.style.cursor = 'pointer';
      return;
    }
    status.textContent = 'Rated ' + done + ' of ' + n.length;
    var ok = (done === n.length);
    btn.disabled = !ok; btn.style.opacity = ok ? '1' : '0.4'; btn.style.cursor = ok ? 'pointer' : 'not-allowed';
  }
  refresh();

  btn.addEventListener('click', function () {
    btn.disabled = true; btn.textContent = 'Saving…';
    var payload = {
      piece_idx: B.pieceIdx, elapsed_ms: Date.now() - t0,
      items: B.items.map(function (it) {
        return {id: it.id, rating: ratings[it.id] === undefined ? (B.binary ? 0 : null) : ratings[it.id],
                missing: it._idx < 0, shown_count: shownCount[it.id] === undefined ? null : shownCount[it.id],
                views: views[it.id] || 0, t_rate_ms: tRate[it.id] === undefined ? null : tRate[it.id]};
      })
    };
    fetch('/blind/submit', {method: 'POST', headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(payload)})
      .then(function (r) { return r.text(); })
      .then(function () { /* server pushes the next page through SSE; fallback: */
        setTimeout(function () { window.location.replace('/?t=' + Date.now()); }, 1500); })
      .catch(function () { btn.disabled = false; btn.textContent = 'Retry'; });
  });
})();
