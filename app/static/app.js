const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  jobId: null, items: [], filter: 'all', category: 'all', selected: new Set(),
  history: [], histSel: new Set(), logTimer: null, editors: {},
};

const CATEGORIES = {
  movie: { label: 'Film', icon: '🎬' },
  series: { label: 'Serie', icon: '📺' },
  anime: { label: 'Anime', icon: '🎌' },
};

// Woher der Titel stammt – der Dateiname ist der Normalfall und bleibt unmarkiert.
const SOURCE_BADGES = {
  folder: '<span class="badge src-folder" title="Der Dateiname war nicht aussagekräftig, '
    + 'der Titel stammt aus dem Ordnernamen">📁 aus Ordner</span>',
  metadata: '<span class="badge src-meta" title="Titel aus den im Container '
    + 'eingebetteten Metadaten">🏷️ aus Metadaten</span>',
};

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || res.statusText);
  }
  return res.json();
}

/* ---------- Tabs ---------- */
$$('.tab').forEach((tab) => tab.addEventListener('click', () => {
  $$('.tab').forEach((t) => t.classList.toggle('active', t === tab));
  $$('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === `tab-${tab.dataset.tab}`));
  if (tab.dataset.tab === 'history') loadHistory();
  if (tab.dataset.tab === 'log') { loadLog(); startLogAuto(); } else stopLogAuto();
}));

/* ---------- Schema-Editoren ---------- */
const SCHEMES = ['movie', 'series', 'anime'];

$$('.scheme-tab').forEach((tab) => tab.addEventListener('click', () => {
  $$('.scheme-tab').forEach((t) => t.classList.toggle('active', t === tab));
  $$('.scheme-panel').forEach((p) =>
    p.classList.toggle('active', p.dataset.schemePanel === tab.dataset.scheme));
}));

async function schemePreview(kind, template, target) {
  try {
    const res = await api('/api/preview-format', { method: 'POST', body: { kind, template } });
    target.textContent = `Beispiel: ${res.preview}`;
    target.style.color = '';
  } catch (err) {
    target.textContent = `Ungültig: ${err.message}`;
    target.style.color = 'var(--err)';
  }
}

for (const kind of SCHEMES) {
  let timer;
  state.editors[kind] = new SchemeEditor(
    $(`[data-editor="${kind}"]`),
    kind,
    $('#settings-form').elements[`${kind}_format`],
    (k, template, previewEl) => {
      clearTimeout(timer);
      timer = setTimeout(() => schemePreview(k, template, previewEl), 300);
    },
  );
}

/* ---------- Einstellungen ---------- */
const LIST_FIELDS = ['extensions', 'subtitle_extensions', 'anime_keywords'];
const LINE_FIELDS = ['source_dirs', 'webhook_urls'];

async function loadSettings() {
  const s = await api('/api/settings');
  const form = $('#settings-form');
  for (const [key, value] of Object.entries(s)) {
    const field = form.elements[key];
    if (!field) continue;
    if (field.type === 'checkbox') field.checked = !!value;
    else if (LINE_FIELDS.includes(key)) field.value = (value || []).join('\n');
    else if (LIST_FIELDS.includes(key)) field.value = (value || []).join(', ');
    else field.value = value ?? '';
  }
  $('#action-select').value = s.action || 'move';
  for (const kind of SCHEMES) state.editors[kind].set(s[`${kind}_format`] || '');
  $('#auth-hint').textContent = s.auth_configured
    ? 'Ein Passwort ist gesetzt. Feld leer lassen, um es beizubehalten.'
    : 'Noch kein Passwort gesetzt – ohne Passwort bleibt die Anmeldung aus.';
  loadCacheInfo();
  syncArtworkOptions();
  return s;
}

/* Die einzelnen Bildarten sind nur bei aktivem Hauptschalter bedienbar. */
function syncArtworkOptions() {
  $('#artwork-types').classList.toggle('off', !$('#artwork-main').checked);
}
$('#artwork-main').addEventListener('change', syncArtworkOptions);

async function loadCacheInfo() {
  try {
    const info = await api('/api/cache');
    const age = info.oldest ? ` · ältester Eintrag ${new Date(info.oldest * 1000).toLocaleDateString('de-DE')}` : '';
    $('#cache-info').textContent = `${info.entries} zwischengespeicherte Antworten${age}`;
  } catch { $('#cache-info').textContent = 'Cache nicht lesbar.'; }
}

$('#btn-cache-clear').addEventListener('click', async () => {
  const res = await api('/api/cache', { method: 'DELETE' });
  $('#cache-info').textContent = `${res.cleared} Einträge entfernt.`;
});

$('#btn-notify-test').addEventListener('click', async () => {
  $('#notify-status').textContent = 'Teste …';
  try {
    const res = await api('/api/notify-test', { method: 'POST' });
    const keys = Object.keys(res);
    $('#notify-status').textContent = keys.length
      ? keys.map((k) => `${k}: ${res[k] ? 'ok' : 'Fehler'}`).join(', ')
      : 'Nichts konfiguriert.';
  } catch (err) { $('#notify-status').textContent = `Fehler: ${err.message}`; }
});

$('#settings-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const payload = {};
  for (const field of form.elements) {
    if (!field.name) continue;
    if (field.type === 'checkbox') payload[field.name] = field.checked;
    else if (LINE_FIELDS.includes(field.name)) payload[field.name] = field.value.split('\n').map((v) => v.trim()).filter(Boolean);
    else if (LIST_FIELDS.includes(field.name)) payload[field.name] = field.value.split(',').map((v) => v.trim()).filter(Boolean);
    else if (field.type === 'number') payload[field.name] = Number(field.value);
    else if (field.value !== '***' && field.value !== '') payload[field.name] = field.value;
  }
  for (const kind of SCHEMES) {
    if (!payload[`${kind}_format`]) {
      $('#settings-status').textContent = `Das Schema für ${CATEGORIES[kind].label} darf nicht leer sein.`;
      return;
    }
  }
  try {
    await api('/api/settings', { method: 'POST', body: payload });
    $('#settings-status').textContent = 'Gespeichert.';
  } catch (err) {
    $('#settings-status').textContent = `Fehler: ${err.message}`;
  }
  setTimeout(() => { $('#settings-status').textContent = ''; }, 3000);
});

/* ---------- Modal ---------- */
function openModal(title, render) {
  $('#modal-title').textContent = title;
  $('#modal-body').innerHTML = '';
  render($('#modal-body'));
  $('#modal').classList.remove('hidden');
}
function closeModal() { $('#modal').classList.add('hidden'); }
$('#modal-close').addEventListener('click', closeModal);
$('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });

/* ---------- Verzeichnis-Browser ---------- */
$$('.browse').forEach((btn) => btn.addEventListener('click', () => {
  const field = $('#settings-form').elements[btn.dataset.target];
  openModal('Ordner wählen', async (body) => {
    const render = async (path) => {
      const data = await api(`/api/browse?path=${encodeURIComponent(path)}`);
      body.innerHTML = '';
      const bar = document.createElement('div');
      bar.className = 'search-bar';
      bar.innerHTML = `<input value="${data.path}" readonly>`;
      const use = document.createElement('button');
      use.className = 'primary';
      use.textContent = 'Übernehmen';
      use.onclick = () => { field.value = data.path; closeModal(); };
      bar.appendChild(use);
      body.appendChild(bar);
      if (data.parent) {
        const up = document.createElement('div');
        up.className = 'dir-row';
        up.textContent = '⬆ ..';
        up.onclick = () => render(data.parent);
        body.appendChild(up);
      }
      for (const dir of data.dirs) {
        const row = document.createElement('div');
        row.className = 'dir-row';
        row.textContent = `📁 ${dir.name}`;
        row.onclick = () => render(dir.path);
        body.appendChild(row);
      }
    };
    render(field.value || '/');
  });
}));

/* ---------- Scan ---------- */
$('#btn-scan').addEventListener('click', async () => {
  $('#btn-scan').disabled = true;
  $('#empty-hint').classList.add('hidden');
  $('#progress').classList.remove('hidden');
  state.items = []; state.selected.clear();
  try {
    const { job_id: jobId } = await api('/api/scan', {
      method: 'POST', body: { include_subtitles: $('#include-subs').checked },
    });
    state.jobId = jobId;
    await poll(jobId);
  } catch (err) {
    $('#progress-text').textContent = `Fehler: ${err.message}`;
  } finally {
    $('#btn-scan').disabled = false;
  }
});

$('#btn-cancel').addEventListener('click', async () => {
  $('#btn-cancel').disabled = true;
  try { await api(`/api/scan/${state.jobId}/cancel`, { method: 'POST' }); } catch { /* egal */ }
});

async function restoreLastScan() {
  try {
    const job = await api('/api/scan');
    if (!job.items || !job.items.length) return;
    state.jobId = job.id;
    state.items = job.items;
    $('#empty-hint').classList.add('hidden');
    $('#filters').classList.remove('hidden');
    $('#progress').classList.remove('hidden');
    $('#progress-bar').style.width = '100%';
    const when = job.finished ? new Date(job.finished * 1000).toLocaleString('de-DE') : '';
    $('#progress-text').textContent = `Letzter Scan (${when}): ${job.items.length} Dateien`;
    if (job.status === 'running') poll(job.id);
    render();
  } catch { /* noch kein Scan vorhanden */ }
}

async function poll(jobId) {
  for (;;) {
    const job = await api(`/api/scan/${jobId}`);
    state.items = job.items;
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    $('#progress-bar').style.width = `${pct}%`;
    $('#progress-text').textContent = `${job.done} / ${job.total} Dateien`;
    render();
    $('#btn-cancel').classList.toggle('hidden', job.status !== 'running');
    if (job.status === 'cancelled') {
      $('#progress-text').textContent = `Abgebrochen nach ${job.done} Dateien.`;
      $('#filters').classList.remove('hidden');
      $('#btn-cancel').disabled = false;
      return;
    }
    if (job.status === 'done') {
      $('#progress-text').textContent = `Fertig: ${job.total} Dateien analysiert.`;
      if (!job.total) $('#progress-text').textContent = 'Keine passenden Dateien gefunden.';
      $('#filters').classList.remove('hidden');
      return;
    }
    if (job.status === 'error') {
      $('#progress-text').textContent = `Fehler: ${job.error}`;
      return;
    }
    await new Promise((r) => setTimeout(r, 700));
  }
}

/* ---------- Ergebnisliste ---------- */
$$('.chip[data-filter]').forEach((chip) => chip.addEventListener('click', () => {
  $$('.chip[data-filter]').forEach((c) => c.classList.toggle('active', c === chip));
  state.filter = chip.dataset.filter;
  render();
}));

$$('.chip[data-cat]').forEach((chip) => chip.addEventListener('click', () => {
  $$('.chip[data-cat]').forEach((c) => c.classList.toggle('active', c === chip));
  state.category = chip.dataset.cat;
  render();
}));

$('#select-all').addEventListener('change', (e) => {
  visibleItems().forEach((item) => {
    if (!item.dest) return;
    if (e.target.checked) state.selected.add(item.src);
    else state.selected.delete(item.src);
  });
  render();
});

function visibleItems() {
  return state.items.filter((i) =>
    (state.filter === 'all' || i.status === state.filter) &&
    (state.category === 'all' || (i.category || 'movie') === state.category));
}

function render() {
  const container = $('#results');
  container.innerHTML = '';
  visibleItems().forEach((item, index) => {
    const el = document.createElement('div');
    el.className = `item ${item.status}${index === focusIndex ? ' focused' : ''}`;

    const check = document.createElement('input');
    check.type = 'checkbox';
    check.disabled = !item.dest;
    check.checked = state.selected.has(item.src);
    check.onchange = () => {
      if (check.checked) state.selected.add(item.src); else state.selected.delete(item.src);
      $('#btn-apply').disabled = state.selected.size === 0;
    };

    const info = document.createElement('div');
    const badge = item.status === 'matched' ? 'ok' : item.status === 'review' ? 'warn' : 'err';
    const g = item.guess || {};
    info.innerHTML = `<div class="src">${item.src}</div>`;
    if (item.dest) {
      const dest = document.createElement('input');
      dest.className = 'dest editable';
      dest.value = item.dest;
      dest.onchange = () => { item.dest = dest.value; };
      info.appendChild(dest);
    } else {
      info.insertAdjacentHTML('beforeend', `<div class="dest">${item.error || 'Kein Ziel ermittelt'}</div>`);
    }
    const cat = CATEGORIES[item.category] || CATEGORIES.movie;
    const meta = [
      `<span class="badge ${badge}">${{ matched: 'Erkannt', review: 'Prüfen', unmatched: 'Ohne Treffer' }[item.status]}</span>`,
      `<span class="badge cat-${item.category || 'movie'}">${cat.icon} ${cat.label}</span>`,
      SOURCE_BADGES[item.title_source] || '',
      item.existing
        ? `<span class="badge exists ${item.existing.verdict === 'better' ? 'better' : ''}"
             title="Im Ziel liegt bereits: ${item.existing.path}">${
               item.existing.verdict === 'better' ? '⬆ ersetzt schlechtere Fassung'
               : item.existing.verdict === 'worse' ? '⬇ vorhandene ist besser'
               : '= schon vorhanden'} (${item.existing.quality})</span>`
        : '',
      item.linked_to ? '<span class="badge">🔗 folgt dem Video</span>' : '',
      item.match ? `<span>${item.match.title}${item.match.year ? ` (${item.match.year})` : ''} · ${item.match.provider.toUpperCase()}</span>` : '',
      `<span>Qualität ${Math.round((item.confidence || 0) * 100)} %</span>`,
      item.is_subtitle ? '<span class="badge">Untertitel</span>' : '',
    ].filter(Boolean).join('');
    info.insertAdjacentHTML('beforeend', `<div class="meta">${meta}</div>`);

    const actions = document.createElement('div');
    actions.className = 'actions';
    const pick = document.createElement('button');
    pick.textContent = 'Treffer wählen';
    pick.onclick = () => openPicker(item);
    actions.appendChild(pick);

    // Kategorie umschalten – wichtig, wenn ein Anime als normale Serie erkannt wurde.
    const catSelect = document.createElement('select');
    catSelect.title = 'Kategorie und damit Namensschema und Zielordner';
    catSelect.innerHTML = Object.entries(CATEGORIES)
      .map(([key, c]) => `<option value="${key}">${c.icon} ${c.label}</option>`).join('');
    catSelect.value = item.category || 'movie';
    catSelect.disabled = !item.match;
    catSelect.onchange = async () => {
      try {
        const updated = await api('/api/category', {
          method: 'POST',
          body: { job_id: state.jobId, src: item.src, category: catSelect.value },
        });
        Object.assign(item, updated);
        render();
      } catch (err) {
        alert(err.message);
        catSelect.value = item.category || 'movie';
      }
    };
    actions.appendChild(catSelect);

    el.append(check, info, actions);
    container.appendChild(el);
  });
  $('#btn-apply').disabled = state.selected.size === 0;
}

function openPicker(item) {
  const g = item.guess || {};
  openModal(`Treffer wählen – ${item.name}`, (body) => {
    const bar = document.createElement('div');
    bar.className = 'search-bar';
    const input = document.createElement('input');
    input.value = g.title || '';
    const kindSel = document.createElement('select');
    kindSel.innerHTML = Object.entries(CATEGORIES)
      .map(([key, c]) => `<option value="${key}">${c.icon} ${c.label}</option>`).join('');
    kindSel.value = item.category || 'movie';
    const go = document.createElement('button');
    go.className = 'primary';
    go.textContent = 'Suchen';
    bar.append(input, kindSel, go);
    body.appendChild(bar);
    const list = document.createElement('div');
    body.appendChild(list);

    const search = async () => {
      list.innerHTML = '<p class="hint" style="padding:12px 16px">Suche läuft …</p>';
      try {
        const { results } = await api('/api/search', {
          method: 'POST', body: { kind: kindSel.value, query: input.value, year: g.year || null },
        });
        list.innerHTML = results.length ? '' : '<p class="hint" style="padding:12px 16px">Keine Treffer.</p>';
        for (const r of results) {
          const row = document.createElement('div');
          row.className = 'result-row';
          row.innerHTML = `${r.poster ? `<img src="${r.poster}" alt="">` : ''}
            <div><div class="t">${r.title}${r.year ? ` (${r.year})` : ''}</div>
            <div class="src">${(r.overview || '').slice(0, 140)}</div></div>`;
          row.onclick = async () => {
            let srcs = null;
            // Bei Serien anbieten, gleich alle Episoden desselben Titels zu setzen.
            if (kindSel.value !== 'movie') {
              try {
                const g = await api(`/api/group/${state.jobId}?src=${encodeURIComponent(item.src)}`);
                if (g.srcs.length > 1 &&
                    confirm(`${g.srcs.length} Dateien wurden als „${g.title}" erkannt.\n\n`
                          + `OK = alle auf „${r.title}" setzen\nAbbrechen = nur diese eine Datei`)) {
                  srcs = g.srcs;
                }
              } catch { /* Gruppe unbekannt: dann eben nur diese Datei */ }
            }
            try {
              const res = await api('/api/select', {
                method: 'POST',
                body: { job_id: state.jobId, src: item.src, srcs,
                        provider: r.provider, id: r.id, kind: kindSel.value },
              });
              for (const updated of res.items) {
                const target = state.items.find((i) => i.src === updated.src);
                if (target) Object.assign(target, updated);
              }
              closeModal();
              render();
              if (res.failed.length) alert(`${res.failed.length} Datei(en) konnten nicht zugewiesen werden.`);
            } catch (err) { alert(err.message); }
          };
          list.appendChild(row);
        }
      } catch (err) {
        list.innerHTML = `<p class="hint" style="padding:12px 16px">Fehler: ${err.message}</p>`;
      }
    };
    go.onclick = search;
    input.onkeydown = (e) => { if (e.key === 'Enter') search(); };
    search();
  });
}

/* ---------- Übernehmen ---------- */
$('#btn-apply').addEventListener('click', async () => {
  const items = state.items
    .filter((i) => state.selected.has(i.src) && i.dest)
    .map((i) => ({ src: i.src, dest: i.dest }));
  if (!items.length) return;
  const action = $('#action-select').value;
  if (action !== 'test' && !confirm(`${items.length} Datei(en) verarbeiten (${action})?`)) return;
  $('#btn-apply').disabled = true;
  try {
    const res = await api('/api/apply', { method: 'POST', body: { items, action } });
    const failed = res.results.filter((r) => !r.ok);
    alert(`${res.ok} erfolgreich, ${res.skipped || 0} übersprungen, ${res.failed} fehlgeschlagen.` +
      (failed.length ? `\n\n${failed.slice(0, 5).map((f) => `${f.src}: ${f.error}`).join('\n')}` : ''));
    if (action !== 'test') {
      const done = new Set(res.results.filter((r) => r.ok).map((r) => r.src));
      state.items = state.items.filter((i) => !done.has(i.src));
      done.forEach((src) => state.selected.delete(src));
      render();
    }
  } catch (err) {
    alert(`Fehler: ${err.message}`);
  } finally {
    $('#btn-apply').disabled = state.selected.size === 0;
  }
});

/* ---------- Verlauf ---------- */
async function loadHistory() {
  const { entries } = await api('/api/history');
  state.history = entries;
  state.histSel.clear();
  renderHistory();
}

function renderHistory() {
  const needle = $('#history-search').value.trim().toLowerCase();
  const mode = $('#history-filter').value;
  const entries = state.history.filter((e) => {
    if (mode === 'open' && e.undone) return false;
    if (mode === 'undone' && !e.undone) return false;
    if (needle && !`${e.src} ${e.dest}`.toLowerCase().includes(needle)) return false;
    return true;
  });
  const list = $('#history-list');
  list.innerHTML = entries.length
    ? ''
    : `<p class="hint">${state.history.length ? 'Keine Einträge für diesen Filter.' : 'Noch keine Operationen ausgeführt.'}</p>`;
  for (const entry of entries) {
    const row = document.createElement('div');
    row.className = `hist${entry.undone ? ' undone' : ''}`;
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.disabled = !!entry.undone;
    check.checked = state.histSel.has(entry.time);
    check.onchange = () => {
      if (check.checked) state.histSel.add(entry.time); else state.histSel.delete(entry.time);
      $('#btn-undo').disabled = state.histSel.size === 0;
    };
    const text = document.createElement('div');
    text.className = 'd';
    text.innerHTML = `<div>${new Date(entry.time * 1000).toLocaleString('de-DE')} · ${entry.action}
      ${entry.undone ? '· rückgängig gemacht' : ''}</div>
      <div class="src">${entry.src}</div><div class="src">→ ${entry.dest}</div>`;
    row.append(check, text);
    list.appendChild(row);
  }
  $('#btn-undo').disabled = state.histSel.size === 0;
}

$('#history-search').addEventListener('input', renderHistory);
$('#history-filter').addEventListener('change', renderHistory);
$('#btn-history-reload').addEventListener('click', loadHistory);

$('#history-all').addEventListener('change', (e) => {
  $$('#history-list input[type=checkbox]').forEach((c) => {
    if (c.disabled) return;
    c.checked = e.target.checked;
    c.dispatchEvent(new Event('change'));
  });
});

$('#btn-undo').addEventListener('click', async () => {
  if (!confirm(`${state.histSel.size} Operation(en) rückgängig machen?`)) return;
  const res = await api('/api/undo', { method: 'POST', body: { times: [...state.histSel] } });
  const failed = res.results.filter((r) => !r.ok);
  alert(`${res.ok} rückgängig gemacht.` +
    (failed.length ? `\n\n${failed.map((f) => `${f.dest}: ${f.error}`).join('\n')}` : ''));
  loadHistory();
});

/* ---------- Log ---------- */
async function loadLog() {
  const level = $('#log-level').value;
  const query = $('#log-search').value.trim();
  const list = $('#log-list');
  try {
    const data = await api(`/api/logs?level=${level}&q=${encodeURIComponent(query)}&limit=500`);
    list.innerHTML = data.entries.length
      ? ''
      : '<p class="hint" style="padding:12px">Keine Einträge für diesen Filter.</p>';
    for (const entry of data.entries) {
      const row = document.createElement('div');
      row.className = `log-row ${entry.level}`;
      const time = new Date(entry.time * 1000).toLocaleString('de-DE');
      row.innerHTML = `<span class="ts">${time}</span><span class="lvl">${entry.level}</span>`;
      const msg = document.createElement('span');
      msg.className = 'msg';
      msg.textContent = entry.message;
      row.appendChild(msg);
      list.appendChild(row);
    }
    $('#log-meta').textContent =
      `${data.entries.length} von ${data.total} Zeilen im Speicher · vollständiges Log: ${data.file}`;
  } catch (err) {
    list.innerHTML = `<p class="hint" style="padding:12px">Log nicht abrufbar: ${err.message}</p>`;
  }
}

function startLogAuto() {
  stopLogAuto();
  if ($('#log-auto').checked) state.logTimer = setInterval(loadLog, 4000);
}
function stopLogAuto() {
  if (state.logTimer) { clearInterval(state.logTimer); state.logTimer = null; }
}

$('#btn-log-reload').addEventListener('click', loadLog);
$('#log-level').addEventListener('change', loadLog);
$('#log-auto').addEventListener('change', startLogAuto);
$('#log-search').addEventListener('input', () => {
  clearTimeout(state.logSearchTimer);
  state.logSearchTimer = setTimeout(loadLog, 300);
});

/* ---------- Automatikbetrieb ---------- */
async function loadAuto() {
  try {
    const auto = await api('/api/auto');
    $('#auto-dot').classList.toggle('on', auto.enabled);
    const last = auto.last_run ? new Date(auto.last_run * 1000).toLocaleTimeString('de-DE') : '–';
    const next = auto.next_run ? new Date(auto.next_run * 1000).toLocaleTimeString('de-DE') : '–';
    $('#auto-text').textContent = auto.enabled
      ? (auto.running
        ? 'Automatik läuft gerade …'
        : `Automatik alle ${auto.interval_minutes} min · zuletzt ${last} · nächster Lauf ${next}`)
      : 'Automatik: aus (unter „Einstellungen“ aktivierbar)';
  } catch { /* bei Anmeldepflicht schlicht ignorieren */ }
}

async function runAuto(dryRun) {
  const label = dryRun ? 'Testlauf' : 'Automatiklauf';
  if (!dryRun && !confirm('Automatiklauf jetzt starten? Sicher erkannte Dateien werden verschoben.')) return;
  $('#btn-auto-now').disabled = $('#btn-auto-dry').disabled = true;
  $('#auto-text').textContent = `${label} läuft …`;
  try {
    const r = await api(`/api/auto/run?dry_run=${dryRun}`, { method: 'POST' });
    alert(`${label} fertig:\n${r.scanned} gefunden, ${r.applied} verarbeitet, `
      + `${r.skipped} übersprungen, ${r.failed} Fehler, ${r.review} zur Durchsicht, `
      + `${r.waiting} noch im Schreibvorgang.`);
  } catch (err) {
    alert(`Fehler: ${err.message}`);
  } finally {
    $('#btn-auto-now').disabled = $('#btn-auto-dry').disabled = false;
    loadAuto();
  }
}

$('#btn-auto-now').addEventListener('click', () => runAuto(false));
$('#btn-auto-dry').addEventListener('click', () => runAuto(true));
setInterval(loadAuto, 20000);

/* ---------- Tastaturbedienung ---------- */
let focusIndex = -1;

function moveFocus(delta) {
  const items = visibleItems();
  if (!items.length) return;
  focusIndex = Math.max(0, Math.min(items.length - 1, focusIndex + delta));
  render();
  const el = $$('#results .item')[focusIndex];
  if (el) el.scrollIntoView({ block: 'nearest' });
}

document.addEventListener('keydown', (event) => {
  const tag = event.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (!$('#tab-rename').classList.contains('active')) return;
  if (!$('#modal').classList.contains('hidden')) return;

  const items = visibleItems();
  if (event.key === 'ArrowDown') { event.preventDefault(); moveFocus(1); }
  else if (event.key === 'ArrowUp') { event.preventDefault(); moveFocus(-1); }
  else if (event.key === ' ' && items[focusIndex]) {
    event.preventDefault();
    const item = items[focusIndex];
    if (!item.dest) return;
    if (state.selected.has(item.src)) state.selected.delete(item.src);
    else state.selected.add(item.src);
    render();
  } else if (event.key === 'Enter' && event.ctrlKey) {
    event.preventDefault();
    $('#btn-apply').click();
  } else if (event.key === 'Enter' && items[focusIndex]) {
    event.preventDefault();
    openPicker(items[focusIndex]);
  } else if (event.key === 'a') {
    event.preventDefault();
    $('#select-all').checked = !$('#select-all').checked;
    $('#select-all').dispatchEvent(new Event('change'));
  }
});

loadAuto();
loadSettings();
restoreLastScan();
