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

async function loadSettings() {
  const s = await api('/api/settings');
  const form = $('#settings-form');
  for (const [key, value] of Object.entries(s)) {
    const field = form.elements[key];
    if (!field) continue;
    if (field.type === 'checkbox') field.checked = !!value;
    else if (key === 'source_dirs') field.value = (value || []).join('\n');
    else if (LIST_FIELDS.includes(key)) field.value = (value || []).join(', ');
    else field.value = value ?? '';
  }
  $('#action-select').value = s.action || 'move';
  for (const kind of SCHEMES) state.editors[kind].set(s[`${kind}_format`] || '');
  return s;
}

$('#settings-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const payload = {};
  for (const field of form.elements) {
    if (!field.name) continue;
    if (field.type === 'checkbox') payload[field.name] = field.checked;
    else if (field.name === 'source_dirs') payload[field.name] = field.value.split('\n').map((v) => v.trim()).filter(Boolean);
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

async function poll(jobId) {
  for (;;) {
    const job = await api(`/api/scan/${jobId}`);
    state.items = job.items;
    const pct = job.total ? Math.round((job.done / job.total) * 100) : 0;
    $('#progress-bar').style.width = `${pct}%`;
    $('#progress-text').textContent = `${job.done} / ${job.total} Dateien`;
    render();
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
  for (const item of visibleItems()) {
    const el = document.createElement('div');
    el.className = `item ${item.status}`;

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
  }
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
            try {
              const updated = await api('/api/select', {
                method: 'POST',
                body: { job_id: state.jobId, src: item.src, provider: r.provider, id: r.id, kind: kindSel.value },
              });
              Object.assign(item, updated);
              closeModal();
              render();
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
    alert(`${res.ok} erfolgreich, ${res.failed} fehlgeschlagen.` +
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

loadSettings();
