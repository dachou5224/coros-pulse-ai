/**
 * Load Weekly_Report data: CSV URL (default) or optional JSON URL from query or window.DATA_URL
 */
(function (global) {
    var DEFAULT_CSV_URL = 'https://docs.google.com/spreadsheets/d/e/2PACX-1vQKYBbug9yQhYtejoO-9OMKXYQfA1Ju4ReO2YvYb7kqhWlrczvSrnHCmK_YBc5B6olsbBfUoP2Jbn5b/pub?gid=774375516&single=true&output=csv';

    function getDataUrl() {
        var params = new URLSearchParams(location.search);
        return params.get('data') || global.DATA_URL || DEFAULT_CSV_URL;
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
            } else {
                out[h] = v;
            }
        });
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

    global.WEEKLY_REPORT = {
        getDataUrl: getDataUrl,
        loadData: loadData,
        sortByWeekStartDesc: sortByWeekStartDesc,
        sortByWeekStartAsc: sortByWeekStartAsc
    };
})(typeof window !== 'undefined' ? window : this);
