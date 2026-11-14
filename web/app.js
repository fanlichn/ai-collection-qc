async function api(url, options={}){const r=await fetch(url,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});if(!r.ok)throw new Error(await r.text());return r.json()}
function pill(s){return `<span class="pill ${s||''}">${s||'-'}</span>`}
let recordingKeyword = '';
let recordingRequest = 0;
let recordingFilter = {};
let recordingPage = 1;
const recordingPrevious = document.querySelector('#recordingPrevious');
const recordingNext = document.querySelector('#recordingNext');
const recordingPageStatus = document.querySelector('#recordingPageStatus');

async function loadRecordings() {
    const request = ++recordingRequest;
    const keyword = recordingKeyword;
    const query = new URLSearchParams({q: keyword, ...recordingFilter, page: recordingPage});
    const {rows, page, total, pages} = await api('/api/recordings?' + query);
    if (request !== recordingRequest) return;
    if (page > pages) {
        recordingPage = pages;
        return loadRecordings();
    }
    recordingPrevious.disabled = page <= 1;
    recordingNext.disabled = page >= pages;
    recordingPageStatus.textContent = `第 ${page} / ${pages} 页 · 共 ${total} 条`;
    document.querySelector('#rows').innerHTML = rows.map(r => `<tr>
        <td>${r.id}</td><td>${esc(r.filename)}</td><td>${esc(r.device_id)}</td><td>${esc(r.language || '-')}</td>
        <td>${pill(r.status)}</td><td>${r.unanswered ? '不评分' : (r.score ?? (r.risk_level === 'REVIEW' ? '未评级' : '-'))}</td>
        <td>${r.unanswered ? '未接通' : pill(r.risk_level || '-')}</td><td>${r.created_at ? new Date(r.created_at).toLocaleString() : ''}</td>
        <td><button onclick="detail(${r.id})">查看</button></td>
    </tr>`).join('') || `<tr><td colspan="9">${keyword || recordingFilter.value ? '没有匹配的录音' : '暂无录音'}</td></tr>`;
}

async function load() {
    try {
        const o = await api('/api/overview');
        total.textContent = o.total;
        completed.textContent = o.completed;
        pending.textContent = o.pending;
        failed.textContent = o.failed;
        avg.textContent = o.avg_score ?? '-';
        review.textContent = o.review_count;
        await loadRecordings();
        const es = await api('/api/employees');
        document.querySelector('#employees').innerHTML = es.map(e =>
            `<p>${esc(e.employee_code)} · ${esc(e.name)} · ${esc(e.team)} · ${esc(e.device_id || '未绑定')}</p>`
        ).join('') || '<p class="muted">暂无员工</p>';
    } catch (error) {
        console.error(error);
        alert('加载失败：' + error.message);
    }
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function normalizeSpokenDigits(text) {
    const digits = '零一二三四五六七八九';
    return text.replace(/[零一二三四五六七八九〇]/g,
        digit => digit === '〇' ? '0' : String(digits.indexOf(digit)));
}

function formatSpokenEmails(text) {
    const spokenEmail = /((?:邮箱(?:地址)?|电子邮件(?:地址)?|地址)\s*(?:是|为|[:：])\s*)([a-z0-9_+\-零一二三四五六七八九〇]+(?:[ \t]+[a-z0-9_+\-零一二三四五六七八九〇]+|[。.]?\r?\n[ \t]*[a-z0-9_+\-零一二三四五六七八九〇]+)*)[ \t]*(?:@|\bat\b|艾特)[ \t]*([a-z0-9-]+(?:[ \t]+[a-z0-9-]+)*)[ \t]*(?:\.|\bdot\b|点)[ \t]*(com\.cn|com|cn|net|org|edu|gov|io)(?![a-z0-9.-])/gi;
    return text.replace(spokenEmail, (original, label, user, domain, suffix) => {
        const username = normalizeSpokenDigits(user.replace(/[\s。]/g, ''));
        const hostname = domain.replace(/[ \t]/g, '');
        if (username.length > 64 || !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/i.test(hostname)) {
            return original;
        }
        return `${label}${username}@${hostname.toLowerCase()}.${suffix.toLowerCase()}`;
    });
}

function formatSpokenTrackingNumbers(text) {
    const tracking = /((?:快递单号|运单号|顺丰单号|顺丰快递单号)\s*(?:是|为|[:：])\s*)s[ \t]*f[ \t]*([0-9零一二三四五六七八九〇]+(?:[ \t]+[0-9零一二三四五六七八九〇]+)*)(?:[。.][ \t]*\r?\n[ \t]*([0-9零一二三四五六七八九〇]+(?:[ \t]+[0-9零一二三四五六七八九〇]+)*)(?=[，。！？、,;；\r\n]|$))?(?![a-z0-9零一二三四五六七八九〇-])/gi;
    return text.replace(tracking, (original, label, first, continued = '') => {
        const number = normalizeSpokenDigits((first + continued).replace(/[ \t]/g, ''));
        if (!/^\d{10,15}$/.test(number)) return original;
        return `${label}SF${number}`;
    });
}

function renderTranscript(transcript) {
    if (!transcript) return '<p class="muted">尚无转录文本</p>';
    const segments = transcript.segments.map(segment => `
        <div class="segment">
            <button type="button" class="seek-audio" data-start="${Number(segment.start)}">${esc(segment.start)}s–${esc(segment.end)}s</button>
            ${esc(segment.text)}
        </div>`).join('');
    const text = formatSpokenTrackingNumbers(formatSpokenEmails(transcript.text));
    return `<pre>${esc(text)}</pre>${segments}`;
}

function setupTranscript(id, savedTranscript, eligible) {
    const panel = document.querySelector('#transcriptPanel');
    const dialog = document.querySelector('#detail');
    const audio = panel.querySelector('audio');
    const button = panel.querySelector('.start-comparison');
    const message = panel.querySelector('.comparison-status');
    const output = panel.querySelector('.transcript-result');
    const endpoint = `/api/recordings/${id}`;
    const active = () => panel.isConnected && dialog.open;
    const audioStatus = panel.querySelector('.audio-status');
    let pendingSeek = null;
    audio.addEventListener('loadedmetadata', () => {
        if (pendingSeek !== null) {
            audio.currentTime = pendingSeek;
            pendingSeek = null;
        }
    });
    const labels = {
        PENDING: '已排队，首次运行可能需要下载模型。',
        RUNNING: '正在转文字…',
        FAILED: '转文字失败，可以重试。',
    };

    async function refresh() {
        try {
            const comparison = await api(endpoint + '/comparison');
            if (!active()) return;
            const waiting = ['PENDING', 'RUNNING'].includes(comparison.status);
            message.textContent = labels[comparison.status] ?? '';
            if (comparison.result) output.innerHTML = renderTranscript(comparison.result);
            button.disabled = waiting || !eligible;
            button.hidden = comparison.status === 'COMPLETED' || !eligible;
            if (waiting) setTimeout(() => { if (active()) refresh(); }, 3000);
        } catch {
            if (active()) {
                message.textContent = '暂时无法读取转录状态，请关闭详情后重试。';
            }
        }
    }

    button.addEventListener('click', async () => {
        button.disabled = true;
        message.textContent = '正在提交转文字任务…';
        try {
            await api(endpoint + '/comparison', {method: 'POST'});
            if (active()) await refresh();
        } catch {
            if (active()) {
                message.textContent = '无法提交转录任务，请稍后重试。';
                button.disabled = false;
            }
        }
    });
    panel.addEventListener('click', async event => {
        const seek = event.target.closest('.seek-audio');
        if (!seek && !event.target.closest('.load-audio')) return;
        try {
            if (!audio.getAttribute('src') || audio.error) {
                const {url} = await api(endpoint + '/audio');
                if (!active()) return;
                audio.src = url;
            }
            audio.hidden = false;
            audioStatus.textContent = '';
            if (seek) {
                const start = Number(seek.dataset.start);
                if (audio.readyState >= 1) audio.currentTime = start;
                else pendingSeek = start;
            }
            await audio.play();
        } catch {
            audioStatus.textContent = '播放未开始，请使用播放器的播放按钮或重试。';
        }
    });
    dialog.addEventListener('close', () => audio.pause(), {once: true});
    output.innerHTML = renderTranscript(savedTranscript);
    refresh();
}
async function detail(id){const d=await api('/api/recordings/'+id);let h=`<p><b>对象：</b>${esc(d.recording.object_key)}</p><p><b>状态：</b>${pill(d.recording.status)} <b>语言：</b>${d.recording.language||'-'}</p>`;if(d.recording.unanswered){h+='<h3>质检结论：未接通 · 不评分</h3><p>根据录音文件的等待标记判定。可播放原始录音核对。</p>'}else if(d.analysis){h+=`<h3>质检结论：${d.analysis.score==null?'未评级':d.analysis.score+'/100'} · ${pill(d.analysis.risk_level)}</h3><p>${esc(d.analysis.summary)}</p><pre>${esc(JSON.stringify(d.analysis.result,null,2))}</pre>`;if(d.analysis.human_review_required){h+=`<h3>人工复核</h3><textarea id="note" placeholder="复核说明" style="width:100%;min-height:70px"></textarea><p><button onclick="review(${id},'CONFIRMED')">确认违规/问题</button> <button onclick="review(${id},'REJECTED')">驳回 AI 判断</button> <button onclick="review(${id},'NEEDS_MORE_INFO')">需要更多信息</button></p>`}}h+=`<section id="transcriptPanel">
    <h3>录音转文字</h3>
    <div class="comparison-actions">
        <button type="button" class="start-comparison" disabled>录音转文字</button>
        <button type="button" class="load-audio">播放原始录音</button>
        <span class="muted comparison-status" role="status"></span>
    </div>
    <audio controls hidden></audio>
    <p class="muted audio-status" role="status"></p>
    <div class="transcript-result"></div>
</section>`;
document.querySelector('#detailBody').innerHTML=h;
document.querySelector('#detail').showModal();
setupTranscript(id, d.transcript, d.recording.status === 'COMPLETED' && !d.recording.unanswered);
}
async function review(id,decision){await api(`/api/recordings/${id}/review`,{method:'POST',body:JSON.stringify({decision,note:document.querySelector('#note')?.value||''})});alert('复核已保存');document.querySelector('#detail').close();load()}
const volumeForm = document.querySelector('#callVolumeForm');
const volumePeriod = document.querySelector('#callVolumePeriod');
const volumeDay = document.querySelector('#callVolumeDay');
const volumeMonth = document.querySelector('#callVolumeMonth');
const volumeStatus = document.querySelector('#callVolumeStatus');
const volumeResults = document.querySelector('#callVolumeResults');
const volumeCharts = document.querySelector('#callVolumeCharts');
let volumeRequest = 0;

function ringSlice(start, span) {
    const steps = Math.max(1, Math.ceil(span * 120));
    const arc = radius => Array.from({length: steps + 1}, (_, i) => {
        const angle = 2 * Math.PI * (start + span * i / steps) - Math.PI / 2;
        return `${(50 + radius * Math.cos(angle)).toFixed(3)}% ${(50 + radius * Math.sin(angle)).toFixed(3)}%`;
    });
    return `polygon(${arc(47).concat(arc(33).reverse()).join(',')})`;
}

function renderCallVolume(report, period) {
    const colors = ['#2563eb', '#08988b', '#8b5cf6', '#d97706', '#db4772', '#477ab6', '#647e32'];
    const employeeLabel = row => esc(row.code ? `${row.name}（${row.code}）` : row.name);
    const formatPercent = new Intl.NumberFormat('zh-CN', {style: 'percent', maximumFractionDigits: 1});
    let start = 0;
    const items = report.rows.map((row, index) => {
        const share = report.total ? row.total / report.total : 0;
        const color = row.id === null ? '#94a3b8' : colors[index % colors.length];
        const gap = share === 1 ? 0 : Math.min(0.005, share / 5);
        const shape = share ? ringSlice(start + gap / 2, share - gap) : '';
        start += share;
        return {row, color, shape, percent: formatPercent.format(share)};
    });
    const slices = items.map(({color, shape}, index) => shape ? `
        <div class="call-volume-slice" data-index="${index}" style="--slice-color:${color};clip-path:${shape}"></div>` : '').join('');
    const legend = items.map(({row, color, percent}, index) => `<li>
        <button type="button" class="call-volume-key" data-index="${index}" aria-label="${employeeLabel(row)}，占比 ${percent}，拨打 ${row.total} 通">
            <span class="call-volume-dot" style="--slice-color:${color}"></span>
            <span>${employeeLabel(row)}</span>
            <strong>${row.total} 通</strong>
        </button>
    </li>`).join('');
    let html = `<div class="call-volume-chart">
        <div class="call-volume-ring${report.total ? '' : ' is-empty'}" aria-hidden="true">
            ${slices}
            <div class="call-volume-center"><span>总拨打数</span><strong>${report.total} 通</strong></div>
        </div>
        ${legend ? `<div class="call-volume-breakdown">
            <div class="call-volume-legend-heading"><span>员工</span><span>拨打数</span></div>
            <ul class="call-volume-legend">${legend}</ul>
        </div>` : ''}
    </div>`;
    if (period === 'month' && report.rows.length) {
        const heading = report.days.map(day => `<th scope="col">${esc(day.slice(8))}日</th>`).join('');
        const rows = report.rows.map(row => `<tr><th scope="row">${employeeLabel(row)}</th>
            <td>${row.total}</td>${row.counts.map(count => `<td>${count}</td>`).join('')}</tr>`).join('');
        html += `<div class="table-wrap"><table class="call-volume-table">
            <caption>每日明细</caption>
            <thead><tr><th scope="col">员工</th><th scope="col">合计</th>${heading}</tr></thead>
            <tbody>${rows}</tbody>
        </table></div>`;
    }
    volumeResults.innerHTML = html;
    const center = volumeResults.querySelector('.call-volume-center');
    const centerLabel = center.querySelector('span');
    const centerValue = center.querySelector('strong');
    let highlighted = [];
    function highlight(index) {
        for (const element of highlighted) element.classList.remove('is-highlighted');
        highlighted = index === null ? [] : [...volumeResults.querySelectorAll(`[data-index="${index}"]`)];
        for (const element of highlighted) element.classList.add('is-highlighted');
        const item = items[index];
        centerLabel.textContent = item ? item.row.name : '总拨打数';
        centerValue.textContent = item ? item.percent : `${report.total} 通`;
    }
    for (const element of volumeResults.querySelectorAll('.call-volume-slice, .call-volume-key')) {
        const index = Number(element.dataset.index);
        element.addEventListener('pointerenter', () => highlight(index));
        element.addEventListener('pointerleave', () => highlight(null));
        element.addEventListener('focus', () => highlight(index));
        element.addEventListener('blur', () => highlight(null));
        if (element.matches('button')) element.addEventListener('click', () => highlight(index));
    }
}

function showChartRecordings(filters, label) {
    recordingFilter = filters;
    recordingPage = 1;
    recordingKeyword = '';
    document.querySelector('#recordingKeyword').value = '';
    document.querySelector('#recordingChartFilter').textContent = label;
    loadRecordings().catch(() => alert('加载录音失败，请稍后重试。'));
    document.querySelector('#recordingSearch').scrollIntoView({block: 'center'});
}

function renderVolumeCharts(report, period) {
    const rows = report.rows;
    const issues = report.issues;
    const maximum = Math.max(1, ...issues.map(item => item.pending + item.confirmed));
    volumeCharts.innerHTML = `
        <section class="volume-chart-panel">
            <div class="panel-title"><h3>每日通话趋势</h3>
                <select class="trend-employee" aria-label="选择员工"><option value="">全部录音</option>
                    ${rows.map(row => `<option value="${row.id ?? 0}">${esc(row.name)}${row.code ? `（${esc(row.code)}）` : ''}</option>`).join('')}
                </select></div>
            <div class="trend-plot"></div>
        </section>
        <section class="volume-chart-panel">
            <h3>常见质检问题</h3>
            ${issues.length ? `<p class="issue-legend"><span>待复核</span><span>人工确认</span></p>
                <ul class="issue-bars">${issues.map((item, index) => `<li>
                    <button type="button" class="issue-row" data-index="${index}">
                        <span>${esc(item.label)}</span><strong>${item.pending + item.confirmed} 条</strong>
                        <span class="issue-track" aria-hidden="true">
                            <span class="issue-pending" style="width:${item.pending / maximum * 100}%"></span>
                            <span class="issue-confirmed" style="width:${item.confirmed / maximum * 100}%"></span>
                        </span>
                        <small>待复核 ${item.pending} · 人工确认 ${item.confirmed}</small>
                    </button>
                </li>`).join('')}</ul>` : '<p class="muted">所选时段暂无质检问题。</p>'}
        </section>`;
    const picker = volumeCharts.querySelector('.trend-employee');
    const plot = volumeCharts.querySelector('.trend-plot');
    function drawTrend() {
        const employee = picker.value;
        const row = rows.find(item => String(item.id ?? 0) === employee);
        const counts = row ? row.counts : report.days.map((_, index) => rows.reduce((total, item) => total + item.counts[index], 0));
        const peak = Math.max(1, ...counts);
        const coordinates = counts.map((count, i) => [
            counts.length === 1 ? 50 : 6 + 88 * i / (counts.length - 1),
            90 - count / peak * 76,
        ]);
        const lines = coordinates.slice(1).map(([x, y], i) => {
            const [left, top] = coordinates[i];
            const width = Math.hypot(x - left, (y - top) * 0.46);
            const angle = Math.atan2((y - top) * 0.46, x - left);
            return `<span class="trend-line" style="left:${left}%;top:${top}%;width:${width}%;transform:rotate(${angle}rad)"></span>`;
        }).join('');
        plot.innerHTML = `<div class="trend-area">${lines}
            ${coordinates.map(([x, y], i) => `<button type="button" class="trend-dot" style="left:${x}%;top:${y}%"
                data-index="${i}" aria-label="${esc(report.days[i])}，${counts[i]} 通">
                <span>${esc(report.days[i].slice(5))} · ${counts[i]} 通</span></button>`).join('')}
            </div><div class="trend-axis">${report.days.map((day, i) =>
                (i === 0 || i === report.days.length - 1 || ((i + 1) % 5 === 0 && i < report.days.length - 3))
                    ? `<span style="left:${coordinates[i][0]}%">${esc(day.slice(5))}</span>` : '').join('')}</div>`;
        for (const button of plot.querySelectorAll('.trend-dot')) {
            button.addEventListener('click', () => {
                const value = report.days[Number(button.dataset.index)];
                const filters = {period: 'day', value};
                if (employee !== '') filters.employee = employee;
                showChartRecordings(filters, row ? `${value} · ${row.name}` : value);
            });
        }
    }
    picker.addEventListener('change', drawTrend);
    drawTrend();
    for (const button of volumeCharts.querySelectorAll('.issue-row')) {
        button.addEventListener('click', () => {
            const issue = issues[Number(button.dataset.index)].label;
            const value = report.days[0];
            showChartRecordings({period, value, issue}, `${period === 'month' ? value.slice(0, 7) : value} · ${issue}`);
        });
    }
}

async function loadCallVolume() {
    const request = ++volumeRequest;
    const period = volumePeriod.value;
    const selected = period === 'month' ? volumeMonth.value : volumeDay.value;
    const value = period === 'month' ? `${selected}-01` : selected;
    volumeStatus.textContent = '正在查询…';
    volumeResults.innerHTML = '';
    volumeCharts.innerHTML = '';
    try {
        const report = await api('/api/call-volume?' + new URLSearchParams({period, value, include_issues: 'true'}));
        if (request !== volumeRequest) return;
        volumeStatus.textContent = report.total ? `${selected} · 共 ${report.total} 通` : `${selected} · 暂无录音`;
        renderCallVolume(report, period);
        renderVolumeCharts(report, period);
    } catch {
        if (request === volumeRequest) volumeStatus.textContent = '查询失败，请稍后重试。';
    }
}

const reportToday = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).formatToParts(new Date());
const reportDate = ['year', 'month', 'day'].map(type => reportToday.find(part => part.type === type).value);
volumeDay.value = reportDate.join('-');
volumeMonth.value = reportDate.slice(0, 2).join('-');
volumePeriod.addEventListener('change', () => {
    const monthly = volumePeriod.value === 'month';
    document.querySelector('#callVolumeDayLabel').hidden = monthly;
    document.querySelector('#callVolumeMonthLabel').hidden = !monthly;
    volumeDay.disabled = monthly;
    volumeMonth.disabled = !monthly;
    if (volumeForm.checkValidity()) loadCallVolume();
});
volumeForm.addEventListener('submit', event => {
    event.preventDefault();
    loadCallVolume();
});
loadCallVolume();

const recordingSearch = document.querySelector('#recordingSearch');
recordingSearch.addEventListener('submit', event => {
    event.preventDefault();
    recordingKeyword = document.querySelector('#recordingKeyword').value.trim();
    recordingPage = 1;
    loadRecordings().catch(() => alert('搜索失败，请稍后重试。'));
});
recordingSearch.addEventListener('reset', () => {
    recordingKeyword = '';
    recordingFilter = {};
    recordingPage = 1;
    document.querySelector('#recordingChartFilter').textContent = '';
    loadRecordings().catch(() => alert('加载录音失败，请稍后重试。'));
});
for (const [button, step] of [[recordingPrevious, -1], [recordingNext, 1]]) {
    button.addEventListener('click', async () => {
        const previous = recordingPage;
        recordingPage += step;
        const target = recordingPage;
        recordingPrevious.disabled = recordingNext.disabled = true;
        try {
            await loadRecordings();
        } catch {
            if (recordingPage === target) {
                recordingPage = previous;
                await loadRecordings().catch(() => { recordingPageStatus.textContent = '加载失败，请刷新重试。'; });
            }
        }
    });
}
document.querySelector('#emp').addEventListener('submit',async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));await api('/api/employees',{method:'POST',body:JSON.stringify(data)});e.target.reset();load()});load();setInterval(load,30000);
