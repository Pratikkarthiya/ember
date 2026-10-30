const $ = selector => document.querySelector(selector);
const role = location.pathname.replace(/\/$/, '') === '/admin' ? 'admin' : 'kitchen';
const isAdmin = role === 'admin';
const title = isAdmin ? 'Admin' : 'Kitchen';
const statuses = ['Paid', 'Preparing', 'Ready', 'Served'];
const money = value => '₹' + value.toLocaleString('en-IN');
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let snapshot = null, loading = false, generation = 0, settings = null, workspaceView = 'overview';
document.body.dataset.role = role;
document.title = `EMBER — ${title}`;
document.querySelector(`a[href="/${role}"]`).setAttribute('aria-current', 'page');
$('#moduleLabel').textContent = `${title.toUpperCase()} MODULE`;
$('#heading').textContent = isAdmin ? 'Cafe overview' : 'Kitchen orders';
$('#description').textContent = isAdmin ? 'Manage menu items, prices, and tables. Track demo sales and order activity.' : 'Prepare incoming paid orders and keep every table moving.';
$('#pinLabel').textContent = `${title} PIN`;
$('#filter').value = 'all';

async function api(path, data) {
  const response = await fetch(path, {credentials:'same-origin', method:data ? 'POST' : 'GET', headers:data ? {'Content-Type':'application/json'} : {}, body:data ? JSON.stringify(data) : undefined});
  const result = await response.json();
  if (!response.ok) { const error = new Error(result.error || 'Request failed.'); error.status = response.status; throw error; }
  return result;
}
function loginView() {
  snapshot = null;
  settings = null;
  $('#management').hidden = true;
  $('#workspaceNav').hidden = true;
  $('#itemForm').reset();
  $('#itemForm').elements.namedItem('id').readOnly = false;
  $('#saveItem').textContent = 'Add item';
  $('#itemMessage').textContent = $('#tableMessage').textContent = '';
  $('#tableForm').reset();
  $('#itemSelect').innerHTML = '';
  $('#tableList').innerHTML = '';
  $('#dashboard').hidden = true;
  $('#summary').innerHTML = $('#requests').innerHTML = $('#orders').innerHTML = '';
  $('#loginPanel').hidden = false;
  $('#logout').hidden = true;
}
function render() {
  const selected = $('#filter').value;
  const orders = snapshot.orders.filter(order => selected === 'all' || (selected === 'active' ? order.status < 3 : order.status === Number(selected)));
  $('#summary').innerHTML = isAdmin ? [
    ['Paid orders', snapshot.summary.orders], ['Demo sales · all time', money(snapshot.summary.total)],
    ['Active orders', snapshot.summary.active], ['Served orders', snapshot.summary.served]
  ].map(([label, value]) => `<div class="summary-card">${label}<strong>${value}</strong></div>`).join('') : '';
  $('#requests').innerHTML = snapshot.requests.length ? snapshot.requests.map(request => `<article class="order-card"><b>Table ${request.table_no}</b><p>Requested ${escape(new Date(request.created * 1000).toLocaleTimeString())}</p>${isAdmin ? '<span class="muted">Awaiting kitchen staff</span>' : `<button class="outline-button" data-resolve="${escape(request.id)}">Mark attended</button>`}</article>`).join('') : '<p>No outstanding waiter requests.</p>';
  const ticket = order => `<article class="order-card"><div class="topline"><h3>Table ${order.table}</h3><span class="order-status">${statuses[order.status]}</span></div><p class="muted">${escape(order.id)} &middot; ${escape(new Date(order.time).toLocaleTimeString())}</p><div class="ticket-items">${order.items.map(item=>`<p><b>${item.qty} &times; ${escape(item.name)}</b><br><span>${escape(item.option)}</span>${item.notes?'<br><em>'+escape(item.notes)+'</em>':''}</p>`).join('')}</div><div class="bill"><span>Demo paid</span><b>${money(order.total)}</b></div>${!isAdmin&&order.status<3?`<button class="primary btn" data-advance="${escape(order.id)}" data-status="${order.status+1}">Mark ${statuses[order.status+1].toLowerCase()} &rarr;</button>`:''}</article>`;
  if(isAdmin){
    const ledger = list => list.length?`<div class="ledger-scroll"><table class="order-ledger"><thead><tr><th>Order / time</th><th>Table</th><th>Selection</th><th>Status</th><th>Total</th></tr></thead><tbody>${list.map(order=>`<tr><td><strong>${escape(order.id)}</strong><small>${escape(new Date(order.time).toLocaleString())}</small></td><td>${order.table}</td><td>${order.items.map(item=>`${item.qty} &times; ${escape(item.name)}`).join('<br>')}</td><td><span class="order-status">${statuses[order.status]}</span></td><td>${money(order.total)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">No orders in this view.</p>';
    $('#orders').innerHTML=ledger(orders);
    $('#overviewRecent').innerHTML=ledger(snapshot.orders.slice(0,6));
  }else{
    $('#orders').innerHTML=statuses.map((status,index)=>{
      const lane=orders.filter(order=>order.status===index);
      return `<section class="kitchen-lane" data-stage="${index}"><div class="lane-heading"><h3>${status}</h3><span>${lane.length}</span></div><div class="lane-tickets">${lane.length?lane.map(ticket).join(''):'<div class="lane-empty">All clear here.</div>'}</div></section>`;
    }).join('');
  }
  applyWorkspaceView();
}
async function refresh() {
  if (loading) return;
  loading = true;
  const current = generation;
  try {
    const result = await api(isAdmin ? '/api/admin/overview' : '/api/kitchen/orders');
    if (current !== generation) return;
    if (isAdmin && !settings) await loadSettings();
    if (current !== generation) return;
    snapshot = result;
    $('#loginPanel').hidden = true;
    $('#workspaceNav').hidden = !isAdmin;
    $('#dashboard').hidden = false;
    $('#logout').hidden = false;
    $('#message').textContent = '';
    render();
    $('#updated').textContent = 'Updated ' + new Date().toLocaleTimeString();
  } catch (error) {
    if (current !== generation) return;
    if (error.status === 401) loginView();
    $('#message').textContent = error.status === 401 ? `Sign in with your ${role} PIN.` : error.message + ' Retrying in five seconds.';
  } finally { loading = false; }
}
$('#loginForm').onsubmit = async event => {
  event.preventDefault();
  $('#loginButton').disabled = true;
  try { await api(`/api/${role}/login`, {pin:$('#pin').value}); $('#pin').value = ''; await refresh(); }
  catch (error) { $('#message').textContent = error.message; }
  finally { $('#loginButton').disabled = false; }
};
$('#logout').onclick = async () => {
  $('#logout').disabled = true;
  try { await api(`/api/${role}/logout`, {}); generation++; loginView(); $('#message').textContent = 'Signed out.'; }
  catch (error) { $('#message').textContent = error.message; }
  finally { $('#logout').disabled = false; }
};
$('#refresh').onclick = refresh;
$('#filter').onchange = () => { if (snapshot) render(); };
$('#dashboard').onclick = async event => {
  const button = event.target.closest('[data-advance], [data-resolve]');
  if (!button || isAdmin) return;
  button.disabled = true;
  try {
    if (button.dataset.advance) await api('/api/kitchen/status', {id:button.dataset.advance, status:Number(button.dataset.status)});
    else await api('/api/kitchen/resolve', {id:button.dataset.resolve});
    await refresh();
  } catch (error) {
    if (error.status === 401) loginView();
    $('#message').textContent = error.message;
  } finally { button.disabled = false; }
};
async function loadSettings(selected = '') {
  settings = await api('/api/admin/settings');
  $('#management').hidden = false;
  $('#itemSelect').innerHTML = '<option value="">Add a new item</option>' + settings.menu.map(item => `<option value="${escape(item.id)}">${escape(item.name)} — ${money(item.price)}</option>`).join('');
  $('#categoryList').innerHTML = [...new Set(settings.menu.map(item => item.cat))].map(cat => `<option value="${escape(cat)}"></option>`).join('');
  $('#tableList').innerHTML = settings.tables.map(table => {
    const url = `${location.origin}/?table=${table.number}`;
    return `<div class="table-entry"><b>${escape(table.label)} · #${table.number}</b><a href="${escape(url)}" target="_blank" rel="noopener">Open menu ↗</a><label class="field">Ordering link<input readonly aria-label="Ordering link for table ${table.number}" value="${escape(url)}"></label></div>`;
  }).join('');
  $('#itemSelect').value = selected;
  applyWorkspaceView();
}
function editItem() {
  const form = $('#itemForm');
  form.reset();
  const item = settings?.menu.find(item => item.id === $('#itemSelect').value);
  form.elements.namedItem('id').readOnly = Boolean(item);
  if (item) {
    for (const key of ['id', 'name', 'price', 'cat', 'tag', 'time', 'desc', 'image']) form.elements.namedItem(key).value = item[key];
    form.elements.namedItem('veg').checked = item.veg;
    form.elements.namedItem('options').value = item.options.join('\n');
  }
  $('#saveItem').textContent = item ? 'Save changes' : 'Add item';
  $('#itemMessage').textContent = '';
}
$('#itemSelect').onchange = editItem;
$('#itemForm').onsubmit = async event => {
  event.preventDefault();
  if (!isAdmin) return;
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  data.price = Number(data.price);
  data.veg = form.elements.namedItem('veg').checked;
  data.options = data.options.split('\n').map(option => option.trim()).filter(Boolean);
  const editing = Boolean($('#itemSelect').value);
  $('#saveItem').disabled = true;
  try {
    await api(`/api/admin/items/${editing ? 'update' : 'add'}`, data);
    await loadSettings(data.id);
    editItem();
    $('#itemMessage').textContent = 'Saved. Customers see this item and price when they refresh the menu.';
  } catch (error) {
    if (error.status === 401) loginView();
    $('#itemMessage').textContent = error.message;
    $('#message').textContent = error.message;
  } finally { $('#saveItem').disabled = false; }
};
$('#tableForm').onsubmit = async event => {
  event.preventDefault();
  if (!isAdmin) return;
  const form = event.currentTarget;
  const data = {number:Number(form.elements.namedItem('number').value)};
  const label = form.elements.namedItem('label').value.trim();
  if (label) data.label = label;
  $('#saveTable').disabled = true;
  try {
    await api('/api/admin/tables/add', data);
    await loadSettings($('#itemSelect').value);
    form.reset();
    $('#tableMessage').textContent = `Table ${data.number} added. Its ordering link is below.`;
  } catch (error) {
    if (error.status === 401) loginView();
    $('#tableMessage').textContent = error.message;
    $('#message').textContent = error.message;
  } finally { $('#saveTable').disabled = false; }
};
function applyWorkspaceView(){
  if(!isAdmin){
    $('#overviewPanel').hidden=true;
    $('#management').hidden=true;
    $('#requestsPanel').hidden=false;
    $('#ordersPanel').hidden=false;
    return;
  }
  $('#overviewPanel').hidden=workspaceView!=='overview';
  const workspaceTitles={overview:'Cafe overview',menu:'Menu & prices',tables:'Tables & links',orders:'Order history',requests:'Waiter requests'};
  $('#heading').textContent=workspaceTitles[workspaceView];
  $('#management').hidden=!['menu','tables'].includes(workspaceView);
  $('#menuPanel').hidden=workspaceView!=='menu';
  $('#tablePanel').hidden=workspaceView!=='tables';
  $('#managementHeading').textContent=workspaceView==='tables'?'Tables & ordering links':'Menu & prices';
  $('#ordersPanel').hidden=workspaceView!=='orders';
  $('#requestsPanel').hidden=workspaceView!=='requests';
  document.querySelectorAll('[data-view]').forEach(button=>{
    const active=button.dataset.view===workspaceView;
    button.classList.toggle('active',active);
    if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
  });
}
$('#workspaceNav').onclick=event=>{
  const button=event.target.closest('[data-view]');
  if(!button||!isAdmin)return;
  workspaceView=button.dataset.view;applyWorkspaceView();
};
setInterval(() => { if (snapshot && !document.hidden) refresh(); }, 5000);
refresh();
