'use strict';
let view, token, current = 0;
const $ = s => document.querySelector(s);
const status = $('#status');
const DECISIONS = [['accept', 'Accept'], ['shortlist', 'Shortlist'], ['maybe', 'Maybe'], ['reject', 'Reject']];
const LABEL = Object.fromEntries(DECISIONS);
const AUTOSAVE_NOTE_MS = 1200;

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function dl(pairs) {
  const d = el('dl');
  for (const [k, v] of pairs) {
    if (v === undefined || v === null || v === '') continue;
    d.append(el('dt', k));
    const dd = el('dd');
    if (v instanceof Node) dd.append(v); else dd.textContent = String(v);
    d.append(dd);
  }
  return d;
}
const num = (x, n = 3) => (typeof x === 'number' ? x.toFixed(n) : '—');
const code = t => el('code', t, 'hash');
function link(url, text) {
  const a = el('a', text || url); a.href = url; a.rel = 'noopener noreferrer'; a.target = '_blank'; return a;
}
const clock = iso => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(); };

const isDecided = e => !!(e.decision && e.decision.current);
function counts(p) {
  return {done: p.queue.filter(isDecided).length, total: p.queue.length,
          otherDone: p.not_in_queue.filter(isDecided).length, others: p.not_in_queue.length};
}
const optionText = p => { const c = counts(p); return `${p.role_id} · ${c.done}/${c.total} decided`; };

function refreshProgress() {
  const p = view.packages[current];
  if (!p) return;
  const c = counts(p), badge = $('#progress');
  badge.textContent = `Queue ${c.done}/${c.total} decided` + (c.others ? ` · others ${c.otherDone}/${c.others}` : '');
  badge.classList.toggle('complete', c.total > 0 && c.done === c.total);
  [...$('#package').options].forEach((o, i) => { o.textContent = optionText(view.packages[i]); });
}

async function load() {
  const response = await fetch('/api/state');
  if (!response.ok) throw new Error(await response.text());
  view = await response.json();
  token = view.save_token;
  const picker = $('#package');
  picker.replaceChildren(...view.packages.map((p, i) => { const o = el('option', optionText(p)); o.value = String(i); return o; }));
  current = Math.min(current, Math.max(0, view.packages.length - 1));
  picker.value = String(current);
  render();
}

function render() {
  document.querySelectorAll('audio').forEach(a => a.pause());
  const p = view.packages[current];
  const warnings = $('#warnings');
  warnings.replaceChildren();
  if (!p) {
    $('#request').textContent = 'No ranking package loaded. Start the server with --ranking <Issue #7 result JSON>.';
    $('#queue').replaceChildren(); return;
  }
  const rc = p.ranking_config, contract = p.retrieval_contract, div = p.diversity_implementation;
  $('#request').replaceChildren('Request: ', el('b', `“${p.query}”`), ` · role ${p.role_id}`);
  $('#summary').replaceChildren(dl([
    ['Request', p.query], ['Role profile', p.role_id],
    ['Ranking config', `${rc.config_id} ${rc.version} · fingerprint ${rc.fingerprint.slice(0, 16)}…`],
    ['Diversity', div ? `${div.library} ${div.version} (${div.license}) ${div.strategy}, diversity ${div.diversity}` : 'disabled'],
    ['Model', `${contract.model} @ ${contract.revision}`], ['Preprocessing', contract.preprocessing],
    ['Index state', code(p.index_state)], ['Eligibility policy', p.eligibility_policy_version],
    ['Ranking package', code(p.package_id)], ['Loaded', p.added_at]]));
  if (!p.contract_matches_current) warnings.append(el('p', 'This ranking used a different model/preprocessing contract than the one currently pinned. It is shown as a historical record.'));
  if (p.config_matches_current === false) warnings.append(el('p', 'The current ranking configuration differs from the one that produced this package. Decisions stay bound to this historical package.'));
  const blocked = [...p.queue, ...p.not_in_queue].filter(e => !e.verification.playable).length;
  if (blocked) warnings.append(el('p', `${blocked} candidate(s) cannot be played now; see the highlighted rows.`));
  $('#queue').replaceChildren(...p.queue.map(e => row(p, e)));
  $('#beyond ol').replaceChildren(...p.not_in_queue.map(e => row(p, e)));
  $('#beyond-count').textContent = String(p.not_in_queue.length);
  $('#beyond').hidden = p.not_in_queue.length === 0;
  $('#removed ul').replaceChildren(
    ...p.suppressed.map(s => el('li', `${s.candidate_id} (${s.sha256.slice(0, 12)}…): ${s.reasons.join('; ')}`)),
    ...p.excluded.map(x => el('li', `${x.candidate_id}: ${x.stage} ${x.status} — ${x.reasons.join('; ')}`)));
  $('#removed').hidden = !p.suppressed.length && !p.excluded.length;
  refreshProgress();
}

// One compact row per candidate: who, listen, decide, note. Everything else is behind "Details".
function row(p, e) {
  const v = e.verification, rec = e.recorded && e.recorded.candidate;
  const li = el('li', null, 'row');
  const who = el('div', null, 'who');
  const names = el('div');
  names.append(el('strong', e.candidate_id, 'name'));
  const title = rec && rec.acquisition_source && rec.acquisition_source.includes(' | ') ? rec.acquisition_source.split(' | ')[0] : null;
  const sub = [title, e.provider, e.representation === 'original' ? null : 'PREVIEW bytes'].filter(Boolean).join(' · ');
  if (sub) names.append(el('span', sub, 'sub'));
  who.append(el('span', String(e.rank), 'rank'), names);
  li.append(who, player(p, e), ...decisionControls(p, e, li));
  v.issues.forEach(text => li.append(el('p', text, 'issue')));
  const more = el('details', null, 'more');
  more.append(el('summary', 'Details'));
  more.addEventListener('toggle', () => {
    if (more.open && !more.dataset.built) { more.dataset.built = '1'; more.append(detail(p, e)); }
  });
  li.append(more);
  return li;
}

function detail(p, e) {
  const v = e.verification, rec = e.recorded && e.recorded.candidate, rights = rec && rec.rights;
  const wrap = el('div');
  const grid = el('div', null, 'grid');
  const blob = rec && (e.representation === 'original' ? rec.original : rec.preview);
  grid.append(dl([
    ['Exact SHA-256', code(e.sha256)], ['File (as recorded)', blob && blob.filename],
    ['Media', blob && `${blob.media_type}, ${blob.size} bytes`], ['Author', e.author], ['Provider', e.provider],
    ['Source asset', rec && link(rec.asset_url)], ['Acquired from', rec && rec.acquisition_source],
    ['Lineage', rec && (rec.kind === 'derivative' ? `derivative of ${rec.parent_id}: ${rec.transformation}` : 'original')]]));
  grid.append(dl([
    ['License', rights ? rights.license_name : 'no license evidence recorded'],
    ['Commercial / modify / embed', rights && `${rights.commercial} / ${rights.modification} / ${rights.game_embedding}`],
    ['Redistribution', rights && rights.redistribution],
    ['Attribution', rights && (rights.attribution + (rights.attribution_text ? `: ${rights.attribution_text}` : ''))],
    ['Evidence', evidenceList(e.recorded)],
    ['Eligibility at ranking', `${e.eligibility.status} (${e.eligibility.policy_version})`],
    ['Eligibility now', v.eligibility ? v.eligibility.status : 'unknown'],
    ['Identity / bytes now', `${v.identity} / ${v.file}`]]));
  const dsp = e.signals.dsp;
  grid.append(dl([
    ['Duration', `${num(dsp.duration_seconds, 2)} s`], ['Sample rate / channels', `${dsp.sample_rate} Hz / ${dsp.channels}`],
    ['Peak / RMS', `${num(dsp.peak_dbfs, 1)} / ${num(dsp.rms_dbfs, 1)} dBFS`],
    ['Semantic (request cosine)', `${num(e.signals.query_cosine)} · best segment ${num(e.signals.best_segment[0], 0)}–${num(e.signals.best_segment[1], 0)} s`],
    ['Pre-diversity score', `${num(e.pre_diversity_score)} (rank ${e.pre_diversity_rank})`],
    ['Reranking', rerankText(e.reranking)],
    ['Ranking config', `${p.ranking_config.config_id} ${p.ranking_config.version}`]]));
  wrap.append(grid, contributions(e));
  return wrap;
}

function evidenceList(recorded) {
  if (!recorded || !recorded.evidence) return null;
  const ul = el('ul');
  recorded.evidence.forEach(x => { const item = el('li'); item.append(link(x.url, x.id), ` checked ${x.checked}, snapshot ${x.snapshot.sha256.slice(0, 12)}…`); ul.append(item); });
  return ul;
}
function rerankText(r) {
  const parts = [r.decision];
  if (r.mmr) parts.push(`MMR step ${r.mmr.step}, gain ${num(r.mmr.marginal_gain)}` +
    (r.mmr.most_similar_prior ? `, most similar earlier: ${r.mmr.most_similar_prior} (${num(r.mmr.max_similarity_to_prior)})` : ''));
  if (r.reasons.length) parts.push(r.reasons.join('; '));
  return parts.join(' · ');
}
function contributions(e) {
  const t = el('table'); t.append(el('caption', 'Score contributions'));
  const head = el('tr'); head.append(el('th', 'Term'), el('th', 'Value')); t.append(head);
  Object.entries(e.contributions).forEach(([k, x]) => { const r = el('tr'); r.append(el('td', k), el('td', num(x, 4))); t.append(r); });
  return t;
}

function player(p, e) {
  const box = el('div', null, 'listen');
  if (!e.verification.playable) { box.append(el('p', 'Playback disabled: these exact bytes cannot be verified as present and eligible. No substitute file is played.', 'issue')); return box; }
  // preload=none: only the player being auditioned holds a media pipeline (Chrome limits active players).
  const a = el('audio'); a.controls = true; a.preload = 'none';
  a.src = `/api/audio/${p.package_id}/${encodeURIComponent(e.candidate_id)}`;
  a.setAttribute('aria-label', `Listen to rank ${e.rank}, ${e.candidate_id}`);
  a.addEventListener('play', () => document.querySelectorAll('audio').forEach(o => { if (o !== a) o.pause(); }));
  box.append(a);
  const d = e.signals.dsp.duration_seconds;
  if (d > 20) {
    const buttons = el('div', null, 'excerpts');
    let stopAt = null, excerptSeek = false;
    a.addEventListener('timeupdate', () => { if (stopAt !== null && a.currentTime >= stopAt) { a.pause(); stopAt = null; } });
    // A seek not started by an excerpt button (e.g. the native scrubber) ends the excerpt window.
    a.addEventListener('seeking', () => { if (!excerptSeek) stopAt = null; excerptSeek = false; });
    [[0, 'Start'], [Math.max(0, d / 2 - 5), 'Middle'], [Math.max(0, d - 10), 'End']].forEach(([at, word]) => {
      const b = el('button', `${word} · 10 s`); b.type = 'button';
      b.onclick = () => { excerptSeek = true; a.currentTime = at; stopAt = Math.min(at + 10, d); a.play().catch(err => { status.textContent = err.message; }); };
      buttons.append(b);
    });
    box.append(buttons);
  }
  return box;
}

// Choosing a decision saves immediately; a note saves after a pause or when it loses focus.
// The row always says whether what is on screen is what the server has stored.
function decisionControls(p, e, li) {
  const v = e.verification;
  const name = `decision-${p.package_id.slice(0, 8)}-${e.candidate_id}`;
  const fs = el('fieldset', null, 'choice'); fs.append(el('legend', 'Your decision', 'sr'));
  DECISIONS.forEach(([value, text]) => {
    const label = el('label', null, 'seg seg-' + value); const input = el('input');
    input.type = 'radio'; input.name = name; input.value = value;
    input.checked = !!(e.decision && e.decision.current === value);
    input.disabled = !v.playable && value !== 'reject';
    input.addEventListener('change', () => save());
    label.append(input, el('span', text)); fs.append(label);
  });
  const clear = el('button', 'Clear', 'link'); clear.type = 'button';
  clear.setAttribute('aria-label', `Clear decision for ${e.candidate_id}`);
  const retry = el('button', 'Retry'); retry.type = 'button';
  const state = el('p', null, 'state');
  const choiceCol = el('div', null, 'choice-col'); choiceCol.append(fs, state);

  const note = el('textarea'); note.rows = 1; note.placeholder = 'Note (optional)';
  note.value = (e.decision && e.decision.note) || ''; note.setAttribute('aria-label', `Note for ${e.candidate_id}`);
  const noteCol = el('div', null, 'note-col'); noteCol.append(note);

  const chosen = () => { const c = fs.querySelector('input:checked'); return c ? c.value : null; };
  const storedNote = () => (e.decision && e.decision.note) || '';
  let timer = null, failed = null, inflight = 0, chain = Promise.resolve();

  function paint(text, kind, withRetry) {
    state.className = 'state ' + kind;
    state.replaceChildren(text);
    if (withRetry) state.append(retry);
  }
  function show() {
    const d = e.decision, stored = d && d.current ? d.current : null;
    li.dataset.state = !v.playable && !stored ? 'blocked' : (stored || 'none');
    clear.hidden = !chosen();
    if (!clear.parentNode) fs.append(clear);
    if (failed) { paint(`Not saved — ${failed}`, 'error', true); return; }
    if (inflight) { paint('Saving…', 'busy'); return; }
    if (chosen() !== stored || note.value !== storedNote()) {
      paint(chosen() ? 'Unsaved changes…' : 'Pick a decision to save this note', 'warn'); return;
    }
    if (stored) paint(`✓ Saved: ${LABEL[stored]} · ${clock(d.decided_at)}`, 'saved');
    else paint(d ? `Cleared · ${clock(d.decided_at)}` : 'Not decided yet', 'none');
  }
  async function send(decision, text) {
    try {
      const response = await fetch('/api/decision', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Audition-Token': token},
        body: JSON.stringify({package_id: p.package_id, candidate_id: e.candidate_id, representation: e.representation, sha256: e.sha256, decision, note: text})});
      if (!response.ok) throw new Error(await response.text());
      e.decision = (await response.json()).saved; failed = null;
      status.textContent = `Saved ${e.candidate_id}: ${decision ? LABEL[decision] : 'cleared'}.`;
    } catch (err) {
      failed = err.message; status.textContent = `Not saved (${e.candidate_id}): ${err.message}`;
    }
  }
  // Saves are serialized per row so the server's append-only history keeps the order the user acted in;
  // each one sends what is on screen when it runs.
  function save() {
    clearTimeout(timer);
    failed = null;
    const stored = () => (e.decision && e.decision.current) || null;
    if (chosen() === null && !stored()) { show(); return chain; }   // a note alone is held until a decision exists
    inflight += 1; show();
    chain = chain
      .then(() => (chosen() === stored() && note.value === storedNote() ? null : send(chosen(), note.value)))
      .then(() => { inflight -= 1; show(); refreshProgress(); });
    return chain;
  }
  note.addEventListener('input', () => {
    show();
    clearTimeout(timer);
    if (chosen() !== null) timer = setTimeout(save, AUTOSAVE_NOTE_MS);
  });
  note.addEventListener('blur', () => { if (chosen() !== null && note.value !== storedNote()) save(); });
  clear.onclick = () => { fs.querySelectorAll('input').forEach(i => { i.checked = false; }); save(); };
  retry.onclick = () => { failed = null; save(); };
  show();
  return [choiceCol, noteCol];
}

function nextUndecided() {
  const target = document.querySelector('#queue .row[data-state=none], #queue .row[data-state=blocked]');
  if (!target) { status.textContent = 'Every candidate in this queue has a decision.'; return; }
  target.scrollIntoView({block: 'center', behavior: 'smooth'});
  target.classList.add('flash'); setTimeout(() => target.classList.remove('flash'), 1500);
  const audio = target.querySelector('audio, input:not(:disabled)'); if (audio) audio.focus({preventScroll: true});
}

$('#package').onchange = ev => { current = Number(ev.target.value); render(); };
$('#next').onclick = nextUndecided;
$('#export').onclick = async () => {
  try {
    const response = await fetch('/api/export', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Audition-Token': token}, body: '{}'});
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    const url = URL.createObjectURL(new Blob([JSON.stringify(result.export, null, 1)], {type: 'application/json'}));
    const a = el('a'); a.href = url; a.download = result.saved_as; a.click(); URL.revokeObjectURL(url);
    const flagged = result.export.integrity.flagged.length;
    status.textContent = `Exported ${result.export.selections.length} decision(s) as ${result.saved_as}.` +
      (flagged ? ` WARNING: ${flagged} flagged — current bytes/evidence/eligibility no longer match.` : ' All exported identities verified.');
  } catch (err) { status.textContent = `Export failed: ${err.message}`; }
};
load().then(() => { status.textContent = 'Ready. Decisions save automatically and survive restart.'; })
  .catch(err => { status.textContent = err.message; });
