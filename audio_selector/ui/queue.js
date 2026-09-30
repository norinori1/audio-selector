'use strict';
let view, token, current = 0;
const $ = s => document.querySelector(s);
const status = $('#status');
const DECISIONS = [['accept', 'Accept'], ['shortlist', 'Shortlist'], ['maybe', 'Maybe'], ['reject', 'Reject']];

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

async function load() {
  const response = await fetch('/api/state');
  if (!response.ok) throw new Error(await response.text());
  view = await response.json();
  token = view.save_token;
  const picker = $('#package');
  picker.replaceChildren(...view.packages.map((p, i) => {
    const o = el('option', `${p.role_id} · “${p.query}” · ${p.ranking_config.config_id} ${p.ranking_config.version}`);
    o.value = String(i); return o;
  }));
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
    $('#summary').replaceChildren(el('p', 'No ranking package loaded. Start the server with --ranking <Issue #7 result JSON>.'));
    $('#queue').replaceChildren(); return;
  }
  const rc = p.ranking_config, contract = p.retrieval_contract, div = p.diversity_implementation;
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
  if (blocked) warnings.append(el('p', `${blocked} candidate(s) cannot be played now; see the highlighted cards.`));
  $('#queue').replaceChildren(...p.queue.map(e => card(p, e)));
  $('#beyond ol').replaceChildren(...p.not_in_queue.map(e => card(p, e)));
  $('#removed ul').replaceChildren(
    ...p.suppressed.map(s => el('li', `${s.candidate_id} (${s.sha256.slice(0, 12)}…): ${s.reasons.join('; ')}`)),
    ...p.excluded.map(x => el('li', `${x.candidate_id}: ${x.stage} ${x.status} — ${x.reasons.join('; ')}`)));
}

function card(p, e) {
  const v = e.verification, rec = e.recorded && e.recorded.candidate, rights = rec && rec.rights;
  const li = el('li', null, 'card' + (v.playable ? '' : ' blocked'));
  const h = el('h3', `Rank ${e.rank} · ${e.candidate_id}`);
  h.append(el('span', e.representation === 'original' ? 'Original bytes' : 'Preview bytes', 'badge ' + e.representation));
  li.append(h);
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
  li.append(grid, contributions(e));
  v.issues.forEach(text => li.append(el('p', text, 'issue')));
  li.append(player(p, e), decisionForm(p, e));
  return li;
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
  const box = el('div');
  if (!e.verification.playable) { box.append(el('p', 'Playback disabled: these exact bytes cannot be verified as present and eligible. No substitute file is played.')); return box; }
  // preload=none: only the player being auditioned holds a media pipeline (Chrome limits active players).
  const a = el('audio'); a.controls = true; a.preload = 'none';
  a.src = `/api/audio/${p.package_id}/${encodeURIComponent(e.candidate_id)}`;
  a.setAttribute('aria-label', `Listen to rank ${e.rank}, ${e.candidate_id}`);
  a.addEventListener('play', () => document.querySelectorAll('audio').forEach(o => { if (o !== a) o.pause(); }));
  box.append(a);
  const d = e.signals.dsp.duration_seconds;
  if (d > 20) {
    let stopAt = null;
    a.addEventListener('timeupdate', () => { if (stopAt !== null && a.currentTime >= stopAt) { a.pause(); stopAt = null; } });
    [[0, 'Start'], [Math.max(0, d / 2 - 5), 'Middle'], [Math.max(0, d - 10), 'End']].forEach(([at, word]) => {
      const b = el('button', `${word} · 10 s`); b.type = 'button';
      b.onclick = () => { a.currentTime = at; stopAt = Math.min(at + 10, d); a.play().catch(err => { status.textContent = err.message; }); };
      box.append(b);
    });
  }
  return box;
}

function decisionForm(p, e) {
  const name = `decision-${p.package_id.slice(0, 8)}-${e.candidate_id}`;
  const fs = el('fieldset'); fs.append(el('legend', 'Your decision'));
  const saved = el('p', null, 'saved');
  const describe = d => { saved.textContent = d ? `Saved: ${d.current || 'cleared'} at ${d.decided_at} (${d.events} event${d.events === 1 ? '' : 's'})` : 'No decision yet.'; };
  describe(e.decision);
  DECISIONS.forEach(([value, text]) => {
    const label = el('label'); const input = el('input'); input.type = 'radio'; input.name = name; input.value = value;
    input.checked = !!(e.decision && e.decision.current === value);
    input.disabled = !e.verification.playable && value !== 'reject';
    label.append(input, ' ' + text); fs.append(label);
  });
  const noteLabel = el('label', 'Note (optional)', 'note'); const note = el('textarea');
  note.value = (e.decision && e.decision.note) || ''; note.setAttribute('aria-label', `Note for ${e.candidate_id}`);
  noteLabel.append(note); fs.append(noteLabel);
  const save = el('button', 'Save decision'); save.type = 'button';
  const clear = el('button', 'Clear decision'); clear.type = 'button';
  async function send(decision) {
    try {
      const response = await fetch('/api/decision', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Audition-Token': token},
        body: JSON.stringify({package_id: p.package_id, candidate_id: e.candidate_id, representation: e.representation, sha256: e.sha256, decision, note: note.value})});
      if (!response.ok) throw new Error(await response.text());
      e.decision = (await response.json()).saved; describe(e.decision);
      if (decision === null) fs.querySelectorAll('input').forEach(i => { i.checked = false; });
      status.textContent = `Saved ${e.candidate_id}: ${decision || 'cleared'}.`;
    } catch (err) { status.textContent = `Not saved: ${err.message}`; }
  }
  save.onclick = () => {
    const chosen = fs.querySelector('input:checked');
    if (!chosen) { status.textContent = 'Choose a decision first, or use Clear decision.'; return; }
    send(chosen.value);
  };
  clear.onclick = () => send(null);
  fs.append(save, clear, saved);
  return fs;
}

$('#package').onchange = ev => { current = Number(ev.target.value); render(); };
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
load().then(() => { status.textContent = 'Ready. Decisions save per candidate and survive restart.'; })
  .catch(err => { status.textContent = err.message; });
