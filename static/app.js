'use strict';
/* Art Studio front end. No framework.
   - `state` holds everything the screens need.
   - Each tab has one function that draws it (tabPaintings, tabOrders, ...).
   - One click listener and one submit listener read data-act / data-form
     attributes and call the matching function in ACTIONS / FORMS.
   The server decides what is allowed; this file only shows the right buttons. */

// ---------- small helpers ----------
const $ = (sel, root = document) => root.querySelector(sel);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inr = n => '₹ ' + Number(n).toLocaleString('en-IN');
const imgSrc = u => (/^https?:\/\//.test(u) ? u : '/static/' + String(u).replace(/^\/+/, ''));
const pad = n => String(n).padStart(2, '0');
const addDays = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const parseDay = iso => new Date(iso + 'T00:00:00');
const longDate = iso => parseDay(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });

const state = { me: null, tab: 'paintings', catalog: null, authMode: 'login', onlyAvailable: false, paintings: [], pottery: [], taken: [] };
let reloadList = () => {};
let dialogCfg = null;
const isStudio = () => !!state.me && state.me.role === 'studio';

// ---------- talking to the server ----------
async function api(path, method = 'GET', body) {
  let res;
  try {
    res = await fetch('/api' + path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  } catch (_) {
    throw new Error("Can't reach the server. Check your connection and try again.");
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }
  if (!res.ok) {
    if (res.status === 401 && state.me) { state.me = null; state.catalog = null; toast('Your session ended. Please log in again.'); render(); }
    throw new Error((data && data.error) || `Something went wrong (${res.status}).`);
  }
  return data;
}

let toastTimer;
function toast(text, ok = false) {
  const t = $('#toast');
  clearTimeout(toastTimer);
  if (!text) { t.hidden = true; return; }
  t.textContent = text;
  t.className = 'toast' + (ok ? '' : ' err');
  t.hidden = false;
  toastTimer = setTimeout(() => { t.hidden = true; }, ok ? 3500 : 7000);
}

// Runs one change on the server, then redraws. On failure shows the server's message and refreshes the list.
async function mutate(path, method, body, okText) {
  try { await api(path, method, body); toast(okText, true); await render(); }
  catch (e) { toast(e.message); reloadList(); }
}

// ---------- reusable pieces ----------
const statusTag = s => `<span class="status s-${esc(s)}">${esc(s)}</span>`;
const pageHead = (title, lede, extra = '') => `<div class="page-head"><div><h1 class="page-title">${esc(title)}</h1><p class="lede">${esc(lede)}</p></div>${extra}</div>`;
const errorState = e => `<div class="state err"><p>Couldn't load this: ${esc(e.message)}</p><button class="btn" data-act="reload">Try again</button></div>`;

function imgFail(img) {
  const s = document.createElement('span');
  s.className = 'noimg';
  s.textContent = 'Image unavailable';
  img.replaceWith(s);
}

// A button that POSTs to the server when clicked (optionally after a "are you sure?" dialog).
function postBtn(label, path, okText, { cls = '', confirm = '', yes = '' } = {}) {
  const ask = confirm ? ` data-confirm="${esc(confirm)}" data-yes="${esc(yes)}"` : '';
  return `<button class="btn ${cls}" data-act="post" data-path="${esc(path)}" data-ok="${esc(okText)}"${ask}>${esc(label)}</button>`;
}

function fieldHTML(f) {
  const id = 'f_' + f.name;
  const attrs = ['min', 'max', 'step', 'maxlength', 'minlength', 'autocomplete', 'placeholder']
    .filter(k => f[k] != null).map(k => `${k}="${esc(f[k])}"`).join(' ') + (f.required ? ' required' : '');
  let control;
  if (f.type === 'select') {
    control = `<select id="${id}" name="${f.name}" ${attrs}>${f.options.map(o =>
      `<option value="${esc(o.value)}"${String(o.value) === String(f.value) ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
  } else if (f.type === 'textarea') {
    control = `<textarea id="${id}" name="${f.name}" rows="3" ${attrs}>${esc(f.value ?? '')}</textarea>`;
  } else {
    control = `<input id="${id}" name="${f.name}" type="${f.type || 'text'}" value="${esc(f.value ?? '')}" ${attrs}>`;
  }
  return `<div class="field"><label for="${id}">${esc(f.label)}</label>${control}${f.hint ? `<small>${esc(f.hint)}</small>` : ''}</div>`;
}

const formHTML = (name, fields, submit, extra = '') =>
  `<form data-form="${name}">${fields.map(fieldHTML).join('')}${extra}<p class="form-error" role="alert" hidden></p><button class="btn solid" type="submit">${esc(submit)}</button></form>`;

// A small dialog with a form inside (used for add/edit).
function openForm(cfg) {
  dialogCfg = cfg;
  const d = $('#formDialog');
  d.innerHTML = `<div class="dlg-body"><h2 class="dlg-title">${esc(cfg.title)}</h2>
    <form data-form="dialog">${cfg.fields.map(fieldHTML).join('')}
      <p class="form-error" role="alert" hidden></p>
      <div class="dlg-actions"><button class="btn solid" type="submit">${esc(cfg.submit)}</button>
      <button class="btn quiet" type="button" data-act="close-dialog">Cancel</button></div></form></div>`;
  d.showModal();
}

// "Are you sure?" dialog. Resolves true only if the person confirms.
function ask(text, yes = 'Yes') {
  return new Promise(resolve => {
    const d = $('#confirmDialog');
    d.innerHTML = `<form method="dialog" class="dlg-body"><p class="confirm-text">${esc(text)}</p>
      <div class="dlg-actions"><button class="btn solid" value="yes">${esc(yes)}</button><button class="btn quiet" value="no">Go back</button></div></form>`;
    d.returnValue = '';
    d.addEventListener('close', () => resolve(d.returnValue === 'yes'), { once: true });
    d.showModal();
  });
}

// ---------- chrome (header) ----------
const TAB_LABELS = { paintings: 'Paintings', orders: 'Orders', bookings: 'Wall painting', pottery: 'Pottery' };

function renderChrome() {
  const top = $('#top');
  if (!state.me) { top.innerHTML = '<span class="brand">Art Studio</span>'; return; }
  top.innerHTML = `<span class="brand">Art Studio</span>
    <nav class="nav" aria-label="Sections">${Object.keys(TAB_LABELS).map(t =>
      `<button data-act="tab" data-tab="${t}"${t === state.tab ? ' aria-current="page"' : ''}>${TAB_LABELS[t]}</button>`).join('')}</nav>
    <div class="who"><span class="eyebrow">${esc(state.me.email)} · ${isStudio() ? 'Studio' : 'Customer'}</span>
      <button class="btn quiet" data-act="logout">Log out</button></div>`;
}

// ---------- landing (logged out) ----------
function renderLanding() {
  const login = state.authMode === 'login';
  const fields = [
    { name: 'email', label: 'Email', type: 'email', required: true, autocomplete: 'username' },
    { name: 'password', label: 'Password', type: 'password', required: true, minlength: login ? null : 6,
      autocomplete: login ? 'current-password' : 'new-password', hint: login ? null : 'At least 6 characters.' },
  ];
  $('#view').innerHTML = `<section class="hero">
    <div class="hero-art"><img src="/static/images/p-012.jpg" alt="A painting from the studio collection" onerror="this.remove()"></div>
    <div class="hero-copy">
      <div><p class="eyebrow">Original Indian art, made by hand</p><h1 class="hero-title">Paintings<br>Murals<br>Pottery</h1></div>
      <div class="hero-auth">
        <div class="tabs">
          <button data-act="auth-mode" data-mode="login"${login ? ' aria-current="true"' : ''}>Log in</button>
          <button data-act="auth-mode" data-mode="signup"${login ? '' : ' aria-current="true"'}>Sign up</button>
        </div>
        ${formHTML(login ? 'login' : 'signup', fields, login ? 'Log in' : 'Create account')}
      </div>
    </div></section>`;
}

// ---------- paintings ----------
function paintingAction(p) {
  if (p.status !== 'available') return '';
  return isStudio()
    ? `<button class="btn" data-act="edit-painting" data-id="${p.id}">Edit</button>`
    : `<button class="btn solid" data-act="buy" data-id="${p.id}">Buy</button>`;
}

function workCard(p) {
  const sold = p.status !== 'available';
  return `<article class="work${sold ? ' sold' : ''}">
    <button class="frame" data-act="open-painting" data-id="${p.id}" aria-label="View ${esc(p.title)}">
      ${p.image_url ? `<img src="${esc(imgSrc(p.image_url))}" alt="" loading="lazy" onerror="imgFail(this)">` : '<span class="noimg">No image</span>'}
      ${sold ? '<span class="sold-chip">Sold</span>' : ''}
    </button>
    <h3 class="work-title" title="${esc(p.title)}">${esc(p.title)}</h3>
    <p class="eyebrow">${esc(p.artist)}</p>
    <div class="work-foot"><span class="price">${inr(p.price)}</span>${paintingAction(p)}</div>
  </article>`;
}

function tabPaintings() {
  $('#view').innerHTML = pageHead('Paintings', 'Each work is one of a kind and can be bought once.',
    isStudio() ? '<button class="btn solid" data-act="add-painting">Add a painting</button>' : '') +
    `<div class="bar"><p class="eyebrow" id="count"></p>
       <label class="check"><input type="checkbox" data-act="filter"${state.onlyAvailable ? ' checked' : ''}> Available only</label></div>
     <div id="list"></div>`;
  reloadList = loadPaintings;
  loadPaintings();
}

async function loadPaintings() {
  const el = $('#list');
  if (!el) return;
  el.innerHTML = '<p class="state eyebrow">Loading…</p>';
  try { state.paintings = await api('/paintings'); drawPaintings(); }
  catch (e) { el.innerHTML = errorState(e); }
}

function drawPaintings() {
  const all = state.paintings;
  const free = all.filter(p => p.status === 'available');
  const shown = state.onlyAvailable ? free : all;
  $('#count').textContent = `${all.length} works · ${free.length} available`;
  $('#list').innerHTML = shown.length
    ? `<div class="grid">${shown.map(workCard).join('')}</div>`
    : `<p class="state">${all.length ? 'Nothing is available right now.' : 'No paintings yet.'}</p>`;
}

function openPainting(id) {
  const p = state.paintings.find(x => x.id === id);
  if (!p) return;
  const d = $('#detailDialog');
  d.innerHTML = `<div class="detail">
    <div class="detail-art">${p.image_url ? `<img src="${esc(imgSrc(p.image_url))}" alt="${esc(p.title)}" onerror="imgFail(this)">` : '<span class="noimg">No image</span>'}</div>
    <div class="detail-copy">
      <p class="eyebrow">${esc(p.artist || 'Studio collection')}</p>
      <h2 class="detail-title">${esc(p.title)}</h2>
      <p class="detail-desc">${esc(p.description)}</p>
      <p class="detail-price">${inr(p.price)}</p>
      ${p.status !== 'available' ? '<div><span class="status s-sold">Sold</span></div>' : ''}
      <div class="actions">${paintingAction(p)}<button class="btn quiet" data-act="close-dialog">Close</button></div>
    </div></div>`;
  d.showModal();
}

function openPaintingForm(p) {
  const editing = !!p;
  openForm({
    title: editing ? 'Edit painting' : 'Add a painting',
    submit: editing ? 'Save changes' : 'Add painting',
    fields: [
      { name: 'title', label: 'Title', value: p?.title, required: true, maxlength: 200 },
      { name: 'artist', label: 'Artist', value: p?.artist, maxlength: 120 },
      { name: 'price', label: 'Price (₹)', type: 'number', value: p?.price, required: true, min: 1 },
      { name: 'description', label: 'Description', type: 'textarea', value: p?.description },
      { name: 'image_url', label: 'Image path', value: p?.image_url, hint: 'A file inside static/images, like images/p-013.jpg.' },
    ],
    onSubmit: async d => {
      if (editing) await api('/paintings/' + p.id, 'PUT', d); else await api('/paintings', 'POST', d);
      toast(editing ? 'Painting updated.' : 'Painting added.', true);
    },
  });
}

// ---------- orders ----------
function orderRow(o) {
  const cancel = !isStudio() && o.status === 'placed'
    ? postBtn('Cancel order', `/orders/${o.id}/cancel`, 'Order cancelled. The painting is back on sale.',
        { cls: 'danger', confirm: 'Cancel this order? The painting goes back on sale.', yes: 'Yes, cancel order' }) : '';
  return `<article class="row has-thumb">
    <div class="thumb">${o.image_url ? `<img src="${esc(imgSrc(o.image_url))}" alt="" onerror="this.remove()">` : ''}</div>
    <div><h3 class="row-title">${esc(o.painting_title)}</h3>
      <p class="row-meta">${o.artist ? esc(o.artist) + ' · ' : ''}${inr(o.price)} · placed ${esc(longDate(o.created_at.slice(0, 10)))}${isStudio() ? ' · ' + esc(o.customer_email) : ''}</p></div>
    <div class="row-side">${statusTag(o.status)}${cancel}</div></article>`;
}

function tabOrders() {
  $('#view').innerHTML = pageHead('Orders', isStudio() ? 'Every order placed with the studio.' : 'Cancel an order and the painting goes back on sale.') + '<div id="list"></div>';
  reloadList = () => showList($('#list'), () => api('/orders'), rows => `<div class="rows">${rows.map(orderRow).join('')}</div>`,
    isStudio() ? 'No orders yet.' : 'No orders yet. Choose a painting from the Paintings page.');
  reloadList();
}

// Loading -> (empty | error | data) for any list.
async function showList(el, loader, drawAll, emptyText) {
  if (!el) return;
  el.innerHTML = '<p class="state eyebrow">Loading…</p>';
  try {
    const data = await loader();
    el.innerHTML = data.length ? drawAll(data) : `<p class="state">${esc(emptyText)}</p>`;
  } catch (e) { el.innerHTML = errorState(e); }
}

// ---------- wall painting bookings ----------
function bookingRow(b) {
  const d = parseDay(b.date);
  const actions = isStudio()
    ? (b.status === 'requested'
        ? postBtn('Confirm', `/bookings/${b.id}/confirm`, 'Booking confirmed.', { cls: 'solid' })
          + postBtn('Decline', `/bookings/${b.id}/decline`, 'Booking declined.', { cls: 'danger', confirm: 'Decline this booking?', yes: 'Yes, decline' })
        : '')
    : (['requested', 'confirmed'].includes(b.status)
        ? postBtn('Cancel', `/bookings/${b.id}/cancel`, 'Booking cancelled.',
            { cls: 'danger', confirm: 'Cancel this booking? This is only allowed until 3 days before the date.', yes: 'Yes, cancel booking' })
        : '');
  return `<article class="row has-date">
    <div class="datebox"><span class="day">${d.getDate()}</span><span class="eyebrow">${esc(d.toLocaleDateString('en-IN', { month: 'short' }))} ${d.getFullYear()}</span></div>
    <div><h3 class="row-title">${b.wall_sqft} sq ft · ${inr(b.price)}</h3>
      <p class="row-meta">${esc(b.address)}${isStudio() ? ' · ' + esc(b.customer_email) : ''}</p></div>
    <div class="row-side">${statusTag(b.status)}<div class="actions">${actions}</div></div></article>`;
}

async function loadTaken() {
  const el = $('#taken');
  try {
    state.taken = await api('/booked-dates');
    if (el) el.textContent = state.taken.length ? state.taken.map(longDate).join(' · ') : 'No dates are booked yet.';
  } catch (_) {
    state.taken = [];
    if (el) el.textContent = "Couldn't load the booked dates. You can still try a date.";
  }
  syncDateCheck();
}

// Early warning in the form. The server's unique index is what really prevents a double booking.
function syncDateCheck() {
  const input = $('#f_date');
  if (input) input.setCustomValidity(state.taken.includes(input.value) ? 'That date is already booked. Please pick another.' : '');
}

function updateEstimate() {
  const n = Number($('#f_wall_sqft').value);
  const el = $('#estimate');
  const ok = Number.isInteger(n) && n >= 10 && n <= 500;
  el.hidden = !ok;
  if (ok) el.textContent = `${n} sq ft × ${inr(state.catalog.wall_rate_per_sqft)} = ${inr(n * state.catalog.wall_rate_per_sqft)}`;
}

function tabBookings() {
  const rate = state.catalog.wall_rate_per_sqft;
  const studio = isStudio();
  const side = studio ? '' : `<aside>
    <h2 class="side-title">Book a wall</h2>
    ${formHTML('booking', [
      { name: 'date', label: 'Date', type: 'date', min: addDays(7), max: addDays(90), required: true, hint: 'From 7 to 90 days away. One booking per date.' },
      { name: 'wall_sqft', label: 'Wall size (sq ft)', type: 'number', min: 10, max: 500, required: true, hint: '10 to 500 sq ft.' },
      { name: 'address', label: 'Address', type: 'textarea', required: true, maxlength: 300 },
    ], 'Request booking', '<p class="estimate" id="estimate" hidden></p>')}
    <div class="taken"><p class="eyebrow">Already booked</p><p class="taken-list" id="taken">Loading…</p></div></aside>`;
  $('#view').innerHTML = pageHead('Wall painting',
      studio ? 'Confirm or decline each request.' : `The studio paints your wall on the date you choose. ${inr(rate)} per sq ft.`) +
    (studio ? '<div id="list"></div>' : `<div class="split">${side}<section><div id="list"></div></section></div>`);
  reloadList = () => {
    showList($('#list'), () => api('/bookings'), rows => `<div class="rows">${rows.map(bookingRow).join('')}</div>`,
      studio ? 'No bookings yet.' : 'You have no bookings yet.');
    if (!studio) loadTaken();
  };
  reloadList();
}

// ---------- pottery ----------
const potteryFields = r => [
  { name: 'item_id', label: 'Item', type: 'select', value: r?.item_id, options: state.catalog.items.map(i => ({ value: i.id, label: i.name })) },
  { name: 'glaze_id', label: 'Glaze', type: 'select', value: r?.glaze_id, options: state.catalog.glazes.map(g => ({ value: g.id, label: g.name })) },
  { name: 'quantity', label: 'Quantity', type: 'number', value: r?.quantity, min: 1, max: 12, required: true, hint: '1 to 12.' },
  { name: 'needed_by', label: 'Needed by', type: 'date', value: r?.needed_by, min: addDays(14), required: true, hint: 'At least 14 days from today.' },
];

function potteryRow(r) {
  let actions = '';
  if (r.status === 'requested') {
    actions = isStudio()
      ? postBtn('Accept', `/pottery/${r.id}/accept`, 'Request accepted.', { cls: 'solid' })
        + postBtn('Decline', `/pottery/${r.id}/decline`, 'Request declined.', { cls: 'danger', confirm: 'Decline this request?', yes: 'Yes, decline' })
      : `<button class="btn" data-act="edit-pottery" data-id="${r.id}">Edit</button>`
        + postBtn('Cancel', `/pottery/${r.id}/cancel`, 'Request cancelled.', { cls: 'danger', confirm: 'Cancel this pottery request?', yes: 'Yes, cancel request' });
  }
  return `<article class="row has-date">
    <div class="datebox"><span class="day">${r.quantity}×</span><span class="eyebrow">Qty</span></div>
    <div><h3 class="row-title">${esc(r.item)} · ${esc(r.glaze)}</h3>
      <p class="row-meta">Needed by ${esc(longDate(r.needed_by))}${isStudio() ? ' · ' + esc(r.customer_email) : ''}</p></div>
    <div class="row-side">${statusTag(r.status)}<div class="actions">${actions}</div></div></article>`;
}

function tabPottery() {
  const studio = isStudio();
  const form = studio ? '' : `<aside><h2 class="side-title">Request pottery</h2>${formHTML('pottery', potteryFields(), 'Send request')}</aside>`;
  $('#view').innerHTML = pageHead('Pottery', studio ? 'Accept or decline each request.' : 'Made to order. Choose an item and a glaze, and tell us when you need it.') +
    (studio ? '<div id="list"></div>' : `<div class="split">${form}<section><div id="list"></div></section></div>`);
  reloadList = () => showList($('#list'), async () => (state.pottery = await api('/pottery')),
    rows => `<div class="rows">${rows.map(potteryRow).join('')}</div>`, studio ? 'No requests yet.' : 'You have no pottery requests yet.');
  reloadList();
}

// ---------- main render ----------
let renderToken = 0;
async function render() {
  const token = ++renderToken;
  renderChrome();
  const view = $('#view');
  view.className = state.me ? '' : 'landing';
  if (!state.me) { renderLanding(); return; }
  if (!state.catalog) {
    view.innerHTML = '<p class="state eyebrow">Loading…</p>';
    try { state.catalog = await api('/catalog'); }
    catch (e) { if (token === renderToken) view.innerHTML = errorState(e); return; }
    if (token !== renderToken) return;
  }
  ({ paintings: tabPaintings, orders: tabOrders, bookings: tabBookings, pottery: tabPottery })[state.tab]();
}

// ---------- what each click does ----------
const ACTIONS = {
  tab: el => { state.tab = el.dataset.tab; toast(''); render(); },
  'auth-mode': el => { state.authMode = el.dataset.mode; render(); },
  logout: async () => { await api('/logout', 'POST'); state.me = null; state.catalog = null; state.authMode = 'login'; toast(''); render(); },
  reload: () => (state.catalog ? reloadList() : render()),
  filter: el => { state.onlyAvailable = el.checked; drawPaintings(); },
  'close-dialog': el => el.closest('dialog').close(),
  'open-painting': el => openPainting(Number(el.dataset.id)),
  'add-painting': () => openPaintingForm(),
  'edit-painting': el => openPaintingForm(state.paintings.find(p => p.id === Number(el.dataset.id))),
  buy: el => mutate('/orders', 'POST', { painting_id: Number(el.dataset.id) }, 'Order placed. The painting is yours.'),
  post: el => mutate(el.dataset.path, 'POST', undefined, el.dataset.ok),
  'edit-pottery': el => {
    const r = state.pottery.find(x => x.id === Number(el.dataset.id));
    openForm({
      title: 'Edit request', submit: 'Save changes', fields: potteryFields(r),
      onSubmit: async d => { await api('/pottery/' + r.id, 'PUT', d); toast('Request updated.', true); },
    });
  },
};

document.addEventListener('click', async ev => {
  if (ev.target instanceof HTMLDialogElement) { ev.target.close(); return; }   // click on the backdrop
  const el = ev.target.closest('[data-act]');
  if (!el || !ACTIONS[el.dataset.act]) return;
  const dlg = el.closest('dialog');
  if (el.dataset.confirm && !(await ask(el.dataset.confirm, el.dataset.yes || 'Yes'))) return;
  if (dlg && el.dataset.act !== 'close-dialog') dlg.close();
  ACTIONS[el.dataset.act](el);
});

// ---------- what each form does ----------
async function authenticate(kind, data) {
  state.me = (await api('/' + kind, 'POST', data)).user;
  state.tab = 'paintings';
  state.catalog = null;
  toast(kind === 'login' ? 'Welcome back.' : 'Account created. Welcome.', true);
  await render();
}

const FORMS = {
  login: d => authenticate('login', d),
  signup: d => authenticate('signup', d),
  booking: async d => { await api('/bookings', 'POST', d); toast('Booking requested. The studio will confirm or decline it.', true); await render(); },
  pottery: async d => { await api('/pottery', 'POST', d); toast('Request sent. The studio will accept or decline it.', true); await render(); },
  dialog: async d => { await dialogCfg.onSubmit(d); $('#formDialog').close(); await render(); },
};

document.addEventListener('submit', async ev => {
  const form = ev.target.closest('form[data-form]');
  if (!form || !FORMS[form.dataset.form]) return;
  ev.preventDefault();
  const err = $('.form-error', form);
  const button = $('button[type=submit]', form);
  err.hidden = true;
  button.disabled = true;
  try { await FORMS[form.dataset.form](Object.fromEntries(new FormData(form))); }
  catch (e) { err.textContent = e.message; err.hidden = false; reloadList(); }   // show why, and refresh what changed
  finally { button.disabled = false; }
});

document.addEventListener('input', ev => {
  if (ev.target.id === 'f_date') syncDateCheck();
  if (ev.target.id === 'f_wall_sqft') updateEstimate();
});

// ---------- start ----------
(async () => {
  try { state.me = (await api('/me')).user; } catch (_) { state.me = null; }
  render();
})();
