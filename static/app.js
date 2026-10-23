'use strict';

(() => {
  const byId = id => document.getElementById(id);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  const storageKey = 'shuye-conversion-tasks-v1';
  const terminal = new Set(['ready', 'needs_attention', 'failed', 'cancelled', 'interrupted']);
  const stageLabels = {
    queued: '等待处理', running: '正在处理', extracting: '读取资料', inventory: '核对资料清单',
    planning: '确定学习结构', generating: '构建教材内容', reviewing: '核查内容与来源',
    validating: '检查与打包', testing: '检验学习页面', ready: '可以下载',
    needs_attention: '需要补充核对', failed: '转换未完成', cancelled: '已取消', interrupted: '处理中断'
  };
  const progress = [
    ['queued', '任务已提交', '等待服务安排处理'],
    ['extracting', '读取与核对资料', '识别页面、结构及资料关系'],
    ['planning', '确定学习结构', '依据主资料建立范围与章节'],
    ['generating', '逐章构建内容', '保留实质讲解、原题与答案出处'],
    ['reviewing', '核查内容与来源', '独立核对覆盖情况和解答'],
    ['validating', '打包与功能检查', '检查结构、公式与离线学习功能'],
    ['ready', '下载交互教材', '交付一个可以离线打开的 HTML']
  ];
  const roles = [
    ['textbook', '教材'], ['teacher_slides', '教师课件'], ['outline', '提纲'],
    ['solution', '配套答案与解析'], ['exam', '真题试卷'], ['auxiliary', '其他辅助资料']
  ];
  const state = {
    config: null, files: [], submitting: false, task: null, job: null,
    tasks: [], selectedId: null, pollTimer: null, requestVersion: 0, pollVersion: 0, storageWarning: false
  };

  function showMessage(target, message) {
    const node = byId(target);
    node.textContent = message || '';
    node.hidden = !message;
  }
  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  function formatDate(raw) {
    if (!raw) return '';
    const date = new Date(typeof raw === 'number' && raw < 1e12 ? raw * 1000 : raw);
    return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  }
  function cleanError(error, fallback = '暂时无法完成操作，请稍后重试。') {
    if (error && typeof error.userMessage === 'string') return error.userMessage.slice(0, 2000);
    if (error && error.name === 'AbortError') return '连接等待超时，请重试。已经提交的任务仍可能继续处理。';
    return fallback;
  }
  function statusText(status) { return stageLabels[status] || '正在处理'; }
  function safeTask(raw) {
    return raw && typeof raw.id === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(raw.id)
      && typeof raw.token === 'string' && /^[a-zA-Z0-9._~-]{8,512}$/.test(raw.token)
      ? { id: raw.id, token: raw.token } : null;
  }
  function loadTasks() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
      if (Array.isArray(saved.tasks)) {
        const ids = new Set();
        state.tasks = saved.tasks.map(safeTask).filter(task => task && !ids.has(task.id) && ids.add(task.id));
      }
      state.selectedId = state.tasks.some(task => task.id === saved.selectedId) ? saved.selectedId : null;
    } catch (_) {
      warnStorage();
    }
  }
  function warnStorage() {
    if (state.storageWarning) return;
    state.storageWarning = true;
    showMessage('global-message', '这个浏览器无法保留任务入口。请保持本页打开并及时下载成品；关闭页面后可能无法恢复任务。');
  }
  function saveTasks() {
    try {
      const payload = JSON.stringify({ tasks: state.tasks, selectedId: state.selectedId });
      localStorage.setItem(storageKey, payload);
      if (localStorage.getItem(storageKey) !== payload) warnStorage();
    } catch (_) { warnStorage(); }
    renderSavedTasks();
  }
  function renderSavedTasks() {
    byId('task-count').textContent = String(state.tasks.length);
    byId('saved-list').replaceChildren();
    if (!state.tasks.length) {
      byId('saved-list').append(el('p', 'subtle', '还没有保留的任务。提交转换后，任务入口会保存在当前浏览器。'));
      return;
    }
    [...state.tasks].reverse().forEach((task, index) => {
      const button = el('button', 'saved-task', `转换任务 ${state.tasks.length - index}`);
      button.type = 'button';
      button.dataset.taskId = task.id;
      const current = state.job && task.id === state.task?.id;
      button.append(el('span', '', current ? `${state.job.title || '未命名教材'} · ${statusText(state.job.status)}` : `任务标识 ${task.id.slice(0, 10)}… · 点击读取状态`));
      button.addEventListener('click', () => openTask(task, true));
      byId('saved-list').append(button);
    });
  }
  async function api(path, options = {}, task = null, timeout = 30000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const headers = new Headers(options.headers || {});
    if (task) headers.set('Authorization', `Bearer ${task.token}`);
    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    try {
      const response = await fetch(path, { ...options, headers, signal: controller.signal, credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) {
        let message = '服务暂时无法处理此操作，请稍后重试。';
        try {
          const body = await response.json();
          if (typeof body.error === 'string') message = body.error;
        } catch (_) {
          if (response.status === 413) message = '资料总体积超过服务限制，请减少文件后重试。';
          if (response.status === 404) message = '任务不存在或已到期清理。';
        }
        const error = new Error('Request did not complete');
        error.userMessage = message;
        error.httpStatus = response.status;
        throw error;
      }
      return response;
    } finally { clearTimeout(timer); }
  }
  function taskPath(task = state.task) { return `/api/jobs/${encodeURIComponent(task.id)}`; }
  async function loadConfig() {
    byId('refresh-service').disabled = true;
    try {
      const response = await api('/api/config');
      const config = await response.json();
      if (!config || typeof config.ready !== 'boolean' || !config.limits) throw new Error('Invalid configuration');
      state.config = config;
      const ready = config.ready;
      byId('service-status').classList.toggle('is-ready', ready);
      byId('service-title').textContent = ready ? '转换服务已就绪' : '转换服务尚未启用';
      const reasons = Array.isArray(config.reasons) ? config.reasons.filter(reason => typeof reason === 'string') : [];
      byId('service-detail').textContent = ready
        ? '选择资料后即可提交。教材将逐章处理，通过检查后提供下载。'
        : (reasons.join(' ') || '管理员尚未完成转换服务配置。') + ' 你仍可先选择文件、设置资料关系。';
      byId('refresh-service').hidden = ready;
      const formats = supportedFormats();
      byId('file-input').accept = formats.map(type => `.${type}`).join(',');
      byId('upload-limits').textContent = `${formats.join(' / ').toUpperCase()} · 最多 ${config.limits.maxFiles} 份 · 单份 ${formatSize(config.limits.maxFileBytes)} · 共 ${formatSize(config.limits.maxTotalBytes)}`;
      const hours = Number(config.retentionHours);
      const retention = Number.isFinite(hours) && hours > 0 ? `${hours} 小时` : '服务规定的期限';
      byId('retention-note').textContent = `资料和成品自提交起保留 ${retention}，随后自动清理。你也可以在任务页面主动删除，请及时下载成品。`;
      byId('consent-retention').textContent = `资料和成品自提交起保留 ${retention}，也可在任务页面主动删除。`;
      byId('provider-name').textContent = typeof config.provider === 'string' && config.provider ? config.provider : 'OpenAI';
      byId('access-code-field').hidden = !config.accessCodeRequired;
      byId('access-code').required = Boolean(config.accessCodeRequired);
      validateChosenFiles();
      if (state.job) renderJob(state.job);
    } catch (error) {
      state.config = null;
      byId('service-status').classList.remove('is-ready');
      byId('service-title').textContent = '暂时无法连接转换服务';
      byId('service-detail').textContent = '可以先准备资料。恢复连接后重新检查服务状态，再提交转换。';
      byId('refresh-service').hidden = false;
    } finally {
      byId('refresh-service').disabled = false;
      updateSubmit();
    }
  }
  function supportedFormats() {
    const formats = state.config?.formats;
    return Array.isArray(formats) && formats.length ? formats.map(value => String(value).toLowerCase().replace(/^\./, '')) : ['pdf', 'txt', 'md', 'docx', 'pptx'];
  }
  function fileIssue() {
    if (!state.config || !state.files.length) return '';
    const limits = state.config.limits;
    const total = state.files.reduce((sum, entry) => sum + entry.file.size, 0);
    if (state.files.length > limits.maxFiles) return `一次最多上传 ${limits.maxFiles} 份资料，请移除多余文件。`;
    const unsupported = state.files.find(entry => !supportedFormats().includes(entry.file.name.split('.').pop().toLowerCase()));
    if (unsupported) return `暂不支持“${unsupported.file.name}”的文件格式。`;
    const empty = state.files.find(entry => entry.file.size === 0);
    if (empty) return `“${empty.file.name}”为空文件，请重新选择有效资料。`;
    const oversize = state.files.find(entry => entry.file.size > limits.maxFileBytes);
    if (oversize) return `“${oversize.file.name}”超过单份 ${formatSize(limits.maxFileBytes)} 的限制。`;
    if (total > limits.maxTotalBytes) return `资料总体积超过 ${formatSize(limits.maxTotalBytes)}，请减少文件后再提交。`;
    if (!state.files.some(entry => entry.primary)) return '请至少标记一份主资料，明确学习内容以什么为准。';
    return '';
  }
  function validateChosenFiles() { showMessage('file-error', fileIssue()); }
  function updateSubmit() {
    const hasFiles = state.files.length > 0;
    const consent = byId('consent').checked;
    const access = !state.config?.accessCodeRequired || byId('access-code').value.trim().length > 0;
    const issue = fileIssue();
    byId('submit-job').disabled = state.submitting || !state.config?.ready || !hasFiles || !consent || !access || Boolean(issue);
    byId('submit-label').textContent = state.submitting ? '正在安全提交资料…' : '开始转换';
    let hint = '转换会逐章处理并检查，较长教材需要更多时间。';
    if (state.submitting) hint = '请保持本页打开，收到任务确认后可稍后返回查看。';
    else if (!state.config?.ready) hint = '服务尚未就绪，当前不能提交转换。';
    else if (!hasFiles) hint = '先选择需要转换的教材或配套资料。';
    else if (issue) hint = '请先处理上方资料提示。';
    else if (!access) hint = '请输入服务管理员提供的访问码。';
    else if (!consent) hint = '请先阅读并确认资料处理授权。';
    byId('submit-hint').textContent = hint;
  }
  function chooseFiles(files) {
    if (state.submitting) return;
    let duplicates = 0;
    for (const file of files) {
      if (state.files.some(entry => entry.file.name === file.name && entry.file.size === file.size && entry.file.lastModified === file.lastModified)) { duplicates += 1; continue; }
      const isFirst = !state.files.length;
      const id = globalThis.crypto?.randomUUID ? crypto.randomUUID() : `file-${Date.now()}-${Math.random().toString(36).slice(2)}`;
      state.files.push({ id, file, role: 'textbook', primary: isFirst });
    }
    showMessage('submit-error', duplicates ? `已跳过 ${duplicates} 份名称、大小和修改时间均相同的重复选择；内容不同的文件请使用不同名称。` : '');
    renderFiles();
  }
  function renderFiles() {
    const list = byId('file-list');
    list.replaceChildren();
    state.files.forEach((entry, index) => {
      const row = el('div', 'file-row');
      row.dataset.fileId = entry.id;
      const top = el('div', 'file-top');
      top.append(el('span', 'file-type', entry.file.name.split('.').pop().slice(0, 5).toUpperCase()));
      const info = el('div', 'file-info');
      info.append(el('div', 'file-name', entry.file.name), el('div', 'file-meta', formatSize(entry.file.size)));
      top.append(info);
      const remove = el('button', 'remove-file', '×');
      remove.id = `remove-file-${index}`;
      remove.type = 'button';
      remove.setAttribute('aria-label', `移除 ${entry.file.name}`);
      remove.addEventListener('click', () => { state.files = state.files.filter(item => item.id !== entry.id); renderFiles(); });
      top.append(remove);
      const controls = el('div', 'file-controls');
      const label = el('label', '', '资料类型');
      const select = el('select');
      select.id = `file-role-${index}`;
      select.setAttribute('aria-label', `${entry.file.name} 的资料类型`);
      roles.forEach(([value, title]) => { const option = el('option', '', title); option.value = value; select.append(option); });
      select.value = entry.role;
      select.addEventListener('change', () => { entry.role = select.value; updateSubmit(); });
      label.append(select);
      const primaryLabel = el('label', 'primary-checkbox');
      const primary = el('input');
      primary.type = 'checkbox';
      primary.id = `file-primary-${index}`;
      primary.checked = entry.primary;
      primary.setAttribute('aria-label', `将 ${entry.file.name} 设为主资料`);
      primary.addEventListener('change', () => { entry.primary = primary.checked; updateFileSummary(); validateChosenFiles(); updateSubmit(); });
      primaryLabel.append(primary, el('span', '', '主资料'));
      controls.append(label, primaryLabel);
      row.append(top, controls);
      list.append(row);
    });
    updateFileSummary();
    validateChosenFiles();
    updateSubmit();
  }
  function updateFileSummary() {
    byId('file-summary').textContent = `${state.files.length} 份资料 · 合计 ${formatSize(state.files.reduce((sum, entry) => sum + entry.file.size, 0))} · 主资料 ${state.files.filter(entry => entry.primary).length} 份`;
    byId('file-summary').hidden = !state.files.length;
  }
  function fileBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = String(reader.result);
        const separator = result.indexOf(',');
        if (separator < 0) { reject(new Error('Could not read file')); return; }
        resolve(result.slice(separator + 1));
      };
      reader.onerror = () => reject(new Error('Could not read file'));
      reader.readAsDataURL(file);
    });
  }
  async function submit(event) {
    event.preventDefault();
    if (byId('submit-job').disabled) return;
    state.submitting = true;
    showMessage('submit-error', '');
    const fields = [...byId('conversion-form').querySelectorAll('input,select,textarea,button')];
    fields.forEach(node => { node.disabled = true; });
    updateSubmit();
    try {
      const files = [];
      for (const entry of state.files) files.push({ name: entry.file.name, role: entry.role, primary: entry.primary, data: await fileBase64(entry.file) });
      const body = {
        title: byId('book-title').value.trim() || (state.files.find(entry => entry.primary)?.file.name || '交互学习教材').replace(/\.[^.]+$/, '').slice(0, 120), mode: byId('material-mode').value,
        scope: byId('scope').value.trim(), consent: byId('consent').checked, files
      };
      if (state.config.accessCodeRequired) body.accessCode = byId('access-code').value;
      const response = await api('/api/jobs', { method: 'POST', body: JSON.stringify(body) }, null, 120000);
      const raw = await response.json();
      const task = safeTask(raw);
      if (!task) throw new Error('Missing task receipt');
      state.tasks.push(task);
      state.selectedId = task.id;
      saveTasks();
      state.files = [];
      byId('conversion-form').reset();
      renderFiles();
      await openTask(task, true);
    } catch (error) {
      showMessage('submit-error', cleanError(error, '资料未能确认提交，请检查连接后重试。若请求已到达服务，任务可能已经建立，请勿连续重复提交。'));
      if (error.httpStatus === 503) await loadConfig();
    } finally {
      state.submitting = false;
      fields.forEach(node => { node.disabled = false; });
      updateSubmit();
    }
  }
  function cancelPolling() { clearTimeout(state.pollTimer); state.pollTimer = null; }
  async function openTask(task, focus = false) {
    cancelPolling();
    state.requestVersion += 1;
    state.task = task;
    state.job = null;
    state.selectedId = task.id;
    saveTasks();
    byId('prepare-view').hidden = true;
    byId('job-panel').hidden = false;
    byId('job-title').textContent = '正在读取任务';
    byId('job-message').textContent = '正在恢复本次转换的实际状态。';
    byId('job-status').textContent = '读取中';
    byId('progress-steps').replaceChildren();
    byId('event-list').replaceChildren();
    byId('job-checks').hidden = true;
    byId('no-events').hidden = false;
    byId('job-expiry').textContent = '';
    ['download-job', 'retry-job', 'cancel-job'].forEach(id => { byId(id).hidden = true; });
    showMessage('job-error', '');
    if (focus) { byId('job-panel').focus({ preventScroll: true }); byId('workspace').scrollIntoView({ behavior: 'smooth', block: 'start' }); }
    await refreshTask();
  }
  async function refreshTask() {
    if (!state.task) return;
    const task = state.task;
    const version = state.requestVersion;
    const pollVersion = ++state.pollVersion;
    try {
      const response = await api(taskPath(task), {}, task);
      const job = await response.json();
      if (version !== state.requestVersion || pollVersion !== state.pollVersion || state.task?.id !== task.id) return;
      if (!job || typeof job.status !== 'string') throw new Error('Invalid job status');
      state.job = job;
      showMessage('job-error', '');
      renderJob(job);
      if (!terminal.has(job.status)) state.pollTimer = setTimeout(refreshTask, 2500);
    } catch (error) {
      if (version !== state.requestVersion || pollVersion !== state.pollVersion) return;
      showMessage('job-error', cleanError(error, '暂时无法读取进度，正在尝试重新连接。请不要重复提交资料。'));
      if ([401, 403, 404, 410].includes(error.httpStatus)) {
        byId('job-status').textContent = '任务不可访问';
        byId('job-message').textContent = '任务可能已到期清理，或当前浏览器的任务凭证已失效。';
        byId('delete-job').textContent = '移除本机任务入口';
        ['download-job', 'retry-job', 'cancel-job'].forEach(id => { byId(id).hidden = true; });
      } else state.pollTimer = setTimeout(refreshTask, 6000);
    }
  }
  function progressIndex(stage) {
    const mapped = { inventory: 'extracting', testing: 'validating', running: 'extracting' }[stage] || stage;
    return progress.findIndex(([key]) => key === mapped);
  }
  function renderJob(job) {
    const stopped = terminal.has(job.status) && job.status !== 'ready';
    const stage = job.status === 'ready' ? 'ready' : (job.stage || job.status);
    byId('job-title').textContent = job.title || '你的学习教材';
    byId('job-status').textContent = statusText(terminal.has(job.status) ? job.status : stage);
    byId('job-status').classList.toggle('is-error', stopped && job.status !== 'cancelled');
    byId('job-message').textContent = job.message || (job.status === 'queued' ? '资料已收到，等待处理。' : '正在按资料范围处理。');
    byId('job-kicker').textContent = job.status === 'ready' ? '制作完成' : '转换进度';
    byId('delete-job').textContent = '删除资料与成品';
    const stageIndex = progressIndex(stage);
    const events = Array.isArray(job.events) ? job.events : [];
    // Mark only stages evidenced by server events; do not invent percentages or elapsed progress.
    const reported = new Set(events.map(event => progressIndex(event.stage)).filter(index => index >= 0));
    const steps = progress.map(([key, title, detail], index) => {
      const node = el('li', 'progress-step');
      const done = !stopped && (job.status === 'ready' || (reported.has(index) && index < stageIndex));
      const current = !stopped && index === stageIndex;
      node.classList.toggle('is-done', done);
      node.classList.toggle('is-current', current);
      if (current) node.setAttribute('aria-current', 'step');
      node.append(el('span', 'progress-indicator', done ? '✓' : ''), el('span', '', title), el('small', '', detail));
      return node;
    });
    byId('progress-steps').replaceChildren(...steps);
    byId('event-list').replaceChildren();
    const recentEvents = events.slice(-60).reverse();
    recentEvents.forEach(event => {
      const item = el('li');
      const date = formatDate(event.at);
      if (date) { const time = el('time', '', date); item.append(time); }
      item.append(el('span', '', typeof event.message === 'string' ? event.message : statusText(event.stage)));
      byId('event-list').append(item);
    });
    byId('no-events').hidden = recentEvents.length > 0;
    byId('check-list').replaceChildren();
    const checks = Array.isArray(job.checks) ? job.checks : [];
    checks.forEach(check => {
      const item = el('li');
      const status = check.status === 'pass' ? 'pass' : check.status === 'fail' ? 'fail' : 'unverified';
      item.append(el('span', `check-label ${status}`, { pass: '通过', fail: '未通过', unverified: '未验证' }[status]));
      const info = el('div', '', check.name || '质量检查');
      if (check.detail) info.append(el('span', 'check-detail', check.detail));
      item.append(info);
      byId('check-list').append(item);
    });
    byId('job-checks').hidden = checks.length === 0;
    byId('download-job').hidden = job.status !== 'ready' || !job.downloadAvailable;
    byId('retry-job').hidden = !['needs_attention', 'failed', 'interrupted', 'cancelled'].includes(job.status);
    byId('retry-job').disabled = !state.config?.ready;
    byId('cancel-job').hidden = terminal.has(job.status);
    const expiry = formatDate(job.expiresAt);
    byId('job-expiry').textContent = expiry ? `本任务预计于 ${expiry} 到期清理。请在此前下载成品。` : '资料和成品会按服务规定的保留期限清理，请及时下载。';
    renderSavedTasks();
  }
  async function action(kind) {
    if (!state.task) return;
    const button = byId(`${kind}-job`);
    const task = state.task;
    button.disabled = true;
    showMessage('job-error', '');
    try {
      await api(`${taskPath(task)}/${kind}`, { method: 'POST', body: '{}' }, task);
      if (state.task?.id !== task.id) return;
      cancelPolling();
      await refreshTask();
    } catch (error) {
      showMessage('job-error', cleanError(error));
    } finally { button.disabled = false; }
  }
  function confirmAction(title, message, label) {
    return new Promise(resolve => {
      const dialog = byId('confirm-dialog');
      byId('confirm-title').textContent = title;
      byId('confirm-message').textContent = message;
      byId('confirm-yes').textContent = label;
      let resolved = false;
      const finish = value => {
        if (resolved) return;
        resolved = true;
        dialog.close();
        byId('confirm-yes').onclick = null;
        byId('confirm-no').onclick = null;
        dialog.oncancel = null;
        resolve(value);
      };
      byId('confirm-yes').onclick = () => finish(true);
      byId('confirm-no').onclick = () => finish(false);
      dialog.oncancel = event => { event.preventDefault(); finish(false); };
      dialog.showModal();
      byId('confirm-no').focus();
    });
  }
  async function deleteTask() {
    if (!state.task) return;
    const task = state.task;
    const accepted = await confirmAction('删除这次转换？', '将取消处理并删除服务上的原资料、成品和任务记录。已经下载到你的设备上的 HTML 不受影响。此操作无法撤销。', '确认删除');
    if (!accepted) return;
    byId('delete-job').disabled = true;
    try {
      try { await api(taskPath(task), { method: 'DELETE' }, task); }
      catch (error) { if (![401, 403, 404, 410].includes(error.httpStatus)) throw error; }
      state.tasks = state.tasks.filter(item => item.id !== task.id);
      if (state.task?.id === task.id) showPreparation();
      saveTasks();
      showMessage('global-message', '本次转换已删除，或已不再可访问。本机任务入口已移除。你下载的文件不受影响。');
    } catch (error) { showMessage('job-error', cleanError(error)); }
    finally { byId('delete-job').disabled = false; }
  }
  async function download() {
    if (!state.task) return;
    const task = state.task;
    const job = state.job;
    byId('download-job').disabled = true;
    showMessage('job-error', '');
    try {
      const response = await api(`${taskPath(task)}/download`, {}, task, 120000);
      const blob = await response.blob();
      if (!blob.size) throw new Error('Empty download');
      const url = URL.createObjectURL(blob);
      const anchor = el('a');
      anchor.href = url;
      const name = (job?.title || '交互学习教材').replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').slice(0, 100);
      anchor.download = `${name}.html`;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      showMessage('job-error', '');
    } catch (error) { showMessage('job-error', cleanError(error, '下载未完成，请检查连接后重试。')); }
    finally { byId('download-job').disabled = false; }
  }
  function showPreparation() {
    cancelPolling();
    state.requestVersion += 1;
    state.task = null;
    state.job = null;
    state.selectedId = null;
    saveTasks();
    byId('job-panel').hidden = true;
    byId('prepare-view').hidden = false;
    byId('workspace').scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  byId('file-input').addEventListener('change', event => { chooseFiles(event.target.files); event.target.value = ''; });
  const dropZone = byId('drop-zone');
  ['dragenter', 'dragover'].forEach(name => dropZone.addEventListener(name, event => { event.preventDefault(); dropZone.classList.add('is-dragging'); }));
  ['dragleave', 'drop'].forEach(name => dropZone.addEventListener(name, event => { event.preventDefault(); dropZone.classList.remove('is-dragging'); }));
  dropZone.addEventListener('drop', event => { if (event.dataTransfer) chooseFiles(event.dataTransfer.files); });
  document.addEventListener('dragover', event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
  document.addEventListener('drop', event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
  byId('file-input').addEventListener('focus', () => dropZone.classList.add('has-input-focus'));
  byId('file-input').addEventListener('blur', () => dropZone.classList.remove('has-input-focus'));
  byId('consent').addEventListener('change', updateSubmit);
  byId('access-code').addEventListener('input', updateSubmit);
  byId('conversion-form').addEventListener('submit', submit);
  byId('refresh-service').addEventListener('click', loadConfig);
  byId('material-mode').addEventListener('change', event => {
    const hints = {
      auto: '只上传一本教材时，默认按教材目录组织。', textbook: '完整展开教材，配套资料用于解释、解析与补充。',
      slides: '以标记的教师主课件组织学习内容，教材补充解释。', outline: '覆盖提纲各条目，结合教材展开实质讲解。',
      combined: '请标记主资料，并在补充要求中说明重要的主次关系。'
    };
    byId('mode-hint').textContent = hints[event.target.value];
  });
  byId('history-toggle').addEventListener('click', () => {
    const hidden = !byId('saved-tasks').hidden;
    byId('saved-tasks').hidden = hidden;
    byId('history-toggle').setAttribute('aria-expanded', String(!hidden));
    if (!hidden) byId('saved-tasks').scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
  byId('cancel-job').addEventListener('click', async () => {
    if (await confirmAction('取消本次转换？', '已完成的处理记录会保留，但本次转换将停止。你可以稍后重试，或主动删除资料。', '确认取消')) action('cancel');
  });
  byId('retry-job').addEventListener('click', () => action('retry'));
  byId('delete-job').addEventListener('click', deleteTask);
  byId('download-job').addEventListener('click', download);
  byId('new-job').addEventListener('click', showPreparation);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && state.task && (!state.job || !terminal.has(state.job.status))) { cancelPolling(); refreshTask(); }
  });
  window.addEventListener('online', () => { loadConfig(); if (state.task) { cancelPolling(); refreshTask(); } });
  loadTasks();
  renderSavedTasks();
  loadConfig().then(() => {
    const selected = state.tasks.find(task => task.id === state.selectedId);
    if (selected) openTask(selected);
  });
})();
