/* Schema-Editor: Namensschema als anklickbare, verschiebbare Bubbles. */

const TOKENS = [
  { key: 'n', label: 'Titel', group: 'Allgemein' },
  { key: 'y', label: 'Jahr', group: 'Allgemein' },
  { key: 'lang', label: 'Sprachen', group: 'Allgemein' },
  { key: 'id', label: 'Datenbank-ID', group: 'Allgemein' },

  { key: 's', label: 'Staffel', group: 'Serie', kinds: ['series', 'anime'] },
  { key: 's.pad(2)', label: 'Staffel 01', group: 'Serie', kinds: ['series', 'anime'] },
  { key: 'e', label: 'Episode', group: 'Serie', kinds: ['series', 'anime'] },
  { key: 'e00', label: 'Episode 02', group: 'Serie', kinds: ['series', 'anime'] },
  { key: 's00e00', label: 'S01E02', group: 'Serie', kinds: ['series', 'anime'] },
  { key: 'sxe', label: '1x02', group: 'Serie', kinds: ['series', 'anime'] },
  { key: 't', label: 'Episodentitel', group: 'Serie', kinds: ['series', 'anime'] },
  { key: 'airdate', label: 'Erstausstrahlung', group: 'Serie', kinds: ['series', 'anime'] },

  { key: 'abs', label: 'Absolute Nr.', group: 'Anime', kinds: ['anime', 'series'] },
  { key: 'abs.pad(3)', label: 'Absolute Nr. 003', group: 'Anime', kinds: ['anime', 'series'] },
  { key: 'abs.pad(3)|s00e00', label: 'Absolut, sonst S01E02', group: 'Anime', kinds: ['anime', 'series'] },

  { key: 'collection', label: 'Filmreihe', group: 'Film', kinds: ['movie'] },
  { key: 'imdb', label: 'IMDb-ID', group: 'Film', kinds: ['movie'] },
  { key: "' CD'+pi", label: 'CD-Nummer (optional)', group: 'Film', kinds: ['movie'] },

  { key: 'vf', label: 'Auflösung', group: 'Release' },
  { key: 'vc', label: 'Video-Codec', group: 'Release' },
  { key: 'ac', label: 'Audio-Codec', group: 'Release' },
  { key: 'source', label: 'Quelle', group: 'Release' },
  { key: 'group', label: 'Release-Gruppe', group: 'Release' },
];

const LABELS = Object.fromEntries(TOKENS.map((t) => [t.key, t.label]));

/** Template-String -> Bubble-Liste. */
function parseTemplate(template) {
  const chips = [];
  const re = /\{[^{}]*\}/g;
  let last = 0;
  const pushText = (text) => {
    for (const piece of text.split('/')) {
      if (piece) chips.push({ type: 'text', value: piece });
      chips.push({ type: 'sep' });
    }
    chips.pop(); // letzter Trenner ist künstlich
  };
  let match;
  while ((match = re.exec(template)) !== null) {
    if (match.index > last) pushText(template.slice(last, match.index));
    chips.push({ type: 'token', value: match[0].slice(1, -1) });
    last = match.index + match[0].length;
  }
  if (last < template.length) pushText(template.slice(last));
  return chips.filter((c) => c.type !== 'text' || c.value !== '');
}

/** Bubble-Liste -> Template-String. */
function serialize(chips) {
  return chips.map((c) => {
    if (c.type === 'token') return `{${c.value}}`;
    if (c.type === 'sep') return '/';
    return c.value;
  }).join('');
}

class SchemeEditor {
  constructor(container, kind, hiddenInput, onChange) {
    this.kind = kind;
    this.hidden = hiddenInput;
    this.onChange = onChange;
    this.chips = [];
    this.dragIndex = null;
    this.build(container);
  }

  build(container) {
    container.innerHTML = '';
    this.canvas = document.createElement('div');
    this.canvas.className = 'canvas';
    container.appendChild(this.canvas);

    this.palette = document.createElement('div');
    this.palette.className = 'palette';
    container.appendChild(this.palette);
    this.buildPalette();

    const foot = document.createElement('div');
    foot.className = 'editor-foot';
    this.preview = document.createElement('p');
    this.preview.className = 'preview';
    const rawToggle = document.createElement('button');
    rawToggle.type = 'button';
    rawToggle.textContent = 'Als Text bearbeiten';
    const reset = document.createElement('button');
    reset.type = 'button';
    reset.textContent = 'Leeren';
    reset.onclick = () => { this.chips = []; this.sync(); };
    foot.append(this.preview, reset, rawToggle);
    container.appendChild(foot);

    this.raw = document.createElement('input');
    this.raw.className = 'raw hidden';
    this.raw.onchange = () => this.set(this.raw.value);
    container.appendChild(this.raw);
    rawToggle.onclick = () => {
      this.raw.classList.toggle('hidden');
      this.raw.value = serialize(this.chips);
    };

    // Ablegen auf freier Fläche hängt die Bubble ans Ende.
    this.canvas.addEventListener('dragover', (e) => {
      e.preventDefault();
      this.canvas.classList.add('drag-over');
    });
    this.canvas.addEventListener('dragleave', () => this.canvas.classList.remove('drag-over'));
    this.canvas.addEventListener('drop', (e) => {
      e.preventDefault();
      this.canvas.classList.remove('drag-over');
      if (e.target === this.canvas && this.dragIndex !== null) this.move(this.dragIndex, this.chips.length);
    });
  }

  buildPalette() {
    const groups = {};
    for (const token of TOKENS) {
      if (token.kinds && !token.kinds.includes(this.kind)) continue;
      (groups[token.group] ||= []).push(token);
    }
    for (const [name, tokens] of Object.entries(groups)) {
      const title = document.createElement('div');
      title.className = 'palette-group';
      title.textContent = name;
      this.palette.appendChild(title);
      for (const token of tokens) {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = 'pill';
        pill.textContent = `+ ${token.label}`;
        pill.title = `{${token.key}}`;
        pill.onclick = () => this.add({ type: 'token', value: token.key });
        this.palette.appendChild(pill);
      }
    }
    const extra = document.createElement('div');
    extra.className = 'palette-group';
    extra.textContent = 'Bausteine';
    this.palette.appendChild(extra);
    for (const [label, chip] of [
      ['Text', { type: 'text', value: ' - ' }],
      ['Ordnertrenner /', { type: 'sep' }],
    ]) {
      const pill = document.createElement('button');
      pill.type = 'button';
      pill.className = 'pill';
      pill.textContent = `+ ${label}`;
      pill.onclick = () => this.add({ ...chip });
      this.palette.appendChild(pill);
    }
  }

  set(template) {
    this.chips = parseTemplate(template || '');
    this.sync();
  }

  add(chip) {
    this.chips.push(chip);
    this.sync();
    if (chip.type === 'text') {
      const inputs = this.canvas.querySelectorAll('.bubble.text input');
      const last = inputs[inputs.length - 1];
      if (last) { last.focus(); last.select(); }
    }
  }

  move(from, to) {
    if (from === to || from === null) return;
    const [chip] = this.chips.splice(from, 1);
    this.chips.splice(from < to ? to - 1 : to, 0, chip);
    this.sync();
  }

  sync() {
    this.render();
    const template = serialize(this.chips);
    this.hidden.value = template;
    this.raw.value = template;
    this.onChange(this.kind, template, this.preview);
  }

  render() {
    this.canvas.innerHTML = '';
    if (!this.chips.length) {
      this.canvas.innerHTML = '<span class="placeholder">Noch leer – unten einen Baustein anklicken.</span>';
      return;
    }
    this.chips.forEach((chip, index) => this.canvas.appendChild(this.bubble(chip, index)));
  }

  bubble(chip, index) {
    const el = document.createElement('span');
    el.className = `bubble ${chip.type}`;
    el.draggable = true;

    if (chip.type === 'token') {
      const label = document.createElement('span');
      label.textContent = LABELS[chip.value] || `{${chip.value}}`;
      const hint = document.createElement('span');
      hint.className = 'hintlabel';
      hint.textContent = `{${chip.value}}`;
      el.append(label, hint);
    } else if (chip.type === 'sep') {
      el.append(document.createTextNode('/'));
    } else {
      const input = document.createElement('input');
      input.value = chip.value;
      input.size = Math.max(chip.value.length, 1);
      input.draggable = false;
      // Beim Tippen nicht neu rendern, sonst verliert das Feld den Fokus.
      input.oninput = () => {
        chip.value = input.value;
        input.size = Math.max(input.value.length, 1);
        const template = serialize(this.chips);
        this.hidden.value = template;
        this.raw.value = template;
        this.onChange(this.kind, template, this.preview);
      };
      input.onmousedown = (e) => e.stopPropagation();
      el.appendChild(input);
    }

    const remove = document.createElement('span');
    remove.className = 'x';
    remove.textContent = '✕';
    remove.title = 'Entfernen';
    remove.onclick = () => { this.chips.splice(index, 1); this.sync(); };
    el.appendChild(remove);

    el.addEventListener('dragstart', (e) => {
      this.dragIndex = index;
      el.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(index));
    });
    el.addEventListener('dragend', () => {
      el.classList.remove('dragging');
      this.dragIndex = null;
      this.canvas.querySelectorAll('.bubble').forEach((b) =>
        b.classList.remove('drop-before', 'drop-after'));
    });
    el.addEventListener('dragover', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const box = el.getBoundingClientRect();
      const after = e.clientX > box.left + box.width / 2;
      el.classList.toggle('drop-before', !after);
      el.classList.toggle('drop-after', after);
    });
    el.addEventListener('dragleave', () => el.classList.remove('drop-before', 'drop-after'));
    el.addEventListener('drop', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const box = el.getBoundingClientRect();
      const after = e.clientX > box.left + box.width / 2;
      el.classList.remove('drop-before', 'drop-after');
      this.move(this.dragIndex, after ? index + 1 : index);
    });
    return el;
  }
}

window.SchemeEditor = SchemeEditor;
