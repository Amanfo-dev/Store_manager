// Theme: "system" follows the device; light/dark are remembered.
const themeSelect = document.getElementById('theme');
const saved = localStorage.getItem('theme');
themeSelect.value = saved === 'light' || saved === 'dark' ? saved : 'system';
themeSelect.addEventListener('change', () => {
  const v = themeSelect.value, root = document.documentElement;
  if (v === 'system') { localStorage.removeItem('theme'); delete root.dataset.theme; }
  else { localStorage.setItem('theme', v); root.dataset.theme = v; }
});

// Dialogs: buttons with data-open fill the form, then open it.
document.querySelectorAll('[data-open]').forEach(btn => btn.addEventListener('click', () => {
  const dlg = document.getElementById(btn.dataset.open), form = dlg.querySelector('form');
  const d = btn.dataset;
  if (form.dataset.action) form.action = form.dataset.action.replace('{id}', d.id);
  for (const [k, v] of Object.entries({ item_id: d.id, name: d.name, price: d.price, stock: d.stock })) {
    const f = form.elements[k]; if (f && v !== undefined) f.value = v;
  }
  const qty = form.elements.quantity;
  if (qty && d.stock) { qty.max = d.stock; qty.value = 1; }
  dlg.dataset.item = JSON.stringify({ id: d.id, name: d.name, price: +d.price, stock: +d.stock });
  dlg.querySelectorAll('[data-fill=name]').forEach(el => el.textContent = d.name || '');
  dlg.showModal();
}));

// Confirm before deleting.
document.querySelectorAll('form[data-confirm]').forEach(f =>
  f.addEventListener('submit', e => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));

document.querySelectorAll('[data-close]').forEach(b =>
  b.addEventListener('click', () => b.closest('dialog').close()));

// Cart (Home page only). Kept in localStorage; the server re-checks prices and stock at checkout.
const fab = document.getElementById('cart-fab');
if (fab) {
  const cur = fab.dataset.currency;
  let cart = {};
  try { cart = JSON.parse(localStorage.getItem('cart') || '{}'); } catch (e) {}
  const $ = id => document.getElementById(id);
  const dlg = $('dlg-cart'), lines = $('cart-lines'), sumEl = $('cart-sum'), countEl = $('cart-count');
  const msg = $('cart-msg'), checkout = $('cart-checkout');
  const fmt = n => n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function save() { localStorage.setItem('cart', JSON.stringify(cart)); render(); }
  function render() {
    const ids = Object.keys(cart);
    let sum = 0, count = 0;
    lines.innerHTML = ids.length ? '' : '<p class="mute">Your cart is empty.</p>';
    ids.forEach(id => {
      const c = cart[id];
      sum += c.price * c.qty; count += c.qty;
      const row = document.createElement('div');
      row.className = 'cart-line';
      row.innerHTML = '<span class="cl-name"></span><input type="number" min="1" aria-label="Quantity"><b></b><button type="button" class="btn small danger">Remove</button>';
      row.querySelector('.cl-name').textContent = c.name;
      const qty = row.querySelector('input');
      qty.value = c.qty; qty.max = c.stock;
      row.querySelector('b').textContent = cur + ' ' + fmt(c.price * c.qty);
      qty.addEventListener('change', () => { c.qty = Math.max(1, Math.min(parseInt(qty.value) || 1, c.stock)); save(); });
      row.querySelector('button').addEventListener('click', () => { delete cart[id]; save(); });
      lines.appendChild(row);
    });
    sumEl.textContent = cur + ' ' + fmt(sum);
    countEl.textContent = count; countEl.hidden = !count;
    checkout.disabled = !ids.length;
  }

  document.querySelector('#dlg-add form').addEventListener('submit', e => {
    e.preventDefault();
    const dlgAdd = $('dlg-add'), item = JSON.parse(dlgAdd.dataset.item);
    const want = parseInt(e.target.elements.quantity.value) || 1;
    const have = cart[item.id] ? cart[item.id].qty : 0;
    const total = Math.min(have + want, item.stock);
    if (have + want > item.stock) alert('Only ' + item.stock + ' of ' + item.name + ' in stock, so the cart now holds all of them.');
    cart[item.id] = { name: item.name, price: item.price, stock: item.stock, qty: total };
    save(); dlgAdd.close();
  });
  fab.addEventListener('click', () => { msg.hidden = true; dlg.showModal(); });
  $('cart-close').addEventListener('click', () => dlg.close());
  checkout.addEventListener('click', async () => {
    checkout.disabled = true;
    try {
      const r = await fetch(fab.dataset.checkout, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: Object.entries(cart).map(([id, c]) => ({ id: +id, qty: c.qty })) }),
      });
      const data = await r.json();
      if (r.ok) { cart = {}; localStorage.removeItem('cart'); location.reload(); return; }
      msg.textContent = data.error || 'Checkout failed.';
    } catch (e) { msg.textContent = 'Could not reach the server.'; }
    msg.hidden = false; checkout.disabled = false;
  });
  render();
}

// A slow free server makes people click twice. Disable a form's buttons once it is sent.
// Forms handled by JavaScript (like the add-to-cart pop-up) call preventDefault and are skipped.
document.addEventListener("submit", e => {
  if (e.defaultPrevented) return;
  const buttons = e.target.querySelectorAll("button:not([type=button])");
  setTimeout(() => buttons.forEach(b => { b.disabled = true; }), 0);
});
// Coming back with the Back button should not leave buttons stuck.
window.addEventListener("pageshow", () => document.querySelectorAll("form button:disabled").forEach(b => { b.disabled = false; }));
