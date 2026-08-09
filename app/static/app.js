'use strict';

const state = {user:null, drivers:[], vehicles:[], users:[], logs:[], products:[], queue:[], searchRows:[], invoiceSequence:{start:null,max:null,missing:[],configured:false}, permissions:{screens:[],actions:[]}, permissionCatalog:{}, invoiceSequence:{start:null,max:null,missing:[],configured:false}, current:null};

const INACTIVITY_LIMIT_MS = 10 * 60 * 1000;
let inactivityTimer = null;
let lastActivityAt = Date.now();

function resetInactivityTimer() {
  lastActivityAt = Date.now();
  clearTimeout(inactivityTimer);
  if (!state.user) return;
  inactivityTimer = setTimeout(forceIdleLogout, INACTIVITY_LIMIT_MS);
}

async function forceIdleLogout() {
  try { await fetch('/api/logout', {method:'POST'}); } catch (_) {}
  clearTimeout(inactivityTimer);
  state.user = null;
  document.getElementById('appView')?.classList.add('hidden');
  document.getElementById('loginView')?.classList.remove('hidden');
  const form = document.getElementById('loginForm');
  if (form) form.reset();
  toast('انتهت الجلسة بسبب عدم الاستخدام لمدة 10 دقائق. سجل الدخول من جديد.', true);
}

function setupInactivityWatch() {
  ['click','keydown','input','touchstart','mousemove','scroll'].forEach(eventName => {
    document.addEventListener(eventName, () => {
      if (state.user) resetInactivityTimer();
    }, {passive:true});
  });
  document.addEventListener('visibilitychange', () => {
    if (!state.user) return;
    if (!document.hidden && Date.now() - lastActivityAt >= INACTIVITY_LIMIT_MS) {
      forceIdleLogout();
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  setupInactivityWatch();
  bind('loginForm','submit',login);
  bind('logoutBtn','click',logout);
  bind('refreshBtn','click',bootstrap);
  bind('newInvoiceBtn','click',showNewInvoice);
  bind('newUserBtn','click',showNewUser);
  bind('newVehicleBtn','click',showNewVehicle);
  bind('newProductBtn','click',showNewProduct);
  bind('saveSequenceStartBtn','click',saveInvoiceSequenceStart);
  bind('searchBtn','click',search);
  bind('closeModalBtn','click',closeModal);

  ['queueFilter','queueSort','queueSortDirection'].forEach(id=>bind(id, id==='queueFilter'?'input':'change', renderFilteredQueue));
  ['usersFilter','usersRoleFilter','usersStatusFilter','usersSort'].forEach(id=>bind(id, id==='usersFilter'?'input':'change', renderFilteredUsers));
  ['vehiclesFilter','vehiclesStatusFilter','vehiclesSort'].forEach(id=>bind(id, id==='vehiclesFilter'?'input':'change', renderFilteredVehicles));
  ['productsFilter','productsStatusFilter','productsSort'].forEach(id=>bind(id, id==='productsFilter'?'input':'change', renderFilteredProducts));
  ['logsFilter','logsSort'].forEach(id=>bind(id, id==='logsFilter'?'input':'change', renderFilteredLogs));
  ['searchStatusFilter','searchSort','searchSortDirection'].forEach(id=>bind(id,'change', renderFilteredSearch));
  document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
  bootstrap();
  setTimeout(bindLiveFilterControls,0);
});

function bind(id, event, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(event, handler);
}

async function api(url, options={}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({detail:'حدث خطأ'}));
  if (!response.ok) {
    if (response.status === 401 && state.user) {
      clearTimeout(inactivityTimer);
      state.user = null;
      document.getElementById('appView')?.classList.add('hidden');
      document.getElementById('loginView')?.classList.remove('hidden');
    }
    let message = 'حدث خطأ';
    if (typeof data?.detail === 'string') {
      message = data.detail;
    } else if (Array.isArray(data?.detail)) {
      message = data.detail.map(x => x?.msg || x?.message || JSON.stringify(x)).join(' — ');
    } else if (data?.detail && typeof data.detail === 'object') {
      message = data.detail.msg || data.detail.message || JSON.stringify(data.detail);
    }
    throw new Error(message);
  }
  return data;
}

async function login(event) {
  event.preventDefault();
  try {
    await api('/api/login', {method:'POST', body:new FormData(event.target)});
    await bootstrap();
  } catch (error) {
    toast(error.message, true);
  }
}

async function logout() {
  clearTimeout(inactivityTimer);
  await api('/api/logout', {method:'POST'});
  location.reload();
}

async function bootstrap() {
  try {
    const data = await api('/api/bootstrap');
    state.user = data.user;
    resetInactivityTimer();
    state.drivers = data.drivers;
    state.vehicles = data.vehicles;
    state.users = data.users;
    state.logs = data.logs || [];
    state.queue = data.queue || [];
    state.products = data.products || [];
    state.permissions = data.permissions || {screens:[],actions:[]};
    state.permissionCatalog = data.permission_catalog || {};
    state.invoiceSequence = data.invoice_sequence || {start:null,max:null,missing:[],configured:false};

    document.getElementById('loginView').classList.add('hidden');
    document.getElementById('appView').classList.remove('hidden');
    document.getElementById('userLabel').textContent = `${state.user.name} — ${roleName(state.user.role)}`;
    renderInvoiceSequence();
    document.getElementById('newInvoiceBtn').classList.toggle('hidden', !state.permissions.actions.includes('invoice_create'));
    document.getElementById('usersTab').classList.toggle('hidden', !state.permissions.screens.includes('users'));
    document.getElementById('vehiclesTab').classList.toggle('hidden', !state.permissions.screens.includes('vehicles'));
    document.getElementById('productsTab').classList.toggle('hidden', !state.permissions.screens.includes('products'));
    document.getElementById('logsTab').classList.toggle('hidden', state.user.role !== 'ADMIN');

    renderStats(data.stats);
    renderFilteredQueue();
    renderFilteredUsers();
    renderFilteredVehicles();
    renderFilteredLogs();
    renderFilteredProducts();
    bindLiveFilterControls();
  } catch (error) {
    if (!error.message.includes('الجلسة')) console.error(error);
  }
}

function renderStats(stats) {
  const cards = [
    ['المعلقة عندي', stats.my_pending],
    ['المخزن', stats.warehouse_pending],
    ['السائقين', stats.driver_pending],
    ['المرتجعات', stats.returns_pending],
    ['المستندات', stats.documents_pending],
    ['المكتملة', stats.closed],
  ];
  document.getElementById('stats').innerHTML =
    cards.map((x,idx) => {
      const buckets=['mine','warehouse','drivers','returns','documents','closed'];
      return `<div class="card stat clickable-stat" data-bucket="${buckets[idx]}">${x[0]}<b>${x[1]}</b></div>`;
    }).join('');
  document.querySelectorAll('.clickable-stat').forEach(el => el.addEventListener('click', () => showDashboardBucket(el.dataset.bucket, el.firstChild.textContent)));
}

function renderQueue(rows) {
  const body = document.getElementById('queueBody');
  if (!body) return;
  body.innerHTML = rows.length ? rows.map(i => `<tr>
    <td data-label="الفاتورة"><b>${esc(i.invoice_no)}</b></td>
    <td data-label="العميل">${esc(i.customer || '')}</td>
    <td data-label="السائق">${esc(i.driver_name || 'لم يحدد')}</td>
    <td data-label="الحالة">${statusName(i.status)}</td>
    <td data-label="تاريخ الفاتورة">${dateOnlyText(i.invoice_date)}</td>
    <td data-label="تاريخ التحميل">${i.loaded_at ? dateTimeText(i.loaded_at) : ''}</td>
    <td data-label=""><button class="open" data-no="${attr(i.invoice_no)}">فتح</button></td>
  </tr>`).join('') : '<tr><td colspan="7">لا توجد فواتير معلقة.</td></tr>';
  body.querySelectorAll('.open').forEach(btn => btn.addEventListener('click', () => openInvoice(btn.dataset.no)));
}

function rowHtml(invoice) {
  return `<tr>
    <td><b>${esc(invoice.invoice_no)}</b></td>
    <td>${esc(invoice.customer || '')}</td>
    <td>${esc(invoice.driver_name || 'لم يحدد')}</td>
    <td>${statusName(invoice.status)}</td>
    <td><button class="open" data-no="${attr(invoice.invoice_no)}">فتح</button></td>
  </tr>`;
}

async function openInvoice(invoiceNo) {
  try {
    state.current = await api('/api/invoices/' + encodeURIComponent(invoiceNo));
    showInvoice(state.current);
  } catch (error) {
    toast(error.message, true);
  }
}

async function showInvoice(invoice) {
  document.getElementById('modalTitle').textContent = 'فاتورة ' + invoice.invoice_no;
  let invoiceIssues=[];
  try { invoiceIssues=await api(`/api/invoices/${encodeURIComponent(invoice.invoice_no)}/issues`); } catch(e) {}
  let html = `<div class="card">
    <b>السائق:</b> ${esc(invoice.driver_name || 'لم يحدد')}<br>
    <b>السيارة:</b> ${esc(invoice.vehicle_no || 'لم تحدد')}<br>
    <b>الحالة:</b> ${statusName(invoice.status)}
  </div>`;

  if (invoice.receipt_photo) {
    html += `<div class="receipt-photo-wrap">
      <a href="${attr(invoice.receipt_photo)}" target="_blank" rel="noopener">
        <img class="receipt-photo" src="${attr(invoice.receipt_photo)}" alt="صورة الاستلام">
      </a>
    </div>`;
  }

  if (['ADMIN','WAREHOUSE'].includes(state.user.role) && invoice.status === 'WAREHOUSE_PENDING') {
    html += warehouseForm();
  } else if (['ADMIN','WAREHOUSE'].includes(state.user.role) && invoice.status === 'RETURN_PENDING') {
    html += returnForm(invoice, invoiceIssues);
  } else if (['ADMIN','DRIVER'].includes(state.user.role) && ['DRIVER_PENDING','POSTPONED'].includes(invoice.status)) {
    html += driverForm();
  } else if (['ADMIN','HR'].includes(state.user.role) && invoice.status === 'DOCUMENT_PENDING' && invoice.delivery_mode === 'EXTERNAL_DRIVER' && !invoice.receipt_photo) {
    html += externalDriverForm();
  } else if (['ADMIN','SALES_ACCOUNTANT'].includes(state.user.role) && invoice.sales_return_required && !invoice.sales_return_reviewed && ['FINAL_REVIEW_PENDING','DOCUMENT_PENDING'].includes(invoice.status)) {
    html += salesReturnReviewForm(invoice);
  } else if (['ADMIN','HR'].includes(state.user.role) && !invoice.original_document_received && ['DOCUMENT_PENDING','FINAL_REVIEW_PENDING'].includes(invoice.status)) {
    html += closeForm(invoice);
  } else {
    html += finalReviewSummary(invoice);
  }

  html += '<hr><h3>التعديل</h3>';
  if (state.user.role === 'ADMIN') {
    html += `<button id="adminEditInvoiceBtn" class="warn">تعديل شامل</button>
             <button id="deleteInvoiceBtn" class="danger">حذف الفاتورة</button>`;
  } else if (state.user.role === 'HR' && invoice.status === 'WAREHOUSE_PENDING') {
    html += `<button id="editHrBtn" class="warn">تعديل بيانات الموارد</button>`;
  } else if (state.user.role === 'WAREHOUSE' && ['WAREHOUSE_PENDING','DRIVER_PENDING'].includes(invoice.status)) {
    html += `<button id="editWarehouseBtn" class="warn">تعديل بيانات المخزن</button>`;
  } else if (state.user.role === 'DRIVER' && ['DRIVER_PENDING','POSTPONED','RETURN_PENDING','DOCUMENT_PENDING'].includes(invoice.status)) {
    html += `<button id="editDriverBtn" class="warn">تعديل نتيجة التسليم</button>`;
  }

  document.getElementById('modalContent').innerHTML = html;
  openModal();
  bindModalForms();
  bindEditButtons();
}

function warehouseForm() {
  const companyDrivers = state.drivers.filter(d=>!d.is_external_driver).map(d=>`<option value="${attr(d.driver_code)}">${esc(d.name)}</option>`).join('');
  const externalDrivers = state.drivers.filter(d=>d.is_external_driver).map(d=>`<option value="${attr(d.driver_code)}">${esc(d.name)}</option>`).join('');
  const vehicleOptions = state.vehicles.map(v=>`<option value="${v.id}">${esc(v.name)} — ${esc(v.plate_no)}</option>`).join('');
  return `<form id="warehouseForm">
    <label>طريقة التوصيل / الاستلام</label>
    <select id="deliveryMode" name="delivery_mode" required>
      <option value="COMPANY_DRIVER">سائق من الشركة</option>
      <option value="EXTERNAL_DRIVER">سائق خارجي</option>
      <option value="CUSTOMER_SELF">العميل نفسه يستلم</option>
    </select>
    <div id="companyDriverField"><label>سائق الشركة</label><select id="companyDriverSelect"><option value="">اختر</option>${companyDrivers}</select></div>
    <div id="externalDriverField" class="hidden"><label>السائق الخارجي</label><select id="externalDriverSelect"><option value="">اختر</option>${externalDrivers}</select></div>
    <input type="hidden" name="driver_code" id="warehouseDriverCode">
    <div id="vehicleField"><label>الدينة / السيارة</label><select name="vehicle_id"><option value="">اختر</option>${vehicleOptions}</select></div>
    <div id="customerReceiptField" class="hidden"><label>صورة الاستلام من العميل (إجباري)</label><input name="receipt_photo" type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif,.avif"></div>
    <label>حالة التحميل</label><select id="loadStatus" name="load_status"><option>تم التحميل كامل</option><option>تم التحميل ناقص</option><option>مرفوض من المخزن</option></select>
    <label>تاريخ ووقت التحميل</label><input name="loaded_at" type="datetime-local" required value="${localDateTimeValue()}">
    <div id="warehouseIssues" class="hidden"><h3>الأصناف الناقصة / المرتجعة</h3><div id="warehouseIssueRows"></div><button type="button" class="secondary" id="addWarehouseIssue">+ إضافة صنف</button></div>
    <label>سبب النقص أو الرفض</label><input name="shortage_reason">
    <label>صورة التحميل (اختياري)</label><input type="file" name="photo" accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif,.avif">
    <label>ملاحظات</label><textarea name="notes"></textarea>
    <input type="hidden" name="issues_json" value="[]"><button>اعتماد</button>
  </form>`;
}

function driverForm() {
  return `<form id="driverForm">
    <label>نتيجة التسليم</label>
    <select name="delivery_result">
      <option>تم كامل</option>
      <option>تم جزئي</option>
      <option>رفض كامل</option>
      <option>مؤجل</option>
      <option>العميل مغلق</option>
    </select>
    <label>وصف كمية المرتجع</label><input name="return_qty_declared" type="text" placeholder="مثال: ٢٠ تنك مرتجع">\n    <div id="driverIssues"><h3>تفاصيل أصناف المرتجع</h3><div id="driverIssueRows"></div><button type="button" class="secondary" id="addDriverIssue">+ إضافة صنف مرتجع</button></div>\n    <input type="hidden" name="issues_json" value="[]">
    <label>السبب</label><input name="reason">
    <label>صورة الاستلام</label><input id="driverReceiptPhoto" name="receipt_photo" type="file" accept="image/*" required>
    <label>صورة المرتجع</label><input name="return_photo" type="file" accept="image/*">
    <label>ملاحظات</label><textarea name="notes"></textarea>
    <button id="driverSubmitBtn" disabled>اعتماد</button>
  </form>`;
}


function externalDriverForm() {
  return `<form id="externalDriverForm">
    <div class="card"><b>السائق الخارجي:</b> الموارد تسجل نتيجة التسليم وترفع صورة الاستلام المرسلة من السائق.</div>
    <label>نتيجة التسليم</label><select name="delivery_result"><option>تم كامل</option><option>تم جزئي</option><option>رفض كامل</option><option>مؤجل</option><option>العميل مغلق</option></select>
    <label>وصف كمية المرتجع</label><input name="return_qty_declared" type="text" placeholder="مثال: ٢٠ تنك مرتجع">
    <input type="hidden" name="issues_json" value="[]">
    <label>السبب</label><input name="reason">
    <label>صورة الاستلام (إجباري)</label><input name="receipt_photo" type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif,.avif" required>
    <label>صورة المرتجع (اختياري)</label><input name="return_photo" type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif,.avif">
    <label>ملاحظات</label><textarea name="notes"></textarea><button>اعتماد نتيجة السائق الخارجي</button>
  </form>`;
}

function returnForm(invoice, allIssues=[]) {
  const items=allIssues.filter(x=>x.stage==='DRIVER' && x.issue_type==='مرتجع');
  const rows=items.length ? items.map(x=>`
    <div class="return-check-row" data-id="${x.id}">
      <div class="return-item-title"><b>${esc(x.product_name)}</b> — ${esc(x.quantity)} ${esc(x.unit||'')}</div>
      <label>هل الكمية المستلمة مطابقة لما سجله السائق؟</label>
      <select class="return-match" required>
        <option value="">اختر</option>
        <option value="yes">نعم، مطابق</option>
        <option value="no">لا، يوجد اختلاف</option>
      </select>
      <div class="return-actual hidden">
        <label>الكمية المستلمة فعليًا</label>
        <input class="return-actual-qty" type="text" placeholder="اكتب الكمية الفعلية بنفس الوحدة">
        <label>ملاحظة الاختلاف (اختياري)</label>
        <input class="return-item-note" type="text">
      </div>
    </div>`).join('') :
    '<div class="card">لا توجد أصناف مرتجع مسجلة من السائق. لا يمكن اعتماد المرتجع حتى يسجل السائق الأصناف.</div>';

  return `<form id="returnForm">
    <div class="card"><b>مطابقة مرتجع السائق</b><br>راجع كل صنف والكمية التي سجلها السائق، ثم أكد المطابقة أو اكتب الكمية الفعلية.</div>
    <div id="returnCheckItems">${rows}</div>
    <input type="hidden" name="issue_results_json" value="[]">
    <label>صورة المرتجع (اختياري)</label>
    <input name="photo" type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.bmp,.tif,.tiff,.heic,.heif,.avif">
    <label>ملاحظات المخزن</label><textarea name="notes"></textarea>
    <button ${items.length?'':'disabled'}>تأكيد استلام المرتجع</button>
  </form>`;
}

function closeForm(invoice) {
  const externalField = invoice.is_external_driver
    ? '<label>صورة الاستلام المرسلة من السائق الخارجي</label><input name="external_receipt" type="file" accept="image/*">'
    : '';
  return `<form id="closeForm">
    <label>استلام أصل الفاتورة</label>
    <select name="original_received"><option>نعم</option><option>لا</option></select>
    ${externalField}
    <label>ملاحظات</label><textarea name="notes"></textarea>
    <button class="success">تأكيد استلام أصل الفاتورة</button>
  </form>`;
}


function salesReturnReviewForm(invoice) {
  return `<form id="salesReturnReviewForm">
    <div class="card">
      <b>مراجعة مردود المبيعات</b><br>
      تأكد من تفاصيل المردود التي سجلها السائق وما استلمه المخزن، ثم اعتمد.
    </div>
    <label>ملاحظات محاسب المبيعات</label>
    <textarea name="notes"></textarea>
    <button class="success">اعتماد المردود</button>
  </form>`;
}

function finalReviewSummary(invoice) {
  const original = invoice.original_document_received ? '✓ تم استلام أصل الفاتورة' : '⏳ أصل الفاتورة لم يُستلم بعد';
  const sales = !invoice.sales_return_required ? 'لا يوجد مردود يحتاج اعتماد'
    : (invoice.sales_return_reviewed ? '✓ تم اعتماد المردود من محاسب المبيعات' : '⏳ المردود بانتظار محاسب المبيعات');
  return `<div class="card final-review-summary">
    <h3>حالة الإقفال</h3>
    <div>${original}</div>
    <div>${sales}</div>
    ${invoice.sales_return_notes ? `<div><b>ملاحظات المردود:</b> ${esc(invoice.sales_return_notes)}</div>` : ''}
  </div>`;
}

function bindModalForms() {
  document.querySelectorAll('.return-match').forEach(sel=>{
    sel.addEventListener('change',()=>{
      const row=sel.closest('.return-check-row');
      row?.querySelector('.return-actual')?.classList.toggle('hidden',sel.value!=='no');
    });
  });
  const forms = [
    ['warehouseForm', 'warehouse'],
    ['driverForm', 'driver'],
    ['externalDriverForm', 'external-delivery'],
    ['returnForm', 'return'],
    ['closeForm', 'close'],
    ['salesReturnReviewForm', 'sales-return-review'],
    ['invoiceForm', 'invoices'],
    ['userForm', 'users'],
    ['vehicleForm', 'vehicles'],
    ['editUserForm', 'edit-user'],
  ];

  forms.forEach(([id, path]) => {
    const form = document.getElementById(id);
    if (!form) return;

    if (id === 'warehouseForm') setupWarehouseForm(form);
    if (id === 'driverForm') {
      setupIssueEditor(form, 'driverIssueRows', 'addDriverIssue', false);
      const receiptInput = form.querySelector('[name="receipt_photo"]');
      const submitButton = form.querySelector('button[type="submit"], button:not([type])');
      const refreshDriverSubmit = () => {
        submitButton.disabled = !(receiptInput.files && receiptInput.files.length > 0);
      };
      receiptInput.addEventListener('change', () => {
        refreshDriverSubmit();
        const file = receiptInput.files && receiptInput.files[0];
        let hint = form.querySelector('.upload-size-hint');
        if (!hint) {
          hint = document.createElement('small');
          hint.className = 'upload-size-hint';
          receiptInput.insertAdjacentElement('afterend', hint);
        }
        hint.textContent = file ? `حجم الصورة قبل التحسين: ${(file.size/1024/1024).toFixed(1)} MB — سيتم تصغيرها تلقائياً قبل الرفع.` : '';
      });
      refreshDriverSubmit();
    }

    form.addEventListener('submit', async event => {
      event.preventDefault();
      try {
        serializeIssueRows(form);
        let url;
        if (id === 'invoiceForm') url = '/api/invoices';
        else if (id === 'userForm') url = '/api/users';
        else if (id === 'vehicleForm') url = '/api/vehicles';
        else if (id === 'editUserForm') url = '/api/users/' + encodeURIComponent(form.dataset.username);
        else url = `/api/invoices/${encodeURIComponent(state.current.invoice_no)}/${path}`;

        const hasImageUpload = ['driverForm','externalDriverForm','warehouseForm','returnForm','closeForm'].includes(id);
        if (hasImageUpload) setSubmitting(form, true, id === 'driverForm' ? 'جاري رفع الصورة والاعتماد...' : 'جاري الحفظ...');
        const body = hasImageUpload ? await optimizedFormData(form) : new FormData(form);
        await api(url, {method:'POST', body});
        closeModal();
        toast('تم الحفظ');
        // حدّث البيانات بعد إغلاق النافذة حتى يشعر المستخدم بالاستجابة فوراً.
        bootstrap();
      } catch (error) {
        setSubmitting(form, false);
        toast(error.message, true);
      }
    });
  });
}

function showNewInvoice() {
  document.getElementById('modalTitle').textContent = 'إدخال فاتورة';
  document.getElementById('modalContent').innerHTML = `<form id="invoiceForm">
    <label>رقم الفاتورة</label><input name="invoice_no" required>
    <label>اسم العميل (اختياري)</label><input name="customer">\n    <label>تاريخ الفاتورة</label><input name="invoice_date" type="date" required value="${new Date().toISOString().slice(0,10)}">
    <label>ملاحظات</label><textarea name="notes"></textarea>
    <button class="success">حفظ وإرسال للمخزن</button>
  </form>`;
  openModal();
  bindModalForms();
}

async function search() {
  try {
    const q = encodeURIComponent(document.getElementById('searchInput').value);
    const closed = document.getElementById('includeClosed').checked;
    state.searchRows = await api(`/api/invoices/search?q=${q}&include_closed=${closed}`);
    renderFilteredSearch();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderUsers(rows) {
  const body = document.getElementById('usersBody');
  body.innerHTML = rows.length
    ? rows.map(user => `<tr>
        <td data-label="المستخدم">${esc(user.username)}</td>
        <td data-label="الاسم">${esc(user.name)}</td>
        <td data-label="الدور">${roleName(user.role)}</td>
        <td data-label="رمز السائق">${esc(user.driver_code || '')}</td>
        <td data-label="الجوال">${esc(user.phone || '')}</td>
        <td data-label="الحالة">${user.active ? 'نشط' : 'موقوف'}</td>
        <td><button class="edit-user" data-user="${attr(user.username)}">تعديل</button>
            ${user.username !== 'admin' ? `<button class="perm-user secondary" data-user="${attr(user.username)}">صلاحيات</button>
            <button class="toggle-user warn" data-user="${attr(user.username)}">${user.active?'توقيف':'تفعيل'}</button>
            <button class="delete-user danger" data-user="${attr(user.username)}">حذف</button>` : ''}</td>
      </tr>`).join('')
    : '<tr><td colspan="7">لا يوجد مستخدمون.</td></tr>';

  body.querySelectorAll('.edit-user').forEach(btn => {
    btn.addEventListener('click', () => showEditUser(btn.dataset.user));
  });
  body.querySelectorAll('.perm-user').forEach(btn => {
    btn.addEventListener('click', () => showPermissions(btn.dataset.user));
  });
  body.querySelectorAll('.toggle-user').forEach(btn => {
    btn.addEventListener('click', () => toggleUser(btn.dataset.user));
  });
  body.querySelectorAll('.delete-user').forEach(btn => {
    btn.addEventListener('click', () => deleteUser(btn.dataset.user));
  });
}

function showNewUser() {
  document.getElementById('modalTitle').textContent = 'مستخدم جديد';
  document.getElementById('modalContent').innerHTML = `<form id="userForm">
    <label>اسم المستخدم</label><input name="username" required>
    <label>الاسم</label><input name="name" required>
    <label>رمز الدخول</label><input name="password" type="password" required>
    <label>الدور</label>
    <select name="role">
      <option value="ADMIN">الإدارة</option>
      <option value="HR">الموارد</option>
      <option value="WAREHOUSE">المخزن</option>
      <option value="DRIVER">السائق</option>
    </select>
    <label>رمز السائق</label><input name="driver_code">
    <label>الجوال</label><input name="phone">
    <button class="success">إنشاء</button>
  </form>`;
  openModal();
  bindModalForms();
}

function showEditUser(username) {
  const user = state.users.find(x => x.username === username);
  if (!user) return;

  document.getElementById('modalTitle').textContent = 'تعديل المستخدم';
  document.getElementById('modalContent').innerHTML = `<form id="editUserForm" data-username="${attr(user.username)}">
    <label>اسم المستخدم</label><input name="new_username" value="${attr(user.username)}" required>
    <label>الاسم</label><input name="name" value="${attr(user.name)}" required>
    <label>رمز دخول جديد (اتركه فارغًا دون تغيير)</label><input name="password" type="password">
    <label>الدور</label>
    <select name="role">
      ${['ADMIN','HR','WAREHOUSE','DRIVER'].map(role =>
        `<option value="${role}" ${user.role === role ? 'selected' : ''}>${roleName(role)}</option>`
      ).join('')}
    </select>
    <label>رمز السائق</label><input name="driver_code" value="${attr(user.driver_code || '')}">
    <label>الجوال</label><input name="phone" value="${attr(user.phone || '')}">
    <label>الحالة</label>
    <select name="active">
      <option value="true" ${user.active ? 'selected' : ''}>نشط</option>
      <option value="false" ${!user.active ? 'selected' : ''}>موقوف</option>
    </select>
    <button class="success">حفظ التعديل</button>
  </form>`;
  openModal();
  bindModalForms();
}

function renderVehicles(rows) {
  const body = document.getElementById('vehiclesBody');
  body.innerHTML = rows.length
    ? rows.map(vehicle => `<tr>
        <td data-label="السيارة">${esc(vehicle.name)}</td><td data-label="اللوحة">${esc(vehicle.plate_no)}</td>
        <td data-label="النوع">${esc(vehicle.vehicle_type || '')}</td><td data-label="الحالة">${esc(vehicle.status)}</td>
        <td data-label="ملاحظات">${esc(vehicle.notes || '')}</td>
        <td>
          <button class="edit-vehicle" data-id="${vehicle.id}">تعديل</button>
          <button class="toggle-vehicle secondary" data-id="${vehicle.id}">${vehicle.active===false?'تفعيل':'تعطيل'}</button>
          <button class="delete-vehicle danger" data-id="${vehicle.id}">حذف</button>
        </td>
      </tr>`).join('')
    : '<tr><td colspan="6">لا توجد سيارات.</td></tr>';
  body.querySelectorAll('.edit-vehicle').forEach(x=>x.addEventListener('click',()=>showEditVehicle(Number(x.dataset.id))));
  body.querySelectorAll('.toggle-vehicle').forEach(x=>x.addEventListener('click',()=>toggleVehicle(Number(x.dataset.id))));
  body.querySelectorAll('.delete-vehicle').forEach(x=>x.addEventListener('click',()=>deleteVehicle(Number(x.dataset.id))));
}

function showNewVehicle() {
  document.getElementById('modalTitle').textContent = 'إضافة سيارة';
  document.getElementById('modalContent').innerHTML = `<form id="vehicleForm">
    <label>اسم السيارة</label><input name="name" placeholder="دينا 1" required>
    <label>رقم اللوحة</label><input name="plate_no" required>
    <label>النوع</label><input name="vehicle_type">
    <label>الحالة</label>
    <select name="status">
      <option value="AVAILABLE">متاحة</option>
      <option value="MISSION">في مهمة</option>
      <option value="MAINTENANCE">في الصيانة</option>
      <option value="STOPPED">موقوفة</option>
    </select>
    <label>ملاحظات</label><textarea name="notes"></textarea>
    <button class="success">إضافة السيارة</button>
  </form>`;
  openModal();
  bindModalForms();
}


function bindEditButtons() {
  const adminEdit = document.getElementById('adminEditInvoiceBtn');
  if (adminEdit) adminEdit.addEventListener('click', showAdminEditInvoice);

  const del = document.getElementById('deleteInvoiceBtn');
  if (del) del.addEventListener('click', deleteCurrentInvoice);

  const hr = document.getElementById('editHrBtn');
  if (hr) hr.addEventListener('click', showEditHr);

  const wh = document.getElementById('editWarehouseBtn');
  if (wh) wh.addEventListener('click', showEditWarehouse);

  const dr = document.getElementById('editDriverBtn');
  if (dr) dr.addEventListener('click', showEditDriver);
}

function showEditHr() {
  const i = state.current;
  document.getElementById('modalTitle').textContent = 'تعديل بيانات الموارد';
  document.getElementById('modalContent').innerHTML = `<form id="editHrInvoiceForm">
    <label>رقم الفاتورة</label><input name="new_invoice_no" value="${attr(i.invoice_no)}" required>
    <label>العميل</label><input name="customer" value="${attr(i.customer || '')}">
    <label>ملاحظات الموارد</label><textarea name="notes">${esc(i.hr_notes || '')}</textarea>
    <button class="success">حفظ</button>
  </form>`;
  const form = document.getElementById('editHrInvoiceForm');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/invoices/${encodeURIComponent(i.invoice_no)}/edit-hr`, {method:'POST', body:new FormData(form)});
      closeModal(); toast('تم التعديل'); await bootstrap();
    } catch (error) { toast(error.message, true); }
  });
}

function showEditWarehouse() {
  const i = state.current;
  const driverOptions = state.drivers.map(d =>
    `<option value="${attr(d.driver_code)}" ${i.driver_code === d.driver_code ? 'selected' : ''}>${esc(d.name)}</option>`
  ).join('');
  const vehicleOptions = state.vehicles.map(v =>
    `<option value="${v.id}">${esc(v.name)} — ${esc(v.plate_no)}</option>`
  ).join('');
  document.getElementById('modalTitle').textContent = 'تعديل بيانات المخزن';
  document.getElementById('modalContent').innerHTML = `<form id="editWarehouseInvoiceForm">
    <label>السائق</label><select name="driver_code">${driverOptions}</select>
    <label>السيارة</label><select name="vehicle_id">${vehicleOptions}</select>
    <label>حالة التحميل</label>
    <select name="load_status">
      ${['تم التحميل كامل','تم التحميل ناقص','مرفوض من المخزن'].map(x => `<option ${i.load_status===x?'selected':''}>${x}</option>`).join('')}
    </select>
    <label>سبب النقص</label><input name="shortage_reason" value="${attr(i.warehouse_shortage_reason || '')}">
    <label>ملاحظات المخزن</label><textarea name="notes">${esc(i.warehouse_notes || '')}</textarea>
    <button class="success">حفظ</button>
  </form>`;
  const form = document.getElementById('editWarehouseInvoiceForm');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/invoices/${encodeURIComponent(i.invoice_no)}/edit-warehouse`, {method:'POST', body:new FormData(form)});
      closeModal(); toast('تم التعديل'); await bootstrap();
    } catch (error) { toast(error.message, true); }
  });
}

function showEditDriver() {
  const i = state.current;
  document.getElementById('modalTitle').textContent = 'تعديل نتيجة التسليم';
  document.getElementById('modalContent').innerHTML = `<form id="editDriverInvoiceForm">
    <label>نتيجة التسليم</label>
    <select name="delivery_result">
      ${['تم كامل','تم جزئي','رفض كامل','مؤجل','العميل مغلق'].map(x => `<option ${i.delivery_result===x?'selected':''}>${x}</option>`).join('')}
    </select>
    <label>كمية المرتجع</label><input name="return_qty_declared" type="number" step="0.01" value="${i.return_qty_declared || 0}">
    <label>السبب</label><input name="reason" value="${attr(i.delivery_reason || '')}">
    <label>صورة استلام جديدة</label><input id="editDriverReceiptPhoto" name="receipt_photo" type="file" accept="image/*" ${i.receipt_photo ? '' : 'required'}>
    <label>صورة مرتجع جديدة</label><input name="return_photo" type="file" accept="image/*">
    <label>ملاحظات السائق</label><textarea name="notes">${esc(i.driver_notes || '')}</textarea>
    <button id="editDriverSubmitBtn" class="success" ${i.receipt_photo ? '' : 'disabled'}>حفظ</button>
  </form>`;
  const form = document.getElementById('editDriverInvoiceForm');
  const receiptInput = form.querySelector('[name="receipt_photo"]');
  const submitButton = document.getElementById('editDriverSubmitBtn');
  receiptInput.addEventListener('change', () => {
    submitButton.disabled = !(i.receipt_photo || (receiptInput.files && receiptInput.files.length > 0));
  });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/invoices/${encodeURIComponent(i.invoice_no)}/edit-driver`, {method:'POST', body:new FormData(form)});
      closeModal(); toast('تم التعديل'); await bootstrap();
    } catch (error) { toast(error.message, true); }
  });
}

function showAdminEditInvoice() {
  const i = state.current;
  const driverOptions = state.drivers.map(d =>
    `<option value="${attr(d.driver_code)}" ${i.driver_code === d.driver_code ? 'selected' : ''}>${esc(d.name)}</option>`
  ).join('');
  const statuses = ['WAREHOUSE_PENDING','DRIVER_PENDING','POSTPONED','RETURN_PENDING','DOCUMENT_PENDING','CLOSED'];
  document.getElementById('modalTitle').textContent = 'تعديل شامل للفاتورة';
  document.getElementById('modalContent').innerHTML = `<form id="adminEditInvoiceForm">
    <label>رقم الفاتورة</label><input name="new_invoice_no" value="${attr(i.invoice_no)}" required>
    <label>العميل</label><input name="customer" value="${attr(i.customer || '')}">
    <label>السائق</label><select name="driver_code"><option value="">بدون تغيير</option>${driverOptions}</select>
    <label>السيارة</label><input name="vehicle_no" value="${attr(i.vehicle_no || '')}">
    <label>الحالة</label><select name="status">${statuses.map(s => `<option value="${s}" ${i.status===s?'selected':''}>${statusName(s)}</option>`).join('')}</select>
    <label>ملاحظات الموارد</label><textarea name="hr_notes">${esc(i.hr_notes || '')}</textarea>
    <label>ملاحظات المخزن</label><textarea name="warehouse_notes">${esc(i.warehouse_notes || '')}</textarea>
    <label>ملاحظات السائق</label><textarea name="driver_notes">${esc(i.driver_notes || '')}</textarea>
    <button class="success">حفظ التعديل</button>
  </form>`;
  const form = document.getElementById('adminEditInvoiceForm');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/invoices/${encodeURIComponent(i.invoice_no)}/admin-edit`, {method:'POST', body:new FormData(form)});
      closeModal(); toast('تم التعديل'); await bootstrap();
    } catch (error) { toast(error.message, true); }
  });
}

async function deleteCurrentInvoice() {
  const i = state.current;
  if (!confirm(`هل أنت متأكد من حذف الفاتورة ${i.invoice_no}؟`)) return;
  try {
    await api(`/api/invoices/${encodeURIComponent(i.invoice_no)}/delete`, {method:'POST'});
    closeModal(); toast('تم حذف الفاتورة'); await bootstrap();
  } catch (error) { toast(error.message, true); }
}

function renderLogs(rows) {
  const body = document.getElementById('logsBody');
  if (!body) return;
  body.innerHTML = rows.length ? rows.map(log => `<tr>
    <td>${dateTimeText(log.created_at)}</td>
    <td>${esc(log.username)}</td>
    <td>${esc(log.action)}</td>
    <td>${esc(log.invoice_no || '')}</td>
    <td>${esc(log.details || '')}</td>
    <td><button class="delete-log danger" data-id="${log.id}">حذف</button></td>
  </tr>`).join('') : '<tr><td colspan="6">لا توجد حركات.</td></tr>';
  body.querySelectorAll('.delete-log').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (!confirm('هل تريد حذف هذه الحركة؟')) return;
      try {
        await api('/api/logs/' + btn.dataset.id + '/delete', {method:'POST'});
        toast('تم حذف الحركة'); await bootstrap();
      } catch (error) { toast(error.message, true); }
    });
  });
}

function dateTimeText(value) {
  if (!value) return '';
  try { return new Date(value).toLocaleString('ar'); }
  catch { return String(value); }
}

function switchTab(tab) {
  ['queue','search','users','vehicles','products','logs'].forEach(name => {
    document.getElementById(name + 'Section').classList.toggle('hidden', name !== tab);
  });
  document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === tab);
  });
}

function openModal() {
  document.getElementById('modal').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal').classList.add('hidden');
  document.getElementById('modalContent').innerHTML = '';
}

function toast(message, error=false) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.style.background = error ? '#b91c1c' : '#111827';
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 4000);
}

function roleName(role) {
  return {ADMIN:'الإدارة',HR:'الموارد البشرية',WAREHOUSE:'أمين المخازن',DRIVER:'السائق'}[role] || role;
}

function statusName(status) {
  return {
    WAREHOUSE_PENDING:'بانتظار المخزن',
    DRIVER_PENDING:'مع السائق',
    POSTPONED:'مؤجلة',
    RETURN_PENDING:'مرتجع للمخزن',
    DOCUMENT_PENDING:'عند الموارد',
    FINAL_REVIEW_PENDING:'بانتظار استكمال الإقفال',
    CLOSED:'مكتملة'
  }[status] || status;
}

function vehicleStatus(status) {
  return {AVAILABLE:'متاحة',MISSION:'في مهمة',MAINTENANCE:'في الصيانة',STOPPED:'موقوفة'}[status] || status;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, m => ({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'
  }[m]));
}

function attr(value) {
  return esc(value).replace(/`/g, '&#096;');
}


function localDateTimeValue(){
  const d=new Date(); d.setMinutes(d.getMinutes()-d.getTimezoneOffset()); return d.toISOString().slice(0,16);
}
function productOptions(){ return state.products.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join(''); }
function addIssueRow(containerId, allowType=true){
  const c=document.getElementById(containerId); if(!c) return;
  const row=document.createElement('div'); row.className='issue-row form-grid';
  row.innerHTML=`${allowType?'<select class="issue-type"><option>ناقص</option><option>مرتجع</option></select>':''}
    <select class="issue-product"><option value="">اختر الصنف</option>${productOptions()}</select>
    <select class="issue-unit"><option value="">الوحدة</option></select>
    <input class="issue-qty" placeholder="الكمية">
    <button type="button" class="danger issue-remove">حذف</button>`;
  c.appendChild(row);
  const p=row.querySelector('.issue-product'), u=row.querySelector('.issue-unit');
  p.addEventListener('change',()=>{const prod=state.products.find(x=>String(x.id)===p.value);u.innerHTML='<option value="">الوحدة</option>'+(prod?.units||[]).map(x=>`<option>${esc(x)}</option>`).join('');});
  row.querySelector('.issue-remove').addEventListener('click',()=>row.remove());
}
function setupIssueEditor(form, rowsId, addId, allowType=true){
  const b=document.getElementById(addId); if(b) b.addEventListener('click',()=>addIssueRow(rowsId,allowType));
}
function serializeIssueRows(form){
  const rows=[...form.querySelectorAll('.issue-row')].map(r=>({
    issue_type:r.querySelector('.issue-type')?.value||'مرتجع',
    product_id:r.querySelector('.issue-product')?.value||'',
    unit:r.querySelector('.issue-unit')?.value||'',
    quantity:r.querySelector('.issue-qty')?.value||''
  })).filter(x=>x.product_id&&x.quantity);
  const h=form.querySelector('[name="issues_json"]'); if(h) h.value=JSON.stringify(rows);
}
function setupWarehouseForm(form){
  const mode=form.querySelector('#deliveryMode'), companyField=form.querySelector('#companyDriverField'), externalField=form.querySelector('#externalDriverField');
  const companySelect=form.querySelector('#companyDriverSelect'), externalSelect=form.querySelector('#externalDriverSelect'), driverCode=form.querySelector('#warehouseDriverCode');
  const vehicleField=form.querySelector('#vehicleField'), vehicleSelect=form.querySelector('[name="vehicle_id"]');
  const customerReceiptField=form.querySelector('#customerReceiptField'), customerReceipt=form.querySelector('[name="receipt_photo"]');
  const loadStatus=form.querySelector('#loadStatus'), issuesBox=form.querySelector('#warehouseIssues');
  const syncMode=()=>{
    const v=mode.value;
    companyField.classList.toggle('hidden',v!=='COMPANY_DRIVER');
    externalField.classList.toggle('hidden',v!=='EXTERNAL_DRIVER');
    vehicleField.classList.toggle('hidden',v!=='COMPANY_DRIVER');
    customerReceiptField.classList.toggle('hidden',v!=='CUSTOMER_SELF');
    companySelect.required=v==='COMPANY_DRIVER'; externalSelect.required=v==='EXTERNAL_DRIVER';
    vehicleSelect.required=v==='COMPANY_DRIVER'; customerReceipt.required=v==='CUSTOMER_SELF';
    driverCode.value=v==='COMPANY_DRIVER'?companySelect.value:(v==='EXTERNAL_DRIVER'?externalSelect.value:'');
    if(v!=='COMPANY_DRIVER') vehicleSelect.value='';
  };
  [mode,companySelect,externalSelect].forEach(el=>el.addEventListener('change',syncMode));
  const syncLoad=()=>issuesBox.classList.toggle('hidden',loadStatus.value!=='تم التحميل ناقص');
  loadStatus.addEventListener('change',syncLoad); syncMode(); syncLoad();
  setupIssueEditor(form,'warehouseIssueRows','addWarehouseIssue',true);
}
async function showDashboardBucket(bucket,title){
  if(bucket==='mine'){switchTab('queue');return;}
  try{
    const rows=await api('/api/dashboard/'+bucket);
    document.getElementById('modalTitle').textContent=title;
    document.getElementById('modalContent').innerHTML=`<div class="toolbar">
      <input id="popupFilter" placeholder="فرز/بحث: فاتورة، عميل، سائق">
      <select id="popupSort"><option value="invoice_no">رقم الفاتورة</option><option value="customer">العميل</option><option value="driver_name">السائق</option><option value="invoice_date">تاريخ الفاتورة</option><option value="loaded_at">تاريخ التحميل</option></select>
      <select id="popupSortDirection"><option value="asc">الأصغر / الأقدم أولاً</option><option value="desc">الأكبر / الأحدث أولاً</option></select>
    </div><div id="popupRows"></div>`;
    const draw=()=>{const q=document.getElementById('popupFilter').value.toLowerCase(), key=document.getElementById('popupSort').value;
      const desc=(document.getElementById('popupSortDirection')?.value||'asc')==='desc';
      const filtered=rows.filter(x=>[x.invoice_no,x.customer,x.driver_name].join(' ').toLowerCase().includes(q));
      const data=sortRows(filtered,key,desc);
      document.getElementById('popupRows').innerHTML=`<div class="table-wrap"><table><thead><tr><th>الفاتورة</th><th>العميل</th><th>السائق</th><th>الحالة</th><th>تاريخ الفاتورة</th><th>تاريخ التحميل</th><th></th></tr></thead><tbody>${data.map(i=>`<tr><td>${esc(i.invoice_no)}</td><td>${esc(i.customer||'')}</td><td>${esc(i.driver_name||'')}</td><td>${statusName(i.status)}</td><td>${dateTimeText(i.invoice_date)}</td><td>${dateTimeText(i.loaded_at)}</td><td><button class="popup-open" data-no="${attr(i.invoice_no)}">فتح</button></td></tr>`).join('')}</tbody></table></div>`;
      document.querySelectorAll('.popup-open').forEach(b=>b.addEventListener('click',()=>openInvoice(b.dataset.no)));
    }; openModal(); draw(); document.getElementById('popupFilter').addEventListener('input',draw);document.getElementById('popupSort').addEventListener('change',draw);document.getElementById('popupSortDirection')?.addEventListener('change',draw);
  }catch(e){toast(e.message,true);}
}
function renderProducts(rows){
  const b=document.getElementById('productsBody'); if(!b)return;
  b.innerHTML=rows.length?rows.map(p=>`<tr>
    <td data-label="الصنف">${esc(p.name)}</td>
    <td data-label="الوحدات">${esc((p.units||[]).join('، '))}</td>
    <td>${p.active?'فعال':'موقوف'}</td>
    <td>
      <button class="edit-product" data-id="${p.id}">تعديل</button>
      <button class="toggle-product secondary" data-id="${p.id}">${p.active?'تعطيل':'تفعيل'}</button>
      <button class="delete-product danger" data-id="${p.id}">حذف</button>
    </td>
  </tr>`).join(''):'<tr><td colspan="4">لا توجد أصناف.</td></tr>';
  b.querySelectorAll('.edit-product').forEach(x=>x.addEventListener('click',()=>showEditProduct(Number(x.dataset.id))));
  b.querySelectorAll('.toggle-product').forEach(x=>x.addEventListener('click',()=>toggleProduct(Number(x.dataset.id))));
  b.querySelectorAll('.delete-product').forEach(x=>x.addEventListener('click',()=>deleteProduct(Number(x.dataset.id))));
}
function showNewProduct(){
  document.getElementById('modalTitle').textContent='إضافة صنف';
  document.getElementById('modalContent').innerHTML=`<form id="productForm"><label>اسم الصنف</label><input name="name" required placeholder="مثال: حلاوة ١٤٠٠ جرام"><label>الوحدات</label><input name="units" required placeholder="حبة، كرتون"><button class="success">حفظ</button></form>`;
  const f=document.getElementById('productForm');openModal();f.addEventListener('submit',async e=>{e.preventDefault();try{await api('/api/products',{method:'POST',body:new FormData(f)});closeModal();toast('تم إضافة الصنف');await bootstrap();}catch(x){toast(x.message,true);}});
}
function showPermissions(username){
  const u=state.users.find(x=>x.username===username); if(!u)return;
  const cat=state.permissionCatalog, perms=u.permissions||{screens:[],actions:[]};
  const checks=(group,obj)=>Object.entries(obj||{}).map(([k,label])=>`<label class="perm-check"><input type="checkbox" data-group="${group}" value="${k}" ${perms[group]?.includes(k)?'checked':''}> ${esc(label)}</label>`).join('');
  document.getElementById('modalTitle').textContent='صلاحيات '+u.name;
  document.getElementById('modalContent').innerHTML=`<form id="permissionsForm"><h3>صلاحيات الشاشات</h3><div class="permission-grid">${checks('screens',cat.screens)}</div><h3>صلاحيات العمليات</h3><div class="permission-grid">${checks('actions',cat.actions)}</div><button class="success">حفظ الصلاحيات</button></form>`;
  openModal(); const f=document.getElementById('permissionsForm'); f.addEventListener('submit',async e=>{e.preventDefault();const data={screens:[],actions:[]};f.querySelectorAll('input:checked').forEach(x=>data[x.dataset.group].push(x.value));const fd=new FormData();fd.set('permissions_json',JSON.stringify(data));try{await api('/api/users/'+encodeURIComponent(username)+'/permissions',{method:'POST',body:fd});closeModal();toast('تم حفظ الصلاحيات');await bootstrap();}catch(x){toast(x.message,true);}});
}


function showEditProduct(id){
  const p=state.products.find(x=>x.id===id); if(!p)return;
  document.getElementById('modalTitle').textContent='تعديل الصنف';
  document.getElementById('modalContent').innerHTML=`<form id="editProductForm">
    <label>اسم الصنف</label><input name="name" required value="${attr(p.name)}">
    <label>الوحدات</label><input name="units" required value="${attr((p.units||[]).join('، '))}">
    <label>الحالة</label><select name="active"><option value="true" ${p.active?'selected':''}>فعال</option><option value="false" ${!p.active?'selected':''}>موقوف</option></select>
    <button class="success">حفظ</button></form>`;
  openModal(); const f=document.getElementById('editProductForm');
  f.addEventListener('submit',async e=>{e.preventDefault();try{await api(`/api/products/${id}/update`,{method:'POST',body:new FormData(f)});closeModal();toast('تم تعديل الصنف');await bootstrap();}catch(x){toast(x.message,true);}});
}
async function toggleProduct(id){try{const r=await api(`/api/products/${id}/toggle`,{method:'POST'});toast(r.active?'تم تفعيل الصنف':'تم تعطيل الصنف');await bootstrap();}catch(x){toast(x.message,true);}}
async function deleteProduct(id){if(!confirm('حذف الصنف؟ إذا كان مستخدمًا سابقًا سيتم تعطيله بدل الحذف.'))return;try{const r=await api(`/api/products/${id}/delete`,{method:'POST'});toast(r.message||'تم');await bootstrap();}catch(x){toast(x.message,true);}}

function showEditVehicle(id){
  const v=state.vehicles.find(x=>Number(x.id)===id); if(!v)return;
  document.getElementById('modalTitle').textContent='تعديل السيارة';
  document.getElementById('modalContent').innerHTML=`<form id="editVehicleForm">
    <label>الاسم</label><input name="name" required value="${attr(v.name)}">
    <label>رقم اللوحة</label><input name="plate_no" required value="${attr(v.plate_no)}">
    <label>النوع</label><input name="vehicle_type" value="${attr(v.vehicle_type||'')}">
    <label>الحالة</label><select name="status"><option value="AVAILABLE">متاحة</option><option value="MISSION">في مهمة</option><option value="MAINTENANCE">صيانة</option><option value="STOPPED">موقوفة</option></select>
    <label>ملاحظات</label><textarea name="notes">${esc(v.notes||'')}</textarea>
    <input type="hidden" name="active" value="${v.active===false?'false':'true'}"><button class="success">حفظ</button></form>`;
  openModal(); const f=document.getElementById('editVehicleForm'); f.querySelector('[name="status"]').value=v.status||'AVAILABLE';
  f.addEventListener('submit',async e=>{e.preventDefault();try{await api(`/api/vehicles/${id}/update`,{method:'POST',body:new FormData(f)});closeModal();toast('تم تعديل السيارة');await bootstrap();}catch(x){toast(x.message,true);}});
}
async function toggleVehicle(id){try{const r=await api(`/api/vehicles/${id}/toggle`,{method:'POST'});toast(r.active?'تم تفعيل السيارة':'تم تعطيل السيارة');await bootstrap();}catch(x){toast(x.message,true);}}
async function deleteVehicle(id){if(!confirm('حذف السيارة؟ إذا كانت مرتبطة بفواتير سابقة سيتم تعطيلها فقط.'))return;try{const r=await api(`/api/vehicles/${id}/delete`,{method:'POST'});toast(r.message||'تم');await bootstrap();}catch(x){toast(x.message,true);}}

async function toggleUser(username){try{const r=await api(`/api/users/${encodeURIComponent(username)}/toggle`,{method:'POST'});toast(r.active?'تم تفعيل المستخدم':'تم توقيف المستخدم من الدخول');await bootstrap();}catch(x){toast(x.message,true);}}
async function deleteUser(username){if(!confirm('إيقاف هذا المستخدم وإلغاء دخوله للنظام؟'))return;try{await api(`/api/users/${encodeURIComponent(username)}/delete`,{method:'POST'});toast('تم إيقاف المستخدم');await bootstrap();}catch(x){toast(x.message,true);}}


function norm(v){return String(v??'').toLowerCase().trim();}
function sortRows(rows,key,desc=false){
  const dateKeys = new Set(['invoice_date','loaded_at','created_at','updated_at']);
  return [...rows].sort((a,b)=>{
    const av=a?.[key], bv=b?.[key];
    // القيم الفارغة تكون في النهاية دائماً، خصوصاً تاريخ التحميل قبل أن يتم التحميل.
    const ae = av === null || av === undefined || av === '';
    const be = bv === null || bv === undefined || bv === '';
    if(ae && be) return 0;
    if(ae) return 1;
    if(be) return -1;

    let cmp=0;
    if(dateKeys.has(key)){
      const at=new Date(av).getTime(), bt=new Date(bv).getTime();
      cmp=(Number.isNaN(at)?0:at)-(Number.isNaN(bt)?0:bt);
    } else if(key==='invoice_no'){
      const an=Number(av), bn=Number(bv);
      cmp=(!Number.isNaN(an)&&!Number.isNaN(bn)) ? an-bn :
        String(av).localeCompare(String(bv),'ar',{numeric:true,sensitivity:'base'});
    } else {
      cmp=String(av).localeCompare(String(bv),'ar',{numeric:true,sensitivity:'base'});
    }
    return desc ? -cmp : cmp;
  });
}
function invoiceHaystack(i){return norm([i.invoice_no,i.customer,i.driver_name,i.status,statusName(i.status),i.invoice_date,i.loaded_at].join(' '));}

function renderFilteredQueue(){
  const q=norm(document.getElementById('queueFilter')?.value);
  const key=document.getElementById('queueSort')?.value||'invoice_date';
  const desc=(document.getElementById('queueSortDirection')?.value||'desc')==='desc';
  let rows=(state.queue||[]).filter(x=>!q||invoiceHaystack(x).includes(q));
  renderQueue(sortRows(rows,key,desc));
}

function renderFilteredSearch(){
  const status=document.getElementById('searchStatusFilter')?.value||'';
  const key=document.getElementById('searchSort')?.value||'invoice_no';
  const desc=(document.getElementById('searchSortDirection')?.value||'desc')==='desc';
  let rows=(state.searchRows||[]).filter(x=>!status||x.status===status);
  rows=sortRows(rows,key,desc);
  const body=document.getElementById('searchBody'); if(!body)return;
  body.innerHTML=rows.length?rows.map(i=>`<tr>
    <td data-label="الفاتورة">${esc(i.invoice_no)}</td>
    <td data-label="العميل">${esc(i.customer||'')}</td>
    <td data-label="السائق">${esc(i.driver_name||'')}</td>
    <td data-label="الحالة">${statusName(i.status)}</td>
    <td data-label="تاريخ الفاتورة">${dateOnlyText(i.invoice_date)}</td>
    <td data-label="تاريخ التحميل">${i.loaded_at?dateTimeText(i.loaded_at):''}</td>
    <td data-label=""><button class="open" data-no="${attr(i.invoice_no)}">فتح</button></td>
  </tr>`).join(''):'<tr><td colspan="7">لا توجد نتائج.</td></tr>';
  body.querySelectorAll('.open').forEach(btn=>btn.addEventListener('click',()=>openInvoice(btn.dataset.no)));
}

function renderFilteredUsers(){
  const q=norm(document.getElementById('usersFilter')?.value), role=document.getElementById('usersRoleFilter')?.value||'', status=document.getElementById('usersStatusFilter')?.value||'', key=document.getElementById('usersSort')?.value||'name';
  let rows=(state.users||[]).filter(u=>{
    const okQ=!q||norm([u.username,u.name,u.role,roleName(u.role),u.driver_code,u.phone].join(' ')).includes(q);
    const okR=!role||u.role===role;
    const okS=!status||(status==='active'?u.active:!u.active);
    return okQ&&okR&&okS;
  });
  renderUsers(sortRows(rows,key));
}

function renderFilteredVehicles(){
  const q=norm(document.getElementById('vehiclesFilter')?.value), status=document.getElementById('vehiclesStatusFilter')?.value||'', key=document.getElementById('vehiclesSort')?.value||'name';
  let rows=(state.vehicles||[]).filter(v=>(!q||norm([v.name,v.plate_no,v.vehicle_type,v.notes].join(' ')).includes(q))&&(!status||v.status===status));
  renderVehicles(sortRows(rows,key));
}

function renderFilteredProducts(){
  const q=norm(document.getElementById('productsFilter')?.value), status=document.getElementById('productsStatusFilter')?.value||'', key=document.getElementById('productsSort')?.value||'name';
  let rows=(state.products||[]).filter(p=>{
    const okQ=!q||norm([p.name,(p.units||[]).join(' ')].join(' ')).includes(q);
    const okS=!status||(status==='active'?p.active:!p.active);
    return okQ&&okS;
  });
  renderProducts(sortRows(rows,key));
}

function renderFilteredLogs(){
  const q=norm(document.getElementById('logsFilter')?.value), key=document.getElementById('logsSort')?.value||'created_at';
  let rows=(state.logs||[]).filter(l=>!q||norm([l.username,l.action,l.invoice_no,l.details].join(' ')).includes(q));
  renderLogs(sortRows(rows,key,key==='created_at'));
}

function dateOnlyText(value){
  if(!value) return '';
  const s=String(value);
  const d=new Date(s);
  if(Number.isNaN(d.getTime())) return esc(s.slice(0,10));
  return d.toLocaleDateString('ar-YE',{year:'numeric',month:'2-digit',day:'2-digit'});
}


async function compressImageFileForUpload(file, maxSide=1280, quality=0.72) {
  if (!file || !file.type || !file.type.startsWith('image/')) return file;
  // الصور الصغيرة لا تحتاج إعادة ضغط.
  if (file.size <= 900 * 1024) return file;

  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));

    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d', {alpha:false});
    ctx.drawImage(bitmap, 0, 0, width, height);
    if (bitmap.close) bitmap.close();

    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', quality));
    if (!blob) return file;
    // لا نستبدل الملف إذا لم نحصل فعلاً على حجم أصغر.
    if (blob.size >= file.size) return file;

    const baseName = (file.name || 'image').replace(/\.[^.]+$/, '');
    return new File([blob], `${baseName}.jpg`, {type:'image/jpeg', lastModified:Date.now()});
  } catch (_) {
    // HEIC وبعض الصيغ قد لا يستطيع المتصفح فكها؛ نرسل الأصل للخادم.
    return file;
  }
}

async function optimizedFormData(form) {
  const fd = new FormData(form);
  const fileNames = ['receipt_photo','return_photo','photo','external_receipt'];
  for (const name of fileNames) {
    const input = form.querySelector(`[name="${name}"]`);
    if (!input || !input.files || !input.files[0]) continue;
    const original = input.files[0];
    const optimized = await compressImageFileForUpload(original);
    if (optimized !== original) fd.set(name, optimized, optimized.name);
  }
  return fd;
}

function setSubmitting(form, active, label='جاري الاعتماد...') {
  const btn = form.querySelector('button[type="submit"], button:not([type])');
  if (!btn) return;
  if (active) {
    btn.dataset.oldText = btn.textContent;
    btn.disabled = true;
    btn.classList.add('is-loading');
    btn.textContent = label;
  } else {
    btn.classList.remove('is-loading');
    btn.textContent = btn.dataset.oldText || 'اعتماد';
  }
}

function bindLiveFilterControls(){
  const pairs = [
    ['queueFilter','queueSort','queueSortDirection'],
    ['searchInput','searchStatusFilter','searchSort','searchSortDirection'],
    ['usersFilter','usersRoleFilter','usersStatusFilter','usersSort'],
    ['vehiclesFilter','vehiclesStatusFilter','vehiclesSort'],
    ['productsFilter','productsStatusFilter','productsSort'],
    ['logsFilter','logsSort']
  ];
  const handlers = [renderFilteredQueue, renderFilteredSearch, renderFilteredUsers, renderFilteredVehicles, renderFilteredProducts, renderFilteredLogs];
  pairs.forEach((ids,idx)=>{
    ids.forEach(id=>{
      const el=document.getElementById(id);
      if(!el || el.dataset.liveBound==='1') return;
      ['input','change'].forEach(ev=>el.addEventListener(ev,handlers[idx]));
      el.dataset.liveBound='1';
    });
  });
}


function renderInvoiceSequence(){
  const box=document.getElementById('sequenceConfig');
  const input=document.getElementById('sequenceStartInput');
  const warning=document.getElementById('sequenceWarning');
  if(!box || !warning) return;

  const canConfigure=['ADMIN','HR'].includes(state.user?.role);
  box.classList.toggle('hidden',!canConfigure);
  if(input && state.invoiceSequence?.start) input.value=state.invoiceSequence.start;

  const seq=state.invoiceSequence||{};
  if(!seq.configured){
    warning.classList.remove('hidden');
    warning.innerHTML='⚠️ لم يتم تحديد بداية تسلسل الفواتير. حدد أول رقم تريد أن يبدأ النظام التدقيق منه.';
    return;
  }

  const missing=seq.missing||[];
  if(!missing.length){
    warning.classList.remove('hidden');
    warning.innerHTML=`✓ تسلسل الفواتير سليم من رقم <b>${seq.start}</b>${seq.max?` حتى <b>${seq.max}</b>`:''}.`;
    warning.classList.add('sequence-ok');
    return;
  }

  warning.classList.remove('hidden','sequence-ok');
  const preview=missing.slice(0,40).join('، ');
  const more=missing.length>40?` … و${missing.length-40} رقم آخر`:'';
  warning.innerHTML=`⚠️ <b>يوجد ${missing.length} رقم فاتورة مفقود في التسلسل</b><br>
    من ${seq.start} إلى ${seq.max}: ${preview}${more}`;
}

async function saveInvoiceSequenceStart(){
  const input=document.getElementById('sequenceStartInput');
  const start=Number(input?.value||0);
  if(!start || start<1){toast('اكتب رقم بداية صحيح للتسلسل.',true);return;}
  const fd=new FormData();fd.set('start',String(start));
  try{
    state.invoiceSequence=await api('/api/settings/invoice-sequence',{method:'POST',body:fd});
    renderInvoiceSequence();
    toast('تم حفظ بداية تسلسل الفواتير.');
  }catch(e){toast(e.message,true);}
}
