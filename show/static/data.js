/**
 * Load Weekly_Report data: CSV URL (default) or optional JSON URL from query or window.DATA_URL
 * Activity_Advice: second data source for per-run coach advice (optional ?activity_advice= or window.ACTIVITY_ADVICE_URL)
 */
(function (global) {
    var DEFAULT_CSV_URL = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQKYBbug9yQhYtejoO-9OMKXYQfA1Ju4ReO2YvYb7kqhWlrczvSrnHCmK_YBc5B6olsbBfUoP2Jbn5b/pub?gid=774375516&single=true&output=csv';
    // Activity_Advice 表 CSV 发布链接，需在 Google 表格中发布 Activity_Advice 工作表后替换为实际 gid；或通过 ?activity_advice= 传入
    var DEFAULT_ACTIVITY_ADVICE_CSV_URL = '';

    function getDataUrl() {
        var params = new URLSearchParams(location.search);
        return params.get('data') || global.DATA_URL || DEFAULT_CSV_URL;
    }

    function getActivityAdviceUrl() {
        var params = new URLSearchParams(location.search);
        return params.get('activity_advice') || global.ACTIVITY_ADVICE_URL || DEFAULT_ACTIVITY_ADVICE_CSV_URL;
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
        if (/\.json$/i.test(url)) return loadJson(url);
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
                var rows = Array.isArray(data) ? data : (data.rows || data.data || []);
                if (!rows.length) return [];
                var headers = Object.keys(typeof rows[0] === 'object' ? rows[0] : {});
                rows = rows.map(function (r) { return normalizeActivityAdviceRow(r, headers); });
                return sortActivityAdviceByDateDesc(rows);
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

    global.WEEKLY_REPORT = {
        getDataUrl: getDataUrl,
        loadData: loadData,
        sortByWeekStartDesc: sortByWeekStartDesc,
        sortByWeekStartAsc: sortByWeekStartAsc,
        getActivityAdviceUrl: getActivityAdviceUrl,
        loadActivityAdvice: loadActivityAdvice,
        sortActivityAdviceByDateDesc: sortActivityAdviceByDateDesc
    };
})(typeof window !== 'undefined' ? window : this);
