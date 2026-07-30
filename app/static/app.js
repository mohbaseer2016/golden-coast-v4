'use strict';

const state = {user:null, drivers:[], vehicles:[], users:[], logs:[], current:null};

document.addEventListener('DOMContentLoaded', () => {
  bind('loginForm','submit',login);
  bind('logoutBtn','click',logout);
  bind('refreshBtn','click',bootstrap);
  bind('newInvoiceBtn','click',showNewInvoice);
  bind('newUserBtn','click',showNewUser);
  bind('newVehicleBtn','click',showNewVehicle);
  bind('searchBtn','click',search);
  bind('closeModalBtn','click',closeModal);
  document.querySelectorAll('[data-tab]').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });
  bootstrap();
});

function bind(id, event, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(event, handler);
}

async function api(url, options={}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({detail:'حدث خطأ'}));
  if (!response.ok) throw new Error(data.detail || 'حدث خطأ');
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
  await api('/api/logout', {method:'POST'});
  location.reload();
}

async function bootstrap() {
  try {
    const data = await api('/api/bootstrap');
    state.user = data.user;
    state.drivers = data.drivers;
    state.vehicles = data.vehicles;
    state.users = data.users;
    state.logs = data.logs || [];

    document.getElementById('loginView').classList.add('hidden');
    document.getElementById('appView').classList.remove('hidden');
    document.getElementById('userLabel').textContent = `${state.user.name} — ${roleName(state.user.role)}`;
    document.getElementById('newInvoiceBtn').classList.toggle('hidden', !['ADMIN','HR'].includes(state.user.role));
    document.getElementById('usersTab').classList.toggle('hidden', state.user.role !== 'ADMIN');
    document.getElementById('vehiclesTab').classList.toggle('hidden', state.user.role !== 'ADMIN');
    document.getElementById('logsTab').classList.toggle('hidden', state.user.role !== 'ADMIN');

    renderStats(data.stats);
    renderQueue(data.queue);
    renderUsers(data.users || []);
    renderVehicles(data.vehicles || []);
    renderLogs(data.logs || []);
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
    cards.map(x => `<div class="card stat">${x[0]}<b>${x[1]}</b></div>`).join('');
}

function renderQueue(rows) {
  const body = document.getElementById('queueBody');
  body.innerHTML = rows.length
    ? rows.map(rowHtml).join('')
    : '<tr><td colspan="5">لا توجد فواتير معلقة.</td></tr>';
  body.querySelectorAll('.open').forEach(btn => {
    btn.addEventListener('click', () => openInvoice(btn.dataset.no));
  });
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

function showInvoice(invoice) {
  document.getElementById('modalTitle').textContent = 'فاتورة ' + invoice.invoice_no;
  let html = `<div class="card">
    <b>السائق:</b> ${esc(invoice.driver_name || 'لم يحدد')}<br>
    <b>السيارة:</b> ${esc(invoice.vehicle_no || 'لم تحدد')}<br>
    <b>الحالة:</b> ${statusName(invoice.status)}
  </div>`;

  if (['ADMIN','WAREHOUSE'].includes(state.user.role) && invoice.status === 'WAREHOUSE_PENDING') {
    html += warehouseForm();
  } else if (['ADMIN','WAREHOUSE'].includes(state.user.role) && invoice.status === 'RETURN_PENDING') {
    html += returnForm(invoice);
  } else if (['ADMIN','DRIVER'].includes(state.user.role) && ['DRIVER_PENDING','POSTPONED'].includes(invoice.status)) {
    html += driverForm();
  } else if (['ADMIN','HR'].includes(state.user.role) && invoice.status === 'DOCUMENT_PENDING') {
    html += closeForm(invoice);
  } else {
    html += '<p>عرض فقط.</p>';
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
  const driverOptions = state.drivers.map(driver =>
    `<option value="${attr(driver.driver_code)}">${esc(driver.name)}${driver.is_external_driver ? ' (خارجي)' : ''}</option>`
  ).join('');

  const vehicleOptions = state.vehicles.map(vehicle =>
    `<option value="${vehicle.id}">${esc(vehicle.name)} — ${esc(vehicle.plate_no)}</option>`
  ).join('');

  return `<form id="warehouseForm">
    <label>السائق</label>
    <select name="driver_code" required><option value="">اختر</option>${driverOptions}</select>
    <label>السيارة</label>
    <select name="vehicle_id" required><option value="">اختر</option>${vehicleOptions}</select>
    <label>حالة التحميل</label>
    <select name="load_status">
      <option>تم التحميل كامل</option>
      <option>تم التحميل ناقص</option>
      <option>مرفوض من المخزن</option>
    </select>
    <label>سبب النقص أو الرفض</label><input name="shortage_reason">
    <label>صورة</label><input type="file" name="photo" accept="image/*">
    <label>ملاحظات</label><textarea name="notes"></textarea>
    <button>اعتماد</button>
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
    <label>كمية المرتجع</label><input name="return_qty_declared" type="number" step="0.01" value="0">
    <label>السبب</label><input name="reason">
    <label>صورة الاستلام</label><input name="receipt_photo" type="file" accept="image/*">
    <label>صورة المرتجع</label><input name="return_photo" type="file" accept="image/*">
    <label>ملاحظات</label><textarea name="notes"></textarea>
    <button>اعتماد</button>
  </form>`;
}

function returnForm(invoice) {
  return `<form id="returnForm">
    <label>الكمية المستلمة فعليًا</label>
    <input name="return_qty_actual" type="number" step="0.01" value="${invoice.return_qty_declared}">
    <label>حالة المرتجع</label><input name="condition">
    <label>صورة المرتجع</label><input name="photo" type="file" accept="image/*">
    <label>ملاحظات</label><textarea name="notes"></textarea>
    <button>تأكيد</button>
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
    <button class="success">إغلاق الفاتورة</button>
  </form>`;
}

function bindModalForms() {
  const forms = [
    ['warehouseForm', 'warehouse'],
    ['driverForm', 'driver'],
    ['returnForm', 'return'],
    ['closeForm', 'close'],
    ['invoiceForm', 'invoices'],
    ['userForm', 'users'],
    ['vehicleForm', 'vehicles'],
    ['editUserForm', 'edit-user'],
  ];

  forms.forEach(([id, path]) => {
    const form = document.getElementById(id);
    if (!form) return;

    form.addEventListener('submit', async event => {
      event.preventDefault();
      try {
        let url;
        if (id === 'invoiceForm') url = '/api/invoices';
        else if (id === 'userForm') url = '/api/users';
        else if (id === 'vehicleForm') url = '/api/vehicles';
        else if (id === 'editUserForm') url = '/api/users/' + encodeURIComponent(form.dataset.username);
        else url = `/api/invoices/${encodeURIComponent(state.current.invoice_no)}/${path}`;

        await api(url, {method:'POST', body:new FormData(form)});
        closeModal();
        toast('تم الحفظ');
        await bootstrap();
      } catch (error) {
        toast(error.message, true);
      }
    });
  });
}

function showNewInvoice() {
  document.getElementById('modalTitle').textContent = 'إدخال فاتورة';
  document.getElementById('modalContent').innerHTML = `<form id="invoiceForm">
    <label>رقم الفاتورة</label><input name="invoice_no" required>
    <label>اسم العميل (اختياري)</label><input name="customer">
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
    const rows = await api(`/api/invoices/search?q=${q}&include_closed=${closed}`);
    const body = document.getElementById('searchBody');
    body.innerHTML = rows.length
      ? rows.map(i => `<tr>
          <td>${esc(i.invoice_no)}</td><td>${esc(i.customer || '')}</td>
          <td>${esc(i.driver_name || '')}</td><td>${statusName(i.status)}</td>
          <td></td><td><button class="open" data-no="${attr(i.invoice_no)}">فتح</button></td>
        </tr>`).join('')
      : '<tr><td colspan="6">لا توجد نتائج.</td></tr>';
    body.querySelectorAll('.open').forEach(btn => {
      btn.addEventListener('click', () => openInvoice(btn.dataset.no));
    });
  } catch (error) {
    toast(error.message, true);
  }
}

function renderUsers(rows) {
  const body = document.getElementById('usersBody');
  body.innerHTML = rows.length
    ? rows.map(user => `<tr>
        <td>${esc(user.username)}</td>
        <td>${esc(user.name)}</td>
        <td>${roleName(user.role)}</td>
        <td>${esc(user.driver_code || '')}</td>
        <td>${esc(user.phone || '')}</td>
        <td>${user.active ? 'نشط' : 'موقوف'}</td>
        <td><button class="edit-user" data-user="${attr(user.username)}">تعديل</button></td>
      </tr>`).join('')
    : '<tr><td colspan="7">لا يوجد مستخدمون.</td></tr>';

  body.querySelectorAll('.edit-user').forEach(btn => {
    btn.addEventListener('click', () => showEditUser(btn.dataset.user));
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
  document.getElementById('vehiclesBody').innerHTML = rows.length
    ? rows.map(vehicle => `<tr>
        <td>${esc(vehicle.name)}</td>
        <td>${esc(vehicle.plate_no)}</td>
        <td>${esc(vehicle.vehicle_type || '')}</td>
        <td>${vehicleStatus(vehicle.status)}</td>
        <td>${esc(vehicle.notes || '')}</td>
      </tr>`).join('')
    : '<tr><td colspan="5">لا توجد سيارات. أضف أول سيارة.</td></tr>';
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
    <label>صورة استلام جديدة</label><input name="receipt_photo" type="file" accept="image/*">
    <label>صورة مرتجع جديدة</label><input name="return_photo" type="file" accept="image/*">
    <label>ملاحظات السائق</label><textarea name="notes">${esc(i.driver_notes || '')}</textarea>
    <button class="success">حفظ</button>
  </form>`;
  const form = document.getElementById('editDriverInvoiceForm');
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
  ['queue','search','users','vehicles','logs'].forEach(name => {
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
