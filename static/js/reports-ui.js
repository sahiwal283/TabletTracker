/**
 * Reports & analytics page: PO tables, shipment breakdown, Chart.js trends, live polling.
 */
(function () {
    'use strict';

    var charts = { trends: null, flavors: null, flavorDaily: null, throughput: null, rippedCards: null };
    var pollTimer = null;
    var lastVersion = null;
    var filtersCache = null;
    var includeClosedPos = false;

    function fmt(n) {
        if (n == null || n === '') return '—';
        var x = Number(n);
        if (Number.isNaN(x)) return String(n);
        return x.toLocaleString();
    }

    function showPoError(msg) {
        var el = document.getElementById('reports_po_error');
        if (!el) return;
        el.textContent = msg || '';
        el.classList.toggle('hidden', !msg);
    }

    function showAnalyticsError(msg) {
        var el = document.getElementById('reports_analytics_error');
        if (!el) return;
        el.textContent = msg || '';
        el.classList.toggle('hidden', !msg);
    }

    function setHint(id, msg) {
        var el = document.getElementById(id);
        if (!el) return;
        el.textContent = msg || '';
        el.classList.toggle('hidden', !msg);
    }

    function destroyChart(key) {
        if (charts[key]) {
            try {
                charts[key].destroy();
            } catch (_) { /* ignore */ }
            charts[key] = null;
        }
    }

    function defaultDateRange(bounds) {
        var to = bounds && bounds.max ? String(bounds.max).slice(0, 10) : new Date().toISOString().slice(0, 10);
        var from = bounds && bounds.min ? String(bounds.min).slice(0, 10) : to;
        return { from: from, to: to };
    }

    function resetTwoLevelSelect(selectEl) {
        if (!selectEl || !selectEl.id) return;
        var groupSelect = document.getElementById(selectEl.id + '_group');
        var itemSelect = document.getElementById(selectEl.id + '_item');
        if (groupSelect && groupSelect.parentNode) groupSelect.parentNode.removeChild(groupSelect);
        if (itemSelect && itemSelect.parentNode) itemSelect.parentNode.removeChild(itemSelect);
        selectEl.style.display = '';
        selectEl.dataset.twoLevelConverted = 'false';
        selectEl.dataset.twoLevelConverting = 'false';
        var rev = parseInt(selectEl.dataset.twoLevelRevision || '0', 10) || 0;
        selectEl.dataset.twoLevelRevision = String(rev + 1);
    }

    function applyTwoLevelFlavorDropdown() {
        var flavorSelect = document.getElementById('reports_flavor');
        if (!flavorSelect) return;
        resetTwoLevelSelect(flavorSelect);
        if (typeof window.convertToTwoLevelDropdown === 'function') {
            window.convertToTwoLevelDropdown(flavorSelect);
        }
    }

    async function fetchFilters() {
        var data = await apiCall('/api/reports/filters', { requestKey: 'reports-filters' });
        if (!data.success) throw new Error(data.error || 'Failed to load filters');
        return data;
    }

    function buildPoList(data) {
        var open = data.pos_open || data.pos || [];
        var closed = data.pos_closed || [];
        return includeClosedPos ? open.concat(closed) : open;
    }

    function renderClosedPoToggle(data) {
        var btn = document.getElementById('reports_toggle_closed_pos');
        if (!btn) return;
        var closedCount = (data.pos_closed || []).length;
        if (!closedCount) {
            btn.classList.add('hidden');
            return;
        }
        btn.classList.remove('hidden');
        btn.textContent = includeClosedPos
            ? 'Hide closed POs'
            : ('Show closed POs (' + fmt(closedCount) + ')');
    }

    function populateFilterSelects(data) {
        filtersCache = data;
        var poList = buildPoList(data);
        var poSel = document.getElementById('reports_po_select');
        var poA = document.getElementById('reports_analytics_po');
        if (poSel) {
            var cur = poSel.value;
            poSel.innerHTML = '<option value="">Select a PO…</option>';
            poList.forEach(function (p) {
                var opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = (p.po_number || '') + (p.vendor_name ? ' — ' + p.vendor_name : '');
                poSel.appendChild(opt);
            });
            if (cur && poList.some(function (p) { return String(p.id) === String(cur); })) poSel.value = cur;
        }
        if (poA) {
            var curA = poA.value;
            poA.innerHTML = '<option value="">All POs</option>';
            poList.forEach(function (p) {
                var opt = document.createElement('option');
                opt.value = p.id;
                opt.textContent = (p.po_number || '') + (p.vendor_name ? ' — ' + p.vendor_name : '');
                poA.appendChild(opt);
            });
            if (curA && poList.some(function (p) { return String(p.id) === String(curA); })) poA.value = curA;
        }
        renderClosedPoToggle(data);
        var vSel = document.getElementById('reports_vendor');
        if (vSel) {
            var cv = vSel.value;
            vSel.innerHTML = '<option value="">All vendors</option>';
            (data.vendors || []).forEach(function (v) {
                var opt = document.createElement('option');
                opt.value = v;
                opt.textContent = v;
                vSel.appendChild(opt);
            });
            if (cv) vSel.value = cv;
        }
        var fSel = document.getElementById('reports_flavor');
        if (fSel) {
            var cf = fSel.value;
            fSel.innerHTML = '<option value="">All flavors</option>';
            (data.flavors || []).forEach(function (f) {
                var opt = document.createElement('option');
                opt.value = f.id;
                opt.textContent = f.name;
                fSel.appendChild(opt);
            });
            if (cf) fSel.value = cf;
            applyTwoLevelFlavorDropdown();
        }
        var dr = defaultDateRange(data.date_bounds);
        var df = document.getElementById('reports_date_from');
        var dt = document.getElementById('reports_date_to');
        if (df && !df.dataset.touched) df.value = dr.from;
        if (dt && !dt.dataset.touched) dt.value = dr.to;
    }

    function renderTotalTable(payload) {
        var tbody = document.getElementById('reports_total_tbody');
        var tfoot = document.getElementById('reports_total_tfoot');
        var sec = document.getElementById('reports_total_section');
        if (!tbody || !tfoot || !sec) return;
        tbody.innerHTML = '';
        (payload.rows || []).forEach(function (row) {
            var tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50';
            tr.innerHTML =
                '<td class="px-3 py-2"><span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-[var(--surface-elevated)] text-gray-800">' +
                escapeHtml(row.flavor) +
                '</span></td>' +
                '<td class="px-3 py-2 text-right tabular-nums">' + fmt(row.ordered) + '</td>' +
                '<td class="px-3 py-2 text-right tabular-nums">' + fmt(row.received) + '</td>' +
                '<td class="px-3 py-2 text-right tabular-nums">' + fmt(row.packed) + '</td>' +
                '<td class="px-3 py-2 text-right tabular-nums">' + fmt(row.bags_received) + '</td>' +
                '<td class="px-3 py-2 text-right tabular-nums">' + (row.avg_packed_per_bag != null ? fmt(row.avg_packed_per_bag) : '—') + '</td>';
            tbody.appendChild(tr);
        });
        var t = payload.totals || {};
        tfoot.innerHTML =
            '<tr><td class="px-3 py-2">Total</td>' +
            '<td class="px-3 py-2 text-right">' + fmt(t.ordered) + '</td>' +
            '<td class="px-3 py-2 text-right">' + fmt(t.received) + '</td>' +
            '<td class="px-3 py-2 text-right">' + fmt(t.packed) + '</td>' +
            '<td class="px-3 py-2 text-right">' + fmt(t.bags_received) + '</td>' +
            '<td class="px-3 py-2 text-right">' + (t.avg_packed_per_bag != null ? fmt(t.avg_packed_per_bag) : '—') + '</td></tr>';
        sec.classList.remove('hidden');
    }

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function renderShipments(payload) {
        var host = document.getElementById('reports_shipments_accordion');
        var sec = document.getElementById('reports_shipments_section');
        if (!host || !sec) return;
        host.innerHTML = '';
        var list = payload.shipments || [];
        if (list.length === 0) {
            sec.classList.add('hidden');
            return;
        }
        list.forEach(function (sh) {
            var details = document.createElement('details');
            details.className = 'group border border-gray-200 rounded-lg bg-white overflow-hidden';
            var sum = document.createElement('summary');
            sum.className = 'px-4 py-3 cursor-pointer text-sm font-semibold text-gray-800 bg-gray-50 hover:bg-gray-100 list-none flex justify-between items-center';
            var tot = sh.totals || {};
            sum.innerHTML =
                '<span>' + escapeHtml(sh.label || 'Shipment') + '</span>' +
                '<span class="text-xs font-normal text-gray-500">Recv ' + fmt(tot.received) + ' · Packed ' + fmt(tot.packed) + ' · Bags ' + fmt(tot.bags_received) + '</span>';
            var inner = document.createElement('div');
            inner.className = 'p-3 overflow-x-auto';
            var table = document.createElement('table');
            table.className = 'min-w-full divide-y divide-gray-200 text-sm';
            table.innerHTML =
                '<thead class="bg-gray-50"><tr>' +
                '<th class="px-2 py-1 text-left text-xs font-medium text-gray-600">Flavor</th>' +
                '<th class="px-2 py-1 text-right text-xs font-medium text-gray-600">Ordered</th>' +
                '<th class="px-2 py-1 text-right text-xs font-medium text-gray-600">Received</th>' +
                '<th class="px-2 py-1 text-right text-xs font-medium text-gray-600">Packed</th>' +
                '<th class="px-2 py-1 text-right text-xs font-medium text-gray-600">Bags</th>' +
                '<th class="px-2 py-1 text-right text-xs font-medium text-gray-600">Avg / bag</th>' +
                '</tr></thead>';
            var tb = document.createElement('tbody');
            tb.className = 'divide-y divide-gray-100';
            (sh.rows || []).forEach(function (row) {
                var tr = document.createElement('tr');
                tr.innerHTML =
                    '<td class="px-2 py-1">' + escapeHtml(row.flavor) + '</td>' +
                    '<td class="px-2 py-1 text-right tabular-nums">' + fmt(row.ordered) + '</td>' +
                    '<td class="px-2 py-1 text-right tabular-nums">' + fmt(row.received) + '</td>' +
                    '<td class="px-2 py-1 text-right tabular-nums">' + fmt(row.packed) + '</td>' +
                    '<td class="px-2 py-1 text-right tabular-nums">' + fmt(row.bags_received) + '</td>' +
                    '<td class="px-2 py-1 text-right tabular-nums">' + (row.avg_packed_per_bag != null ? fmt(row.avg_packed_per_bag) : '—') + '</td>';
                tb.appendChild(tr);
            });
            table.appendChild(tb);
            inner.appendChild(table);
            details.appendChild(sum);
            details.appendChild(inner);
            host.appendChild(details);
        });
        sec.classList.remove('hidden');
    }

    async function loadPoBlocks() {
        var poSel = document.getElementById('reports_po_select');
        var meta = document.getElementById('reports_po_meta');
        var loading = document.getElementById('reports_po_loading');
        if (!poSel) return;
        var poId = poSel.value;
        showPoError('');
        if (!poId) {
            document.getElementById('reports_total_section').classList.add('hidden');
            document.getElementById('reports_shipments_section').classList.add('hidden');
            if (meta) meta.textContent = '';
            return;
        }
        if (loading) loading.classList.remove('hidden');
        try {
            var overview = await apiCall('/api/reports/po-overview?po_id=' + encodeURIComponent(poId), {
                requestKey: 'reports-po-overview',
            });
            var ship = await apiCall('/api/reports/po-shipments?po_id=' + encodeURIComponent(poId), {
                requestKey: 'reports-po-shipments',
            });
            if (overview.po && meta) {
                meta.textContent =
                    (overview.po.po_number || '') +
                    (overview.po.vendor_name ? ' · ' + overview.po.vendor_name : '') +
                    (overview.po.tablet_type ? ' · ' + overview.po.tablet_type : '');
            }
            renderTotalTable(overview);
            renderShipments(ship);
        } catch (e) {
            if (e.name === 'AbortError') return;
            showPoError(e.message || 'Failed to load PO data');
        } finally {
            if (loading) loading.classList.add('hidden');
        }
    }

    function analyticsQueryParams() {
        var df = document.getElementById('reports_date_from');
        var dt = document.getElementById('reports_date_to');
        var v = document.getElementById('reports_vendor');
        var f = document.getElementById('reports_flavor');
        var po = document.getElementById('reports_analytics_po');
        var q = [];
        if (df && df.value) q.push('date_from=' + encodeURIComponent(df.value));
        if (dt && dt.value) q.push('date_to=' + encodeURIComponent(dt.value));
        if (v && v.value) q.push('vendor=' + encodeURIComponent(v.value));
        if (f && f.value) q.push('tablet_type_id=' + encodeURIComponent(f.value));
        if (po && po.value) q.push('po_id=' + encodeURIComponent(po.value));
        return q.join('&');
    }

    function renderTrendsChart(series) {
        destroyChart('trends');
        setHint('reports_trends_hint', '');
        var canvas = document.getElementById('reports_chart_trends');
        if (!canvas || typeof Chart === 'undefined') return;
        var labels = (series || []).map(function (s) {
            return s.date;
        });
        var packed = (series || []).map(function (s) {
            return s.packed_displays != null ? s.packed_displays : (s.packed || 0);
        });
        var received = (series || []).map(function (s) {
            return s.received || 0;
        });
        if (!labels.length) {
            setHint('reports_trends_hint', 'No trend data found for the selected filters/date range.');
        }
        charts.trends = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Packed (display equiv.)',
                        data: packed,
                        borderColor: 'rgb(79, 124, 130)',
                        backgroundColor: 'rgba(79, 124, 130, 0.12)',
                        tension: 0.2,
                        fill: true,
                    },
                    {
                        label: 'Received (bag labels)',
                        data: received,
                        borderColor: 'rgb(147, 177, 181)',
                        backgroundColor: 'rgba(147, 177, 181, 0.1)',
                        tension: 0.2,
                        fill: true,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    y: { beginAtZero: true },
                },
            },
        });
    }

    function renderTopFlavorsChart(topFlavors) {
        destroyChart('flavors');
        setHint('reports_top_flavors_hint', '');
        var canvas = document.getElementById('reports_chart_flavors');
        if (!canvas || typeof Chart === 'undefined') return;
        var slice = (topFlavors || []).slice(0, 12);
        var labels = slice.map(function (x) {
            return x.flavor;
        });
        var data = slice.map(function (x) {
            return x.packed_displays != null ? x.packed_displays : (x.packed || 0);
        });
        if (!slice.length) {
            setHint('reports_top_flavors_hint', 'No flavor totals found for the selected filters/date range.');
        }
        charts.flavors = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Packed displays',
                        data: data,
                        backgroundColor: 'rgba(11, 46, 51, 0.75)',
                    },
                ],
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { beginAtZero: true },
                },
            },
        });
    }

    function renderFlavorDailyChart(series) {
        destroyChart('flavorDaily');
        var canvas = document.getElementById('reports_chart_flavor_daily');
        var hint = document.getElementById('reports_flavor_series_hint');
        if (!canvas || typeof Chart === 'undefined') return;
        var s = series || [];
        var flavorSel = document.getElementById('reports_flavor');
        var hasFlavor = flavorSel && flavorSel.value;
        if (s.length === 0) {
            if (hint) {
                hint.textContent = hasFlavor
                    ? 'No packed data for this flavor in the selected range.'
                    : 'Choose a flavor filter to see daily packed trend for that flavor.';
                hint.classList.remove('hidden');
            }
            return;
        }
        if (hint) hint.classList.add('hidden');
        charts.flavorDaily = new Chart(canvas.getContext('2d'), {
            type: 'bar',
            data: {
                labels: s.map(function (x) {
                    return x.date;
                }),
                datasets: [
                    {
                        label: 'Packed',
                        data: s.map(function (x) {
                            return x.packed_displays != null ? x.packed_displays : (x.packed || 0);
                        }),
                        backgroundColor: 'rgba(79, 124, 130, 0.85)',
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: { y: { beginAtZero: true } },
            },
        });
    }

    function renderThroughput(summary, series) {
        var samplesEl = document.getElementById('reports_tp_samples');
        var avgMinEl = document.getElementById('reports_tp_avg_min');
        var medMinEl = document.getElementById('reports_tp_median_min');
        var tphEl = document.getElementById('reports_tp_tph');
        if (samplesEl) samplesEl.textContent = fmt((summary || {}).samples || 0);
        if (avgMinEl) avgMinEl.textContent = (summary && summary.avg_minutes != null) ? fmt(summary.avg_minutes) : '—';
        if (medMinEl) medMinEl.textContent = (summary && summary.median_minutes != null) ? fmt(summary.median_minutes) : '—';
        if (tphEl) tphEl.textContent = (summary && summary.avg_tablets_per_hour != null) ? fmt(summary.avg_tablets_per_hour) : '—';

        destroyChart('throughput');
        setHint('reports_throughput_hint', '');
        var canvas = document.getElementById('reports_chart_throughput');
        if (!canvas || typeof Chart === 'undefined') return;
        var s = series || [];
        if (!s.length) {
            setHint('reports_throughput_hint', 'No throughput samples with valid bag start/end times in this range.');
        }
        charts.throughput = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: s.map(function (x) { return x.date; }),
                datasets: [
                    {
                        label: 'Avg cycle (minutes)',
                        data: s.map(function (x) { return x.avg_minutes || 0; }),
                        borderColor: 'rgb(11, 46, 51)',
                        backgroundColor: 'rgba(11, 46, 51, 0.12)',
                        yAxisID: 'y',
                        tension: 0.2,
                        fill: true
                    },
                    {
                        label: 'Avg tablets / hour',
                        data: s.map(function (x) { return x.avg_tablets_per_hour || 0; }),
                        borderColor: 'rgb(79, 124, 130)',
                        backgroundColor: 'rgba(79, 124, 130, 0.12)',
                        yAxisID: 'y1',
                        tension: 0.2,
                        fill: true
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Minutes' } },
                    y1: { beginAtZero: true, position: 'right', grid: { drawOnChartArea: false }, title: { display: true, text: 'Tablets/hour' } }
                }
            }
        });
    }

    function renderKpis(trendsSeries, topFlavors) {
        var packed = 0;
        var received = 0;
        var days = (trendsSeries || []).length;
        (trendsSeries || []).forEach(function (x) {
            packed += Number(x.packed_displays != null ? x.packed_displays : (x.packed || 0));
            received += Number(x.received || 0);
        });
        var top = (topFlavors || [])[0];
        var topLabel = top
            ? (top.flavor + ' (' + fmt(top.packed_displays != null ? top.packed_displays : top.packed) + ')')
            : '—';
        var elPacked = document.getElementById('reports_kpi_total_packed');
        var elReceived = document.getElementById('reports_kpi_total_received');
        var elTop = document.getElementById('reports_kpi_top_flavor');
        var elDays = document.getElementById('reports_kpi_days');
        if (elPacked) elPacked.textContent = fmt(packed);
        if (elReceived) elReceived.textContent = fmt(received);
        if (elTop) elTop.textContent = topLabel;
        if (elDays) elDays.textContent = fmt(days);
    }

    function renderRippedCards(total, byFlavor) {
        var el = document.getElementById('reports_kpi_ripped_cards');
        if (el) el.textContent = fmt(total || 0);
        var host = document.getElementById('reports_ripped_cards_rows');
        var hint = document.getElementById('reports_ripped_cards_hint');
        if (!host) return;
        host.innerHTML = '';
        var rows = (byFlavor || []).slice(0, 12);
        if (!rows.length) {
            if (hint) {
                hint.textContent = 'No ripped-card losses were recorded for this filter range.';
                hint.classList.remove('hidden');
            }
            return;
        }
        if (hint) hint.classList.add('hidden');
        rows.forEach(function (row) {
            var line = document.createElement('div');
            line.className = 'flex items-center justify-between rounded-md border border-gray-200 px-3 py-2';
            line.innerHTML =
                '<span class="text-gray-700">' + escapeHtml(row.flavor || 'Unknown') + '</span>' +
                '<span class="font-semibold text-gray-800 tabular-nums">' + fmt(row.ripped_cards || 0) + '</span>';
            host.appendChild(line);
        });
    }

    function renderLossRate(cardsPerDisplay) {
        var el = document.getElementById('reports_kpi_loss_rate');
        if (!el) return;
        el.classList.remove('text-emerald-700', 'text-amber-700', 'text-red-700');
        if (cardsPerDisplay == null || Number.isNaN(Number(cardsPerDisplay))) {
            el.textContent = '—';
            el.classList.add('text-gray-800');
            return;
        }
        var rate = Number(cardsPerDisplay);
        el.classList.remove('text-gray-800');
        // cards/display thresholds:
        // <= 0.03 healthy, <= 0.07 watch, > 0.07 elevated loss
        if (rate <= 0.03) {
            el.classList.add('text-emerald-700');
        } else if (rate <= 0.07) {
            el.classList.add('text-amber-700');
        } else {
            el.classList.add('text-red-700');
        }
        el.textContent = rate.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 4,
        });
    }

    function renderRippedCardsTrend(series) {
        destroyChart('rippedCards');
        setHint('reports_ripped_trend_hint', '');
        var canvas = document.getElementById('reports_chart_ripped_cards');
        if (!canvas || typeof Chart === 'undefined') return;
        var s = series || [];
        if (!s.length) {
            setHint('reports_ripped_trend_hint', 'No ripped-card losses were recorded for this filter range.');
        }
        charts.rippedCards = new Chart(canvas.getContext('2d'), {
            type: 'line',
            data: {
                labels: s.map(function (x) { return x.date; }),
                datasets: [
                    {
                        label: 'Ripped cards',
                        data: s.map(function (x) { return x.ripped_cards || 0; }),
                        borderColor: 'rgb(147, 92, 43)',
                        backgroundColor: 'rgba(147, 92, 43, 0.14)',
                        tension: 0.2,
                        fill: true
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'bottom' } },
                scales: {
                    y: { beginAtZero: true, title: { display: true, text: 'Cards' } }
                }
            }
        });
    }

    function ensureChartLibrary() {
        if (typeof Chart !== 'undefined') return true;
        setHint('reports_trends_hint', 'Chart library unavailable.');
        setHint('reports_top_flavors_hint', 'Chart library unavailable.');
        showAnalyticsError(
            'Chart library failed to load. Refresh the page, or allow scripts from unpkg.com (CSP / ad blocker).'
        );
        return false;
    }

    async function loadAnalytics() {
        var loading = document.getElementById('reports_analytics_loading');
        showAnalyticsError('');
        var dfEl = document.getElementById('reports_date_from');
        var dtEl = document.getElementById('reports_date_to');
        var q = analyticsQueryParams();
        if (!dfEl || !dtEl || !dfEl.value || !dtEl.value) {
            showAnalyticsError('Choose both start and end dates.');
            return;
        }
        if (!q) {
            showAnalyticsError('Choose a date range.');
            return;
        }
        if (loading) loading.classList.remove('hidden');
        try {
            var trends = await apiCall('/api/reports/trends?' + q, { requestKey: 'reports-trends' });
            var dims = await apiCall('/api/reports/dimensions?' + q, { requestKey: 'reports-dimensions' });
            renderKpis(trends.series || [], dims.top_flavors || []);
            renderRippedCards(dims.ripped_cards_total || 0, dims.ripped_cards_by_flavor || []);
            renderLossRate(dims.loss_rate_cards_per_display);
            renderThroughput(dims.throughput_summary || {}, dims.throughput_series || []);
            if (ensureChartLibrary()) {
                renderTrendsChart(trends.series || []);
                renderTopFlavorsChart(dims.top_flavors || []);
                renderFlavorDailyChart(dims.selected_flavor_series || []);
                renderRippedCardsTrend(dims.ripped_cards_series || []);
            }
        } catch (e) {
            if (e.name === 'AbortError') return;
            showAnalyticsError(e.message || 'Failed to load analytics');
        } finally {
            if (loading) loading.classList.add('hidden');
        }
    }

    async function refreshVersion() {
        var data = await apiCall('/api/reports/updates', { requestKey: 'reports-updates' });
        if (!data.success || !data.version) return;
        if (lastVersion && data.version !== lastVersion) {
            await softReload();
        }
        lastVersion = data.version;
    }

    async function softReload() {
        try {
            var data = await fetchFilters();
            populateFilterSelects(data);
            await loadPoBlocks();
            await loadAnalytics();
        } catch (e) {
            console.warn('reports soft reload', e);
        }
    }

    function wireReportControls() {
        var df = document.getElementById('reports_date_from');
        var dt = document.getElementById('reports_date_to');
        if (df) {
            df.addEventListener('change', function () {
                df.dataset.touched = '1';
            });
        }
        if (dt) {
            dt.addEventListener('change', function () {
                dt.dataset.touched = '1';
            });
        }

        var poSel = document.getElementById('reports_po_select');
        if (poSel) poSel.addEventListener('change', loadPoBlocks);

        var closedToggle = document.getElementById('reports_toggle_closed_pos');
        if (closedToggle) {
            closedToggle.addEventListener('click', function () {
                includeClosedPos = !includeClosedPos;
                if (filtersCache) {
                    populateFilterSelects(filtersCache);
                    loadPoBlocks();
                    loadAnalytics();
                }
            });
        }

        var applyBtn = document.getElementById('reports_apply_analytics');
        if (applyBtn) {
            applyBtn.addEventListener('click', function (e) {
                e.preventDefault();
                e.stopPropagation();
                loadAnalytics();
            });
        }

        var vendor = document.getElementById('reports_vendor');
        var flavor = document.getElementById('reports_flavor');
        var apo = document.getElementById('reports_analytics_po');
        if (vendor) vendor.addEventListener('change', loadAnalytics);
        if (flavor) flavor.addEventListener('change', loadAnalytics);
        if (apo) apo.addEventListener('change', loadAnalytics);
    }

    function schedulePoll() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(function () {
            if (document.visibilityState !== 'visible') return;
            refreshVersion().catch(function () { /* ignore */ });
        }, 12000);
    }

    async function init() {
        wireReportControls();
        schedulePoll();
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible') refreshVersion().catch(function () {});
        });

        try {
            var data = await fetchFilters();
            populateFilterSelects(data);
            await loadAnalytics();
            var up = await apiCall('/api/reports/updates', { requestKey: 'reports-updates-init' });
            if (up.success) lastVersion = up.version;
        } catch (e) {
            showAnalyticsError(e.message || 'Failed to initialize');
        }
    }

    function startReports() {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
        } else {
            init();
        }
    }

    startReports();
})();
