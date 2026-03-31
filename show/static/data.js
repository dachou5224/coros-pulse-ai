/**
 * Load Weekly_Report and Activities snapshots.
 * 默认优先读同源 JSON；也支持通过 query/window 参数覆盖为 JSON 或 CSV。
 */
(function (global) {
    var DEFAULT_WEEKLY_JSON_URL = './data/weekly_report.json';
    var DEFAULT_ACTIVITY_JSON_URL = './data/activities.json';
    var DEFAULT_WEEKLY_CSV_URL = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQKYBbug9yQhYtejoO-9OMKXYQfA1Ju4ReO2YvYb7kqhWlrczvSrnHCmK_YBc5B6olsbBfUoP2Jbn5b/pub?gid=774375516&single=true&output=csv';
    var STATIC_TRAINING_PLAN = {
        phases: [
            {
                id: 'p0',
                name: '第一期 · 基础',
                start: '2026-05-01',
                end: '2026-05-31',
                weeklyKm: '50-55 km',
                longRun: '16-18 km',
                keyItems: [
                    { tag: '轻松跑', text: '全程 HR < 145，以心率为锚点，不追配速数字。' },
                    { tag: '长跑', text: '16-18 km，全程 HR < 150，不得加速。' },
                    { tag: '步伐训练', text: '轻松跑后 8×20s 加速，激活神经肌肉系统。' }
                ],
                weekRhythm: ['二 轻松跑', '三 轻松+步伐', '四 轻松跑', '日 长跑'],
                note: '五月以热适应和有氧地基为主，不安排高强度。'
            },
            {
                id: 'p1',
                name: '第二期 · 构建',
                start: '2026-06-01',
                end: '2026-07-06',
                weeklyKm: '55-65 km',
                longRun: '18-22 km',
                keyItems: [
                    { tag: '节奏跑', text: '每周一次阈值段 4-5 km，HR 165-172。' },
                    { tag: '马配速跑', text: '5-6 km @ 5\'20"，建立比赛配速记忆。' },
                    { tag: '长跑', text: '18-22 km，HR < 150，六月高温下优先控心率。' }
                ],
                weekRhythm: ['二 节奏跑', '四 马配速跑', '日 长跑'],
                note: '六月高温期，质量课宁可移到跑步机，也不要硬扛配速。'
            },
            {
                id: 'p2',
                name: '第三期 · 发展',
                start: '2026-07-07',
                end: '2026-08-10',
                weeklyKm: '55-65 km',
                longRun: '22-24 km',
                keyItems: [
                    { tag: '间歇训练', text: '5-6×1000m @ 4\'20"-4\'30"，提升最大摄氧量。' },
                    { tag: '节奏跑', text: '6-8 km 阈值段，双质量周必须留足恢复。' },
                    { tag: '长跑', text: '22-24 km，清晨完成，HR 上限 152。' }
                ],
                weekRhythm: ['二 间歇训练', '四 节奏跑', '日 长跑'],
                note: '七月是高风险月，晨脉和睡眠异常时直接降级为恢复周。'
            },
            {
                id: 'p3',
                name: '第四期 · 专项',
                start: '2026-08-11',
                end: '2026-09-07',
                weeklyKm: '60-65 km',
                longRun: '24-26 km',
                keyItems: [
                    { tag: '半马配速', text: '3-4×4 km @ 4\'44"-4\'50"，建立专项速度感。' },
                    { tag: '马配速长跑', text: '20 km 总量中 12 km @ 5\'20"，模拟专项疲劳。' },
                    { tag: '长跑', text: '24-26 km，后 8 km 切入马配速。' }
                ],
                weekRhythm: ['二 半马配速', '四 马配速长跑', '日 长跑'],
                note: '八月底气温回落，是把夏训储备兑现为速度的关键窗口。'
            },
            {
                id: 'p4',
                name: '第五期 · 减量',
                start: '2026-09-08',
                end: '2026-09-28',
                weeklyKm: '25-45 km',
                longRun: '按减量周调整',
                keyItems: [
                    { tag: '减量', text: '按 70% / 50% / 30% 三周递减，保留神经激活。' },
                    { tag: '马配速提醒', text: '保留短段马配速刺激，不再堆体能。' },
                    { tag: '恢复', text: '睡眠和补给优先，腿部新鲜度高于总里程。' }
                ],
                weekRhythm: ['保留短刺激', '降低总量', '比赛周蓄力'],
                note: '减量期的关键不是练更多，而是把疲劳彻底卸掉。'
            }
        ]
    };

    function getDataUrl() {
        var params = new URLSearchParams(location.search);
        return params.get('data') || global.DATA_URL || DEFAULT_WEEKLY_JSON_URL || DEFAULT_WEEKLY_CSV_URL;
    }

    function getActivityAdviceUrl() {
        var params = new URLSearchParams(location.search);
        return params.get('activity_advice') || global.ACTIVITY_ADVICE_URL || DEFAULT_ACTIVITY_JSON_URL;
    }

    function num(s) {
        if (s == null || s === '') return NaN;
        var t = String(s).replace(/,/g, '').trim();
        return parseFloat(t);
    }

    function parseDate(s) {
        if (!s) return null;
        var d = new Date(s);
        return isNaN(d.getTime()) ? null : d;
    }

    function normalizeRow(row, headers) {
        var out = {};
        headers.forEach(function (h) {
            var v = row[h];
            if (v === undefined) return;
            if (h === 'Week Start' || h === 'Week End') {
                out[h] = parseDate(v);
                out[h + '_raw'] = v;
            } else if (h === 'LSD Decouple') {
                var s = String(v).replace(/%/g, '').trim();
                out[h] = num(s);
                if (isNaN(out[h])) out[h] = 0;
            } else if (['Distance (km)', 'Weekly Load', 'Fitness (CTL)', 'Form (TSB)', 'VDOT'].indexOf(h) >= 0) {
                out[h] = num(v);
                if (isNaN(out[h])) out[h] = 0;
            } else if (h === 'Coach Advice' || h === 'Coach advice') {
                out['Coach Advice'] = v;
            } else if (['本周总评', '核心诊断', '下周药方'].indexOf(h) >= 0) {
                out[h] = v;
            } else {
                out[h] = v;
            }
        });
        // 若 Coach Advice 为空但有三段解析列，合并供展示
        if (!out['Coach Advice'] && (out['本周总评'] || out['核心诊断'] || out['下周药方'])) {
            var parts = [];
            if (out['本周总评']) parts.push(out['本周总评']);
            if (out['核心诊断']) parts.push(out['核心诊断']);
            if (out['下周药方']) parts.push(out['下周药方']);
            out['Coach Advice'] = parts.join('\n\n');
        }
        return out;
    }

    function sortByWeekStartDesc(rows) {
        return rows.slice().sort(function (a, b) {
            var t1 = a['Week Start'] && a['Week Start'].getTime ? a['Week Start'].getTime() : 0;
            var t2 = b['Week Start'] && b['Week Start'].getTime ? b['Week Start'].getTime() : 0;
            return t2 - t1;
        });
    }

    function sortByWeekStartAsc(rows) {
        return rows.slice().sort(function (a, b) {
            var t1 = a['Week Start'] && a['Week Start'].getTime ? a['Week Start'].getTime() : 0;
            var t2 = b['Week Start'] && b['Week Start'].getTime ? b['Week Start'].getTime() : 0;
            return t1 - t2;
        });
    }

    function loadJson(url) {
        return fetch(url).then(function (r) {
            if (!r.ok) throw new Error(r.statusText);
            return r.json();
        });
    }

    function normalizeJsonRows(data, normalizer, sorter) {
        var rows = Array.isArray(data) ? data : (data.rows || data.data || []);
        if (!rows.length) return [];
        var headers = Object.keys(typeof rows[0] === 'object' ? rows[0] : {});
        rows = rows.map(function (row) { return normalizer(row, headers); });
        return sorter(rows);
    }

    function loadCsv(url) {
        return fetch(url).then(function (r) {
            if (!r.ok) throw new Error(r.statusText);
            return r.text();
        }).then(function (text) {
            if (typeof Papa === 'undefined') {
                throw new Error('PapaParse required for CSV. Include: <script src="https://cdn.jsdelivr.net/npm/papaparse@5.4.1/papaparse.min.js"></script>');
            }
            var parsed = Papa.parse(text, { header: true, skipEmptyLines: true });
            var headers = parsed.meta.fields || [];
            var rows = (parsed.data || []).map(function (row) { return normalizeRow(row, headers); });
            return sortByWeekStartDesc(rows);
        });
    }

    function loadData() {
        var url = getDataUrl();
        if (/\.json$/i.test(url)) {
            return loadJson(url).then(function (data) {
                return normalizeJsonRows(data, normalizeRow, sortByWeekStartDesc);
            });
        }
        return loadCsv(url);
    }

    function normalizeActivityAdviceRow(row, headers) {
        var out = {};
        headers.forEach(function (h) {
            var v = row[h];
            if (v === undefined) return;
            if (h === 'Date') {
                out[h] = parseDate(v);
                out[h + '_raw'] = v;
            } else {
                out[h] = v;
            }
        });
        // 优先用 Advice，否则用 总评（activity_advice 写入列）
        if (!out['Advice'] && out['总评']) out['Advice'] = out['总评'];
        return out;
    }

    function sortActivityAdviceByDateDesc(rows) {
        return rows.slice().sort(function (a, b) {
            var t1 = a['Date'] && a['Date'].getTime ? a['Date'].getTime() : 0;
            var t2 = b['Date'] && b['Date'].getTime ? b['Date'].getTime() : 0;
            return t2 - t1;
        });
    }

    function loadActivityAdvice() {
        var url = getActivityAdviceUrl();
        if (!url) return Promise.resolve([]);
        if (/\.json$/i.test(url)) {
            return loadJson(url).then(function (data) {
                return normalizeJsonRows(data, normalizeActivityAdviceRow, sortActivityAdviceByDateDesc);
            });
        }
        return fetch(url).then(function (r) {
            if (!r.ok) throw new Error(r.statusText);
            return r.text();
        }).then(function (text) {
            if (typeof Papa === 'undefined') return [];
            var parsed = Papa.parse(text, { header: true, skipEmptyLines: true });
            var headers = parsed.meta.fields || [];
            var rows = (parsed.data || []).map(function (row) { return normalizeActivityAdviceRow(row, headers); });
            return sortActivityAdviceByDateDesc(rows);
        }).catch(function () { return []; });
    }

    function phaseForWeekEnd(weekEnd) {
        if (!weekEnd || !weekEnd.getTime) return null;
        for (var i = 0; i < STATIC_TRAINING_PLAN.phases.length; i++) {
            var ph = STATIC_TRAINING_PLAN.phases[i];
            var start = parseDate(ph.start);
            var end = parseDate(ph.end);
            if (start && end && weekEnd >= start && weekEnd <= end) return { phase: ph, relation: 'in_phase' };
        }
        var first = STATIC_TRAINING_PLAN.phases[0];
        var last = STATIC_TRAINING_PLAN.phases[STATIC_TRAINING_PLAN.phases.length - 1];
        if (weekEnd < parseDate(first.start)) return { phase: first, relation: 'before_plan' };
        if (weekEnd > parseDate(last.end)) return { phase: last, relation: 'after_plan' };
        for (var j = 0; j < STATIC_TRAINING_PLAN.phases.length; j++) {
            var item = STATIC_TRAINING_PLAN.phases[j];
            if (weekEnd < parseDate(item.start)) return { phase: item, relation: 'before_phase' };
        }
        return { phase: last, relation: 'after_plan' };
    }

    function buildPhaseFollowUp(latest) {
        var resolved = phaseForWeekEnd(latest['Week End']);
        if (!resolved) return null;
        var phase = resolved.phase;
        var actual = latest['Distance (km)'] || 0;
        var weekly = (phase.weeklyKm || '').split('-');
        var lo = num(weekly[0]);
        var hi = num(weekly[1]);
        var volumeStatus = '在区间内';
        if (!isNaN(lo) && actual < lo) volumeStatus = '低于计划';
        if (!isNaN(hi) && actual > hi) volumeStatus = '高于计划';

        var relationText = {
            in_phase: '本周已落在该训练阶段',
            before_plan: '当前周报早于训练计划起点，以下按第一期做衔接参考',
            before_phase: '当前周报早于该阶段，以下作为提前衔接建议',
            after_plan: '当前周报已晚于计划末期，以下按最后一期复盘'
        }[resolved.relation] || phase.name;

        var tsb = latest['Form (TSB)'] || 0;
        var decouple = latest['LSD Decouple'] || 0;
        var followUps = [];
        if (volumeStatus === '低于计划' && !isNaN(lo)) {
            followUps.push('本周跑量还没到计划下限，先补稳总量，再考虑上更重的质量课。');
        } else if (volumeStatus === '高于计划' && !isNaN(hi)) {
            followUps.push('本周跑量已经超过该期上限，下周优先控量，不要继续叠疲劳。');
        } else {
            followUps.push('本周跑量已经落在当前阶段的目标区间，可以继续按本期结构推进。');
        }
        if (tsb < -20) followUps.push('TSB 已进入高疲劳区，下周先保恢复，再谈关键课完成度。');
        if (decouple > 5) followUps.push('LSD 解耦偏高，长跑日先守心率红线，不要把有氧长跑跑成测试课。');

        return {
            phase: phase,
            relationText: relationText,
            volumeStatus: volumeStatus,
            actualWeeklyKm: actual,
            followUps: followUps
        };
    }

    global.WEEKLY_REPORT = {
        getDataUrl: getDataUrl,
        loadData: loadData,
        sortByWeekStartDesc: sortByWeekStartDesc,
        sortByWeekStartAsc: sortByWeekStartAsc,
        getActivityAdviceUrl: getActivityAdviceUrl,
        loadActivityAdvice: loadActivityAdvice,
        sortActivityAdviceByDateDesc: sortActivityAdviceByDateDesc,
        trainingPlan: STATIC_TRAINING_PLAN,
        buildPhaseFollowUp: buildPhaseFollowUp
    };
})(typeof window !== 'undefined' ? window : this);
