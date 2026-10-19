'use strict';
const $ = id => document.getElementById(id);
let apiKey = sessionStorage.getItem('campusorg-key') || '';
let history = [];
let busy = false;
let maxUploadMB = 25;
const dateLabel = value => value ? new Intl.DateTimeFormat('id-ID', {day:'numeric', month:'long', year:'numeric'}).format(new Date(value + 'T12:00:00')) : 'Tanggal belum tersedia';
$('api-key').value = apiKey;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 130000);
  try {
    const headers = new Headers(options.headers || {});
    if (apiKey) headers.set('X-API-Key', apiKey);
    const response = await fetch(path, {...options, headers, signal:controller.signal});
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const detail = typeof payload.detail === 'string' ? payload.detail : `Permintaan gagal (${response.status}). Periksa isian dan coba kembali.`;
      throw new Error(detail);
    }
    return response;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Waktu tunggu habis. Coba kembali atau periksa koneksi layanan AI.');
    throw error;
  } finally { clearTimeout(timer); }
}

function message(text, error = false) {
  $('global-message').textContent = text;
  $('global-message').classList.toggle('error', error);
  $('global-message').hidden = !text;
}

function pdfLink(url, label) {
  const link = node('a', label);
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener';
  link.addEventListener('click', async event => {
    if (!apiKey) return;
    event.preventDefault();
    const tab = window.open('about:blank', '_blank');
    if (tab) tab.opener = null;
    try {
      const [path, fragment] = url.split('#');
      const response = await api(path);
      const blobURL = URL.createObjectURL(await response.blob());
      if (tab) tab.location.href = blobURL + (fragment ? '#' + fragment : '');
      else { URL.revokeObjectURL(blobURL); throw new Error('Izinkan tab baru untuk melihat PDF.'); }
      setTimeout(() => URL.revokeObjectURL(blobURL), 300000);
    } catch (error) { if (tab) tab.close(); message(error.message, true); }
  });
  return link;
}

async function refresh() {
  try {
    const [statusResponse, documentResponse] = await Promise.all([api('/status'), api('/documents')]);
    const status = (await statusResponse.json()).data;
    const documents = (await documentResponse.json()).data;
    $('stat-docs').textContent = status.total_documents;
    $('document-count').textContent = status.total_documents;
    $('stat-pages').textContent = status.total_pages;
    $('stat-chunks').textContent = status.total_chunks;
    maxUploadMB = status.max_upload_mb;
    $('upload-limit').textContent = `(maks. ${maxUploadMB} MB/berkas)`;
    const ai = status.ai || {provider:'ollama', model_ready:status.ollama.model_ready};
    const aiReady = status.answer_mode !== 'extractive' && ai.model_ready;
    const aiLabel = ai.provider === 'gemini' ? `Gemini online (${ai.model})` : 'AI lokal';
    $('service-status').textContent = aiReady ? `Arsip siap · ${aiLabel} terhubung` : 'Arsip siap · Kutipan sumber tersedia';
    $('mode-label').textContent = aiReady ? 'AI + SUMBER ARSIP' : 'KUTIPAN SUMBER';
    if (ai.provider === 'gemini' && !ai.configured && status.answer_mode !== 'extractive') message('Gemini belum aktif. Isi GEMINI_API_KEY pada .env lalu restart server; kutipan arsip tetap tersedia.');
    else if (['ollama', 'gemini'].includes(status.answer_mode) && !aiReady) message('Layanan AI belum siap. Periksa koneksi dan konfigurasi layanan AI.', true);
    else if (status.import_errors.length) message('Ada dataset yang gagal diimpor: ' + status.import_errors.map(e => e.file + ': ' + e.error).join('; '), true);
    else if (status.import_warnings.length) message(status.import_warnings.map(w => w.file + ': ' + w.warning).join('; '));
    else if (!documents.length) message('Arsip masih kosong. Tambahkan PDF untuk memulai.');
    else message('');
    $('documents').replaceChildren();
    const previousDocument = $('document-filter').value;
    $('document-filter').replaceChildren(new Option('Semua rapat', ''));
    for (const document of documents) {
      const title = document.meeting_number ? `Rapat Besar ${String(document.meeting_number).padStart(2,'0')}` : document.nama_file;
      const link = pdfLink(`/documents/${document.id}/pdf`, '');
      link.className = 'document';
      link.title = document.nama_file;
      link.append(node('span', 'PDF', 'document-icon'));
      const info = node('span');
      const contained = document.meetings.length > 1 ? ` · memuat ${document.meetings.length} rapat` : '';
      info.append(node('div', title, 'document-name'), node('div', `${dateLabel(document.meeting_date)} · ${document.total_pages} hal.${contained}`, 'document-date'));
      link.append(info);
      $('documents').append(link);
      $('document-filter').add(new Option(`${title} · ${document.tahun}`, document.id));
    }
    if ([...$('document-filter').options].some(o => o.value === previousDocument)) $('document-filter').value = previousDocument;
    const previousDivision = $('division').value;
    $('division').replaceChildren(new Option('Semua divisi', ''));
    for (const division of status.divisi) $('division').add(new Option(division, division));
    if ([...$('division').options].some(o => o.value === previousDivision)) $('division').value = previousDivision;
  } catch (error) {
    $('service-status').textContent = 'Koneksi perlu diperiksa';
    message(error.message, true);
  }
}

$('save-key').addEventListener('click', () => {
  apiKey = $('api-key').value.trim();
  if (apiKey) sessionStorage.setItem('campusorg-key', apiKey);
  else sessionStorage.removeItem('campusorg-key');
  refresh();
});
$('upload-toggle').addEventListener('click', () => {
  const show = $('upload-panel').hidden;
  $('upload-panel').hidden = !show;
  $('upload-toggle').setAttribute('aria-expanded', String(show));
});
$('upload-panel').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type=submit]');
  button.disabled = true;
  const results = [];
  const files = [...$('files').files];
  try {
    for (const file of files) {
      if (file.size > maxUploadMB * 1024 * 1024) { results.push(`${file.name}: melebihi ${maxUploadMB} MB.`); continue; }
      $('upload-result').textContent = `Memproses ${file.name}…`;
      const form = new FormData();
      form.append('file', file);
      form.append('divisi', $('upload-division').value.trim());
      form.append('tahun', $('upload-year').value);
      try {
        const result = await (await api('/upload', {method:'POST', body:form})).json();
        results.push(`${file.name}: ${result.data.duplicate ? 'sudah terindeks' : result.data.total_chunks + ' potongan diimpor'}${result.data.empty_pages.length ? '; halaman tanpa teks: ' + result.data.empty_pages.join(', ') : ''}.${result.data.warning ? ' '+result.data.warning : ''}`);
      } catch (error) { results.push(`${file.name}: ${error.message}`); }
    }
    $('upload-result').textContent = results.join('\n');
    $('files').value = '';
    await refresh();
  } finally { button.disabled = false; }
});

function renderResult(data) {
  $('answer-section').hidden = false;
  $('suggestions').hidden = true;
  $('answer-question').textContent = data.query_asli;
  const modes = {gemini:'Jawaban Gemini dengan rujukan', ollama:'Jawaban AI dengan rujukan', source_match:'Jawaban langsung dari arsip', extractive:'Kutipan asli arsip', no_evidence:'Bukti belum ditemukan'};
  $('answer-meta').textContent = `${modes[data.metadata.answer_mode] || 'Hasil arsip'} · ${data.metadata.retrieval} · ${(data.metadata.duration_ms/1000).toFixed(1)} detik`;
  $('answer-warning').textContent = data.metadata.warning || '';
  $('answer-warning').hidden = !data.metadata.warning;
  $('answer-text').textContent = data.jawaban_ai;
  $('source-count').textContent = `(${data.referensi.length})`;
  $('sources').replaceChildren();
  if (!data.referensi.length) $('sources').append(node('p', 'Tidak ada sumber yang memenuhi pencarian.', 'subtle'));
  for (const source of data.referensi) {
    const card = node('div', undefined, 'source-card');
    card.append(pdfLink(source.url, `[${source.id}] ${source.file} ↗`));
    card.append(node('div', `Halaman ${source.halaman} · ${source.divisi} · ${dateLabel(source.tanggal_rapat)}`, 'source-meta'));
    const details = node('details');
    details.append(node('summary', 'Periksa kutipan'), node('pre', source.kutipan));
    card.append(details);
    $('sources').append(card);
  }
  $('answer-section').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth', block:'start'});
}

$('ask-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const question = $('question').value.trim();
  if (question.length < 3) return;
  busy = true;
  $('ask-button').disabled = true;
  $('ask-form').setAttribute('aria-busy', 'true');
  $('ask-button').textContent = 'Menelusuri…';
  message('');
  try {
    const payload = {pertanyaan:question, history:history.slice(-6)};
    if ($('division').value) payload.divisi = $('division').value;
    if ($('document-filter').value) payload.document_id = Number($('document-filter').value);
    const result = await (await api('/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)})).json();
    renderResult(result.data);
    // Only store compact generated replies; long raw quotes are not conversation history.
    history.push({role:'user',content:question});
    if (['ollama', 'gemini'].includes(result.data.metadata.answer_mode)) history.push({role:'assistant',content:result.data.jawaban_ai.slice(0,4000)});
    history = history.slice(-6);
  } catch (error) { message(error.message, true); }
  finally {
    busy = false;
    $('ask-button').disabled = false;
    $('ask-button').textContent = 'Telusuri arsip ↗';
    $('ask-form').removeAttribute('aria-busy');
  }
});
$('question').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('ask-form').requestSubmit(); }
});
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => {
  $('question').value = button.dataset.question;
  $('question').focus();
  $('ask-form').requestSubmit();
}));
$('reset-chat').addEventListener('click', () => {
  history = [];
  $('answer-section').hidden = true;
  $('suggestions').hidden = false;
  $('question').value = '';
  $('question').focus();
});
for (const id of ['division','document-filter']) $(id).addEventListener('change', () => { history = []; });
refresh();
