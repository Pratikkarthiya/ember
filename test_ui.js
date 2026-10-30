// Browser-independent checks for the layout's state and rendering contracts.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

const menu = [{id:'coffee', name:'Coffee & cream', cat:'Coffee', desc:'Freshly brewed.',
  price:180, options:['Regular'], time:'5 MIN', tag:'HOUSE', veg:true, image:'photo-test'},
  {id:'toast', name:'Toast', cat:'Kitchen', desc:'Fresh toast.', price:250,
    options:['Classic'], time:'10 MIN', tag:'FRESH', veg:false, image:'photo-test'}];
const orders = [0,1,2,3].map(status => ({id:`EM-${status}`, status, table:status+1,
  time:Date.now(), total:180, method:'UPI', items:[{...menu[0],option:'Regular',qty:1}]}));

function context(script, role, responses) {
  const elements = new Map();
  function element(key) {
    if (!elements.has(key)) elements.set(key, {
      value:key==='#filter'?'active':'', innerHTML:'', textContent:'', hidden:false,
      disabled:false, open:false, checked:false,
      classList:{add(){},remove(){},toggle(){}}, style:{},
      setAttribute(){}, removeAttribute(){}, addEventListener(){}, focus(){},
      reset(){}, elements:{namedItem:field=>element(`${key}:${field}`)},
      showModal(){this.open=true;}, close(){this.open=false;}
    });
    return elements.get(key);
  }
  const views=['overview','menu','tables','orders','requests'].map(view=>({
    dataset:{view}, classList:{toggle(){}}, setAttribute(){}, removeAttribute(){}
  }));
  const sandbox = vm.createContext({
    document:{querySelector:element,querySelectorAll:()=>views,body:{dataset:{}},hidden:false},
    location:{pathname:`/${role}`,search:'?table=5',origin:'http://localhost:8000'},
    localStorage:{getItem:()=>null,setItem(){},removeItem(){}},
    fetch:async path=>({ok:true,json:async()=>structuredClone(responses[path])}),
    setInterval(){},setTimeout:fn=>fn(),clearTimeout(){},URLSearchParams,
    Date,console,window:{},crypto:{},matchMedia:()=>({matches:false})
  });
  vm.runInContext(fs.readFileSync(`static/${script}`,'utf8'),sandbox);
  return {sandbox,element,run:source=>vm.runInContext(source,sandbox)};
}
const ready = () => new Promise(resolve=>setImmediate(resolve));

test('customer menu groups entries by category and filters search and diet',async()=>{
  const ui=context('app.js','',{'/api/menu':menu,'/api/orders':[]});
  await ready();
  assert.match(ui.element('#menuGrid').innerHTML,/Coffee &amp; cream/);
  assert.equal((ui.element('#menuGrid').innerHTML.match(/class="menu-chapter"/g)||[]).length,2);
  ui.element('#veg').checked=true;ui.run('renderMenu()');
  assert.doesNotMatch(ui.element('#menuGrid').innerHTML,/>Toast</);
  ui.element('#search').value='not on the menu';ui.run('renderMenu()');
  assert.equal(ui.element('#empty').hidden,false);
});

test('order rail reflects selection, quantity, and total, then clears after removal',async()=>{
  const ui=context('app.js','',{'/api/menu':menu,'/api/orders':[]});
  await ready();
  assert.equal(ui.element('#reviewOrder').disabled,true);
  ui.run("cart=[{id:'coffee',name:'Coffee & cream',option:'Regular',qty:2,price:180}];updateCart()");
  assert.match(ui.element('#orderPreview').innerHTML,/Coffee &amp; cream/);
  assert.match(ui.element('#previewTotal').textContent,/360/);
  assert.equal(ui.element('#reviewOrder').disabled,false);
  ui.run('cart=[];updateCart()');
  assert.equal(ui.element('#reviewOrder').disabled,true);
  assert.equal(ui.element('#cartFloat').hidden,true);
});

test('admin navigation isolates workspaces and preserves editor drafts',async()=>{
  const ui=context('staff.js','admin',{
    '/api/admin/overview':{orders,requests:[],summary:{orders:4,total:720,active:3,served:1}},
    '/api/admin/settings':{menu,tables:[{number:5,label:'Table 5'}]}
  });
  await ready();
  assert.equal(ui.element('#workspaceNav').hidden,false);
  assert.equal(ui.element('#overviewPanel').hidden,false);
  assert.equal(ui.element('#management').hidden,true);
  assert.match(ui.element('#overviewRecent').innerHTML,/class="order-ledger"/);
  ui.run("workspaceView='menu';applyWorkspaceView()");
  assert.equal(ui.element('#menuPanel').hidden,false);
  assert.equal(ui.element('#tablePanel').hidden,true);
  ui.element('#itemForm:name').value='Unfinished edit';
  ui.run("workspaceView='tables';applyWorkspaceView()");
  assert.equal(ui.element('#tablePanel').hidden,false);
  assert.equal(ui.element('#menuPanel').hidden,true);
  ui.run("workspaceView='menu';applyWorkspaceView()");
  assert.equal(ui.element('#itemForm:name').value,'Unfinished edit');
  ui.run('loginView()');
  assert.equal(ui.element('#workspaceNav').hidden,true);
  assert.equal(ui.element('#dashboard').hidden,true);
});

test('kitchen board groups tickets into four stages and offers only valid next steps',async()=>{
  const ui=context('staff.js','kitchen',{'/api/kitchen/orders':{orders,requests:[]}});
  await ready();
  ui.element('#filter').value='all';ui.run('render()');
  const board=ui.element('#orders').innerHTML;
  assert.equal((board.match(/class="kitchen-lane"/g)||[]).length,4);
  assert.equal((board.match(/data-advance=/g)||[]).length,3);
  assert.match(board,/data-advance="EM-0" data-status="1"/);
  assert.match(board,/data-advance="EM-2" data-status="3"/);
  assert.doesNotMatch(board,/data-advance="EM-3"/);
  assert.equal(ui.element('#overviewPanel').hidden,true);
});
