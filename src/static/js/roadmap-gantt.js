/*
 * Roadmap Gantt view.
 *
 * Renders a roadmap as swimlanes of goals with draggable, resizable initiative bars
 * and finish-to-start dependency arrows, and drives the /roadmaps/<id>/api endpoints.
 *
 * Ported from the standalone Roadmap Planner prototype with four things fixed, all of
 * which matter more here than they did there:
 *
 *  - Every value interpolated into markup goes through esc(). In a single-user local
 *    tool an unescaped name was self-XSS; in a multi-user app it is stored XSS from
 *    one user to another.
 *  - Writes send X-CSRFToken, because OpsDeck has CSRFProtect enabled globally.
 *  - Colours live in CSS (see roadmap-gantt.css) so the chart follows data-bs-theme.
 *    The dependency overlay needs its colours imperatively, so it reads them back
 *    from custom properties and redraws on the app's themechange event.
 *  - localStorage keys are namespaced, matching opsdeck-theme.
 */
(function () {
    'use strict';

    const root = document.getElementById('roadmap-gantt');
    if (!root) {
        return;
    }

    const CONFIG = {
        apiBase: root.dataset.apiBase,
        // Prefix to append an initiative id to, for the full detail page.
        initiativeBase: root.dataset.initiativeBase,
        canWrite: root.dataset.canWrite === 'true',
        csrfToken: root.dataset.csrfToken,
        stepsPerPeriod: parseInt(root.dataset.stepsPerPeriod, 10) || 4,
    };

    const COMPACT_KEY = 'opsdeck-roadmap-compact';

    const PRIORITY_ICON = {
        very_high: '▲▲', high: '▲', medium: '●',
        low: '▼', very_low: '▼▼',
    };
    const PRIORITY_LABEL = {
        very_high: 'Very high', high: 'High', medium: 'Medium', low: 'Low', very_low: 'Very low',
    };
    const STATUS_LABEL = { planned: 'Planned', in_progress: 'In progress', done: 'Done' };

    let state = null;
    let searchTerm = '';
    let statusFilter = '';
    let criticalPath = { tasks: new Set(), edges: new Set() };
    let panelInitiativeId = null;
    let dragInitiativeId = null;
    let bars = [];
    let panel = null;

    // --- helpers -----------------------------------------------------------

    function esc(value) {
        return String(value === null || value === undefined ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function status(message, isError) {
        const el = document.getElementById('rg-status');
        if (!el) {
            return;
        }
        el.textContent = message;
        el.className = isError ? 'small text-danger' : 'small text-muted';
        if (!isError) {
            window.setTimeout(function () {
                if (el.textContent === message) {
                    el.textContent = '';
                }
            }, 2000);
        }
    }

    async function api(method, path, body) {
        const options = {
            method: method,
            credentials: 'same-origin',
            headers: { Accept: 'application/json', 'X-CSRFToken': CONFIG.csrfToken },
        };
        if (body !== undefined) {
            options.headers['Content-Type'] = 'application/json';
            options.body = JSON.stringify(body);
        }

        const response = await fetch(CONFIG.apiBase + path, options);
        let payload = null;
        try {
            payload = await response.json();
        } catch (error) {
            payload = null;
        }
        if (!response.ok) {
            throw new Error((payload && payload.error) || 'Request failed (' + response.status + ').');
        }
        return payload;
    }

    /** Run a mutation, report failures inline, and refresh from the server. */
    async function mutate(promiseFactory, successMessage) {
        try {
            await promiseFactory();
            status(successMessage || 'Saved');
            await load();
        } catch (error) {
            status(error.message, true);
        }
    }

    function themeColour(name, fallback) {
        const value = window.getComputedStyle(root).getPropertyValue(name).trim();
        return value || fallback;
    }

    function initiativesOf(goalId) {
        return state.initiatives.filter(function (initiative) {
            return initiative.goal_id === goalId;
        });
    }

    function findInitiative(id) {
        return state.initiatives.find(function (initiative) {
            return initiative.id === id;
        }) || null;
    }

    function matchesFilters(initiative) {
        if (statusFilter && initiative.status !== statusFilter) {
            return false;
        }
        if (searchTerm && initiative.name.toLowerCase().indexOf(searchTerm) === -1) {
            return false;
        }
        return true;
    }

    /** Escape first, then wrap the match, so the highlight cannot inject markup. */
    function highlight(name) {
        const safe = esc(name);
        if (!searchTerm) {
            return safe;
        }
        const index = name.toLowerCase().indexOf(searchTerm);
        if (index === -1) {
            return safe;
        }
        return esc(name.slice(0, index)) +
            '<mark>' + esc(name.slice(index, index + searchTerm.length)) + '</mark>' +
            esc(name.slice(index + searchTerm.length));
    }

    function durationLabel(initiative) {
        const periods = (initiative.end_step - initiative.start_step + 1) / CONFIG.stepsPerPeriod;
        return (Math.round(periods * 100) / 100) + 'P';
    }

    // --- derived data ------------------------------------------------------

    function pointsInPeriod(index) {
        const first = index * CONFIG.stepsPerPeriod + 1;
        const last = first + CONFIG.stepsPerPeriod - 1;
        let sum = 0;
        state.initiatives.forEach(function (initiative) {
            if (initiative.points === null || initiative.points === undefined) {
                return;
            }
            const duration = initiative.end_step - initiative.start_step + 1;
            const overlap = Math.min(initiative.end_step, last) - Math.max(initiative.start_step, first) + 1;
            if (overlap > 0) {
                sum += initiative.points * (overlap / duration);
            }
        });
        return Math.round(sum * 10) / 10;
    }

    /**
     * Walk back from the latest-finishing initiatives along dependency edges that are
     * exactly tight (predecessor.end + lag === successor.start). Those are the links
     * with no slack, so they form the chain that decides the roadmap's end date.
     */
    function computeCriticalPath() {
        const result = { tasks: new Set(), edges: new Set() };
        if (!state.initiatives.length) {
            return result;
        }

        const byId = {};
        state.initiatives.forEach(function (initiative) {
            byId[initiative.id] = initiative;
        });

        const predecessors = {};
        state.dependencies.forEach(function (dep) {
            (predecessors[dep.successor_id] = predecessors[dep.successor_id] || []).push(dep);
        });

        const latest = Math.max.apply(null, state.initiatives.map(function (i) {
            return i.end_step;
        }));
        const stack = state.initiatives.filter(function (i) {
            return i.end_step === latest;
        }).map(function (i) {
            return i.id;
        });

        while (stack.length) {
            const id = stack.pop();
            if (result.tasks.has(id)) {
                continue;
            }
            result.tasks.add(id);
            (predecessors[id] || []).forEach(function (dep) {
                const predecessor = byId[dep.predecessor_id];
                if (predecessor && predecessor.end_step + dep.lag === byId[id].start_step) {
                    result.edges.add(dep.predecessor_id + '-' + id);
                    stack.push(dep.predecessor_id);
                }
            });
        }
        return result;
    }

    // --- rendering ---------------------------------------------------------

    function columnTemplate() {
        return 'var(--rg-label-width) repeat(' + state.periods.length + ', minmax(90px, 1fr))';
    }

    function renderHeader(columns) {
        const cells = state.periods.map(function (period) {
            const range = [period.start_date, period.end_date].filter(Boolean).join(' → ');
            return '<div class="rg-period">' + esc(period.label) +
                '<small>' + (range ? esc(range) : '&nbsp;') + '</small></div>';
        }).join('');

        const sums = state.periods.map(function (period, index) {
            const sum = pointsInPeriod(index);
            return '<div class="rg-sum-cell">' + (sum ? esc(sum) : '—') + '</div>';
        }).join('');

        return '<div class="rg-row rg-head" style="grid-template-columns:' + columns + '">' +
            '<div class="rg-label">Initiative</div>' + cells + '</div>' +
            '<div class="rg-row rg-sum" style="grid-template-columns:' + columns + '">' +
            '<div class="rg-label">Σ Story points</div>' + sums + '</div>';
    }

    function goalHeaderRow(goal) {
        const row = document.createElement('div');
        row.className = 'rg-row';
        row.style.gridTemplateColumns = '1fr';

        const actions = CONFIG.canWrite
            ? '<button type="button" class="btn btn-sm btn-link text-white p-0 rg-row-actions"' +
              ' data-action="add-initiative" data-goal-id="' + goal.id + '" title="Add initiative">' +
              '<i class="fas fa-plus"></i></button>' +
              '<button type="button" class="btn btn-sm btn-link text-white p-0 ms-2 rg-row-actions"' +
              ' data-action="delete-goal" data-goal-id="' + goal.id + '" title="Delete goal">' +
              '<i class="fas fa-times"></i></button>'
            : '';

        row.innerHTML = '<div class="rg-goal-header" style="background:' + esc(goal.color) + '">' +
            '<span class="rg-goal-name">' + esc(goal.name) + '</span>' + actions + '</div>';

        if (CONFIG.canWrite) {
            makeDropTarget(row, goal.id);
        }
        return row;
    }

    function makeDropTarget(element, goalId) {
        element.addEventListener('dragover', function (event) {
            if (dragInitiativeId === null) {
                return;
            }
            event.preventDefault();
            element.classList.add('rg-drop-target');
        });
        element.addEventListener('dragleave', function () {
            element.classList.remove('rg-drop-target');
        });
        element.addEventListener('drop', function (event) {
            if (dragInitiativeId === null) {
                return;
            }
            event.preventDefault();
            element.classList.remove('rg-drop-target');
            reorder(dragInitiativeId, goalId, element.dataset.initiativeId);
        });
    }

    function initiativeRow(initiative, goal, columns, zebra) {
        const row = document.createElement('div');
        row.className = 'rg-row';
        row.style.gridTemplateColumns = columns;
        row.dataset.initiativeId = String(initiative.id);

        const priority = initiative.priority || 'medium';
        const flag = initiative.status === 'done'
            ? '<span class="rg-flag" title="Done">✅</span>'
            : (initiative.is_overdue ? '<span class="rg-flag text-danger" title="Overdue">⚠</span>' : '');
        const points = (initiative.points === null || initiative.points === undefined)
            ? ''
            : '<span class="rg-points" title="Story points">' + esc(initiative.points) + ' pt</span>';
        const grip = CONFIG.canWrite
            ? '<span class="rg-grip" title="Drag to reorder or move between goals">⠢</span>'
            : '';
        const remove = CONFIG.canWrite
            ? '<button type="button" class="btn btn-sm btn-link text-danger p-0 rg-row-actions"' +
              ' data-action="delete-initiative" data-initiative-id="' + initiative.id + '"' +
              ' title="Delete initiative"><i class="fas fa-times"></i></button>'
            : '';

        const cells = state.periods.map(function () {
            return '<div class="' + (zebra ? 'rg-zebra' : '') + '"></div>';
        }).join('');

        row.innerHTML =
            '<div class="rg-label">' + grip +
            '<span class="rg-priority" title="Priority: ' + esc(PRIORITY_LABEL[priority] || priority) + '">' +
            (PRIORITY_ICON[priority] || '') + '</span>' +
            '<span class="rg-name" data-action="open-panel" data-initiative-id="' + initiative.id + '">' +
            highlight(initiative.name) + '</span>' + flag + points + remove + '</div>' +
            '<div class="rg-track" style="grid-column:2/-1">' +
            '<div class="rg-cellgrid" style="grid-template-columns:repeat(' +
            state.periods.length + ',1fr)">' + cells + '</div></div>';

        const track = row.querySelector('.rg-track');
        track.appendChild(buildBar(initiative, goal, track));

        if (CONFIG.canWrite) {
            enableRowDrag(row, initiative);
            makeDropTarget(row, goal.id);
        }
        return row;
    }

    function buildBar(initiative, goal, track) {
        const bar = document.createElement('div');
        bar.className = 'rg-bar' + (criticalPath.tasks.has(initiative.id) ? ' rg-critical' : '');
        bar.style.background = goal.color;
        bar.dataset.initiativeId = String(initiative.id);
        bar.title = initiative.name + ' — ' + (STATUS_LABEL[initiative.status] || initiative.status);

        const progress = Math.max(0, Math.min(100, initiative.progress || 0));
        bar.innerHTML =
            '<div class="rg-bar-inner">' +
            '<div class="rg-progress" style="width:' + progress + '%"></div>' +
            '<span class="rg-bar-text">' + esc(durationLabel(initiative)) + '</span></div>' +
            '<div class="rg-handle rg-handle-l"></div><div class="rg-handle rg-handle-r"></div>' +
            '<div class="rg-dep-handle" title="Drag onto another initiative to link them"></div>';

        bars.push({ bar: bar, track: track, initiative: initiative });
        if (CONFIG.canWrite) {
            enableBarDrag(bar, track, initiative);
            enableDependencyDrag(bar, initiative);
        }
        return bar;
    }

    function placeBars() {
        const totalSteps = state.periods.length * CONFIG.stepsPerPeriod;
        bars.forEach(function (entry) {
            const stepWidth = entry.track.clientWidth / totalSteps;
            const initiative = entry.initiative;
            entry.bar.style.left = ((initiative.start_step - 1) * stepWidth) + 'px';
            entry.bar.style.width =
                Math.max(24, (initiative.end_step - initiative.start_step + 1) * stepWidth - 4) + 'px';
        });
    }

    /** Keep the "new initiative" goal picker in step with goals created via the API. */
    function refreshGoalPicker() {
        const select = document.getElementById('rg-new-initiative-goal');
        if (!select) {
            return;
        }
        const previous = select.value;
        select.innerHTML = state.goals.map(function (goal) {
            return '<option value="' + goal.id + '">' + esc(goal.name) + '</option>';
        }).join('');
        if (previous) {
            select.value = previous;
        }
    }

    function render() {
        bars = [];
        root.classList.toggle('rg-writable', CONFIG.canWrite);
        refreshGoalPicker();

        if (!state.periods.length) {
            root.innerHTML = '<div class="rg-empty">This roadmap has no periods yet. ' +
                'Add at least one from the roadmap form before placing initiatives.</div>';
            return;
        }

        const columns = columnTemplate();
        root.innerHTML = renderHeader(columns);

        criticalPath = computeCriticalPath();

        let rendered = 0;
        let zebra = false;
        state.goals.forEach(function (goal) {
            const all = initiativesOf(goal.id);
            const visible = all.filter(matchesFilters);
            const filtering = Boolean(searchTerm || statusFilter);
            if (filtering && !visible.length) {
                return;
            }
            rendered += 1;

            root.appendChild(goalHeaderRow(goal));

            if (!visible.length) {
                const empty = document.createElement('div');
                empty.className = 'rg-row';
                empty.style.gridTemplateColumns = columns;
                empty.innerHTML = '<div class="rg-label text-muted">— no initiatives —</div>' +
                    '<div class="rg-track" style="grid-column:2/-1"></div>';
                if (CONFIG.canWrite) {
                    makeDropTarget(empty, goal.id);
                }
                root.appendChild(empty);
            }

            visible.forEach(function (initiative) {
                root.appendChild(initiativeRow(initiative, goal, columns, zebra));
            });
            zebra = !zebra;
        });

        if (!state.goals.length) {
            root.insertAdjacentHTML('beforeend',
                '<div class="rg-empty">No goals yet. Add one to start placing initiatives.</div>');
        } else if (!rendered) {
            root.insertAdjacentHTML('beforeend',
                '<div class="rg-empty">No initiatives match the current filters.</div>');
        }

        placeBars();
        drawDependencies();
        drawTodayLine();
        if (panelInitiativeId !== null) {
            renderPanel();
        }
    }

    // --- overlays ----------------------------------------------------------

    function drawDependencies() {
        const existing = document.getElementById('rg-dep-svg');
        if (existing) {
            existing.remove();
        }
        if (!state.dependencies.length) {
            return;
        }

        const normal = themeColour('--rg-dep-color', '#8a94a3');
        const critical = themeColour('--rg-critical-color', '#e5484d');

        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.id = 'rg-dep-svg';
        svg.setAttribute('width', root.scrollWidth);
        svg.setAttribute('height', root.scrollHeight);
        svg.innerHTML =
            '<defs>' +
            '<marker id="rg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"' +
            ' markerHeight="7" orient="auto-start-reverse">' +
            '<path d="M0,0 L10,5 L0,10 z" fill="' + normal + '"/></marker>' +
            '<marker id="rg-arrow-critical" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"' +
            ' markerHeight="7" orient="auto-start-reverse">' +
            '<path d="M0,0 L10,5 L0,10 z" fill="' + critical + '"/></marker>' +
            '</defs>';

        const bounds = root.getBoundingClientRect();
        state.dependencies.forEach(function (dep) {
            const from = root.querySelector('.rg-bar[data-initiative-id="' + dep.predecessor_id + '"]');
            const to = root.querySelector('.rg-bar[data-initiative-id="' + dep.successor_id + '"]');
            if (!from || !to) {
                return;
            }

            const isCritical = criticalPath.edges.has(dep.predecessor_id + '-' + dep.successor_id);
            const fromRect = from.getBoundingClientRect();
            const toRect = to.getBoundingClientRect();
            const x1 = fromRect.right - bounds.left + root.scrollLeft;
            const y1 = fromRect.top - bounds.top + root.scrollTop + fromRect.height / 2;
            const x2 = toRect.left - bounds.left + root.scrollLeft;
            const y2 = toRect.top - bounds.top + root.scrollTop + toRect.height / 2;
            const mid = x1 + Math.max(14, (x2 - x1) / 2);

            const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            path.setAttribute('d', 'M' + x1 + ',' + y1 + ' L' + mid + ',' + y1 +
                ' L' + mid + ',' + y2 + ' L' + x2 + ',' + y2);
            path.setAttribute('fill', 'none');
            path.setAttribute('stroke', isCritical ? critical : normal);
            path.setAttribute('stroke-width', isCritical ? '2.4' : '1.6');
            path.setAttribute('marker-end', isCritical ? 'url(#rg-arrow-critical)' : 'url(#rg-arrow)');
            if (CONFIG.canWrite) {
                path.addEventListener('click', function () {
                    if (window.confirm('Delete this dependency?')) {
                        mutate(function () {
                            return api('DELETE', '/dependencies/' + dep.id);
                        }, 'Dependency removed');
                    }
                });
            }
            svg.appendChild(path);
        });

        root.appendChild(svg);
    }

    function drawTodayLine() {
        const existing = root.querySelector('.rg-today-line');
        if (existing) {
            existing.remove();
        }

        const track = root.querySelector('.rg-track');
        if (!track) {
            return;
        }

        const today = new Date();
        today.setHours(0, 0, 0, 0);

        let stepPosition = null;
        for (let index = 0; index < state.periods.length; index += 1) {
            const period = state.periods[index];
            if (!period.start_date || !period.end_date) {
                continue;
            }
            const start = new Date(period.start_date + 'T00:00:00');
            const end = new Date(period.end_date + 'T00:00:00');
            if (today >= start && today <= end) {
                const fraction = (today - start) / ((end - start) || 1);
                stepPosition = index * CONFIG.stepsPerPeriod + fraction * CONFIG.stepsPerPeriod + 1;
                break;
            }
        }
        if (stepPosition === null) {
            return;
        }

        const bounds = root.getBoundingClientRect();
        const trackBounds = track.getBoundingClientRect();
        const stepWidth = trackBounds.width / (state.periods.length * CONFIG.stepsPerPeriod);

        const line = document.createElement('div');
        line.className = 'rg-today-line';
        line.style.left = (trackBounds.left - bounds.left + root.scrollLeft +
            (stepPosition - 1) * stepWidth) + 'px';
        line.style.height = root.scrollHeight + 'px';
        line.innerHTML = '<span class="rg-today-label">Today</span>';
        root.appendChild(line);
    }

    // --- interactions ------------------------------------------------------

    function enableBarDrag(bar, track, initiative) {
        const totalSteps = state.periods.length * CONFIG.stepsPerPeriod;
        let mode = null;
        let originX = 0;
        let startStep = 0;
        let endStep = 0;

        function begin(kind) {
            return function (event) {
                mode = kind;
                originX = event.clientX;
                startStep = initiative.start_step;
                endStep = initiative.end_step;
                event.preventDefault();
                document.addEventListener('mousemove', onMove);
                document.addEventListener('mouseup', onUp);
            };
        }

        function onMove(event) {
            const stepWidth = track.clientWidth / totalSteps;
            const delta = Math.round((event.clientX - originX) / stepWidth);

            if (mode === 'move') {
                const duration = endStep - startStep;
                initiative.start_step = Math.min(Math.max(1, startStep + delta), totalSteps - duration);
                initiative.end_step = initiative.start_step + duration;
            } else if (mode === 'left') {
                initiative.start_step = Math.min(Math.max(1, startStep + delta), endStep);
            } else if (mode === 'right') {
                initiative.end_step = Math.max(Math.min(totalSteps, endStep + delta), startStep);
            }

            bar.querySelector('.rg-bar-text').textContent = durationLabel(initiative);
            placeBars();
            drawDependencies();
        }

        function onUp() {
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            if (!mode) {
                return;
            }
            mode = null;
            mutate(function () {
                return api('PATCH', '/initiatives/' + initiative.id, {
                    start_step: initiative.start_step,
                    end_step: initiative.end_step,
                });
            });
        }

        bar.addEventListener('mousedown', begin('move'));
        bar.querySelector('.rg-handle-l').addEventListener('mousedown', function (event) {
            event.stopPropagation();
            begin('left')(event);
        });
        bar.querySelector('.rg-handle-r').addEventListener('mousedown', function (event) {
            event.stopPropagation();
            begin('right')(event);
        });
    }

    function enableDependencyDrag(bar, initiative) {
        bar.querySelector('.rg-dep-handle').addEventListener('mousedown', function (event) {
            event.stopPropagation();
            event.preventDefault();

            const svg = document.getElementById('rg-dep-svg') || (function () {
                const created = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                created.id = 'rg-dep-svg';
                created.setAttribute('width', root.scrollWidth);
                created.setAttribute('height', root.scrollHeight);
                root.appendChild(created);
                return created;
            }());

            const guide = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            guide.setAttribute('stroke', themeColour('--rg-dep-color', '#8a94a3'));
            guide.setAttribute('stroke-width', '2');
            guide.setAttribute('stroke-dasharray', '4,3');
            svg.appendChild(guide);

            function onMove(moveEvent) {
                const bounds = root.getBoundingClientRect();
                const rect = bar.getBoundingClientRect();
                guide.setAttribute('x1', rect.right - bounds.left + root.scrollLeft);
                guide.setAttribute('y1', rect.top - bounds.top + root.scrollTop + rect.height / 2);
                guide.setAttribute('x2', moveEvent.clientX - bounds.left + root.scrollLeft);
                guide.setAttribute('y2', moveEvent.clientY - bounds.top + root.scrollTop);
            }

            function onUp(upEvent) {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
                guide.remove();

                const element = document.elementFromPoint(upEvent.clientX, upEvent.clientY);
                const target = element && element.closest('.rg-bar');
                if (!target) {
                    return;
                }
                const successorId = parseInt(target.dataset.initiativeId, 10);
                if (!successorId || successorId === initiative.id) {
                    return;
                }
                mutate(function () {
                    return api('POST', '/dependencies', {
                        predecessor_id: initiative.id,
                        successor_id: successorId,
                    });
                }, 'Dependency created');
            }

            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }

    function enableRowDrag(row, initiative) {
        const grip = row.querySelector('.rg-grip');
        if (!grip) {
            return;
        }
        grip.draggable = true;
        grip.addEventListener('dragstart', function (event) {
            dragInitiativeId = initiative.id;
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', String(initiative.id));
            row.classList.add('rg-dragging');
        });
        grip.addEventListener('dragend', function () {
            dragInitiativeId = null;
            root.querySelectorAll('.rg-dragging, .rg-drop-target').forEach(function (element) {
                element.classList.remove('rg-dragging', 'rg-drop-target');
            });
        });
    }

    /** Rebuild the position sequence for the target goal with `movedId` inserted. */
    function reorder(movedId, goalId, beforeIdRaw) {
        const beforeId = beforeIdRaw ? parseInt(beforeIdRaw, 10) : null;
        if (beforeId === movedId) {
            return;
        }

        const ordered = initiativesOf(goalId).filter(function (initiative) {
            return initiative.id !== movedId;
        });
        const moved = findInitiative(movedId);
        if (!moved) {
            return;
        }

        const at = beforeId === null ? ordered.length : ordered.findIndex(function (initiative) {
            return initiative.id === beforeId;
        });
        ordered.splice(at === -1 ? ordered.length : at, 0, moved);

        const items = ordered.map(function (initiative, index) {
            return { id: initiative.id, goal_id: goalId, position: index };
        });
        mutate(function () {
            return api('POST', '/initiatives/reorder', { items: items });
        }, 'Reordered');
    }

    // --- detail panel ------------------------------------------------------

    function openPanel(id) {
        panelInitiativeId = id;
        renderPanel();
        if (panel) {
            panel.show();
        }
    }

    function scheduleLabel(initiative) {
        const dates = [initiative.planned_start_date, initiative.planned_end_date].filter(Boolean);
        if (dates.length === 2) {
            return dates[0] + ' → ' + dates[1];
        }
        return 'Steps ' + initiative.start_step + '–' + initiative.end_step;
    }

    function dependencyItems(initiative) {
        const items = [];
        state.dependencies.forEach(function (dep) {
            if (dep.successor_id === initiative.id) {
                items.push({ id: dep.id, label: 'After', other: findInitiative(dep.predecessor_id) });
            } else if (dep.predecessor_id === initiative.id) {
                items.push({ id: dep.id, label: 'Before', other: findInitiative(dep.successor_id) });
            }
        });
        return items;
    }

    function renderPanel() {
        const initiative = findInitiative(panelInitiativeId);
        const body = document.getElementById('rg-panel-body');
        if (!body) {
            return;
        }
        if (!initiative) {
            panelInitiativeId = null;
            body.innerHTML = '<p class="text-muted">This initiative no longer exists.</p>';
            return;
        }

        const disabled = CONFIG.canWrite ? '' : ' disabled';
        const goal = state.goals.find(function (candidate) {
            return candidate.id === initiative.goal_id;
        });

        const statusOptions = Object.keys(STATUS_LABEL).map(function (key) {
            return '<option value="' + key + '"' + (initiative.status === key ? ' selected' : '') +
                '>' + esc(STATUS_LABEL[key]) + '</option>';
        }).join('');
        const priorityOptions = Object.keys(PRIORITY_LABEL).map(function (key) {
            return '<option value="' + key + '"' + (initiative.priority === key ? ' selected' : '') +
                '>' + esc(PRIORITY_LABEL[key]) + '</option>';
        }).join('');

        const dependencies = dependencyItems(initiative);
        const dependencyList = dependencies.length
            ? dependencies.map(function (item) {
                const remove = CONFIG.canWrite
                    ? '<button type="button" class="btn btn-sm btn-link text-danger p-0"' +
                      ' data-action="remove-dependency" data-dependency-id="' + item.id + '"' +
                      ' title="Remove dependency"><i class="fas fa-times"></i></button>'
                    : '';
                return '<li class="list-group-item d-flex justify-content-between align-items-center py-1">' +
                    '<span><span class="badge bg-secondary me-2">' + esc(item.label) + '</span>' +
                    esc(item.other ? item.other.name : '—') + '</span>' + remove + '</li>';
            }).join('')
            : '<li class="list-group-item text-muted py-1">None</li>';

        const linkTargets = state.initiatives.filter(function (candidate) {
            return candidate.id !== initiative.id;
        }).map(function (candidate) {
            return '<option value="' + candidate.id + '">' + esc(candidate.name) + '</option>';
        }).join('');

        body.innerHTML =
            '<input type="hidden" id="rg-panel-id" value="' + initiative.id + '">' +
            '<p class="text-muted small mb-3">' +
            (goal ? '<span class="badge me-2" style="background:' + esc(goal.color) + '">' +
                esc(goal.name) + '</span>' : '') +
            esc(scheduleLabel(initiative)) + '</p>' +

            (CONFIG.initiativeBase
                ? '<a class="btn btn-sm btn-outline-secondary mb-3" href="' +
                  esc(CONFIG.initiativeBase + initiative.id) + '">' +
                  '<i class="fas fa-external-link-alt"></i> Open full details</a>'
                : '') +

            '<div class="mb-3"><label class="form-label" for="rg-panel-name">Name</label>' +
            '<input type="text" class="form-control" id="rg-panel-name" value="' +
            esc(initiative.name) + '"' + disabled + '></div>' +

            '<div class="row"><div class="col-6 mb-3">' +
            '<label class="form-label" for="rg-panel-status">Status</label>' +
            '<select class="form-select no-tom" id="rg-panel-status"' + disabled + '>' +
            statusOptions + '</select></div>' +
            '<div class="col-6 mb-3"><label class="form-label" for="rg-panel-priority">Priority</label>' +
            '<select class="form-select no-tom" id="rg-panel-priority"' + disabled + '>' +
            priorityOptions + '</select></div></div>' +

            '<div class="row"><div class="col-6 mb-3">' +
            '<label class="form-label" for="rg-panel-progress">Progress (%)</label>' +
            '<input type="number" min="0" max="100" class="form-control" id="rg-panel-progress"' +
            ' value="' + esc(initiative.progress) + '"' + disabled + '></div>' +
            '<div class="col-6 mb-3"><label class="form-label" for="rg-panel-points">Story points</label>' +
            '<input type="number" min="0" class="form-control" id="rg-panel-points" value="' +
            (initiative.points === null || initiative.points === undefined ? '' : esc(initiative.points)) +
            '"' + disabled + '></div></div>' +

            '<div class="row"><div class="col-6 mb-3">' +
            '<label class="form-label" for="rg-panel-ref">Ticket reference</label>' +
            '<input type="text" class="form-control" id="rg-panel-ref" value="' +
            esc(initiative.external_ref) + '" placeholder="JIRA-1234"' + disabled + '></div>' +
            '<div class="col-6 mb-3"><label class="form-label" for="rg-panel-url">Ticket URL</label>' +
            '<input type="url" class="form-control" id="rg-panel-url" value="' +
            esc(initiative.external_url || '') + '"' + disabled + '></div></div>' +

            '<div class="form-check mb-3">' +
            '<input class="form-check-input" type="checkbox" id="rg-panel-new"' +
            (initiative.is_new ? ' checked' : '') + disabled + '>' +
            '<label class="form-check-label" for="rg-panel-new">Flag as new this cycle</label></div>' +

            '<div class="mb-3"><label class="form-label" for="rg-panel-description">Description</label>' +
            '<textarea class="form-control" id="rg-panel-description" rows="4"' + disabled + '>' +
            esc(initiative.description) + '</textarea></div>' +

            '<h6 class="mt-4">Dependencies</h6>' +
            '<ul class="list-group list-group-flush mb-2">' + dependencyList + '</ul>' +
            (CONFIG.canWrite && linkTargets
                ? '<div class="input-group input-group-sm mb-3">' +
                  '<select class="form-select no-tom" id="rg-panel-dep-target">' + linkTargets +
                  '</select><button type="button" class="btn btn-outline-secondary"' +
                  ' data-action="add-dependency">Add as successor</button></div>'
                : '');
    }

    async function savePanel() {
        const id = parseInt(document.getElementById('rg-panel-id').value, 10);
        const pointsValue = document.getElementById('rg-panel-points').value;

        await mutate(function () {
            return api('PATCH', '/initiatives/' + id, {
                name: document.getElementById('rg-panel-name').value,
                status: document.getElementById('rg-panel-status').value,
                priority: document.getElementById('rg-panel-priority').value,
                progress: document.getElementById('rg-panel-progress').value || 0,
                points: pointsValue === '' ? null : pointsValue,
                external_ref: document.getElementById('rg-panel-ref').value,
                external_url: document.getElementById('rg-panel-url').value,
                is_new: document.getElementById('rg-panel-new').checked,
                description: document.getElementById('rg-panel-description').value,
            });
        });
    }

    // --- event wiring ------------------------------------------------------

    const ACTIONS = {
        'open-panel': function (element) {
            openPanel(parseInt(element.dataset.initiativeId, 10));
        },
        'delete-initiative': function (element) {
            if (!window.confirm('Delete this initiative?')) {
                return;
            }
            const id = parseInt(element.dataset.initiativeId, 10);
            if (panelInitiativeId === id && panel) {
                panel.hide();
            }
            mutate(function () {
                return api('DELETE', '/initiatives/' + id);
            }, 'Initiative deleted');
        },
        'delete-goal': function (element) {
            if (!window.confirm('Delete this goal and all of its initiatives?')) {
                return;
            }
            mutate(function () {
                return api('DELETE', '/goals/' + parseInt(element.dataset.goalId, 10));
            }, 'Goal deleted');
        },
        'add-initiative': function (element) {
            const select = document.getElementById('rg-new-initiative-goal');
            if (select) {
                select.value = element.dataset.goalId;
            }
            window.bootstrap.Modal.getOrCreateInstance(
                document.getElementById('rg-initiative-modal')).show();
        },
        'remove-dependency': function (element) {
            mutate(function () {
                return api('DELETE', '/dependencies/' + parseInt(element.dataset.dependencyId, 10));
            }, 'Dependency removed');
        },
        'add-dependency': function () {
            const target = document.getElementById('rg-panel-dep-target');
            const id = parseInt(document.getElementById('rg-panel-id').value, 10);
            if (!target || !target.value) {
                return;
            }
            mutate(function () {
                return api('POST', '/dependencies', {
                    predecessor_id: id,
                    successor_id: parseInt(target.value, 10),
                });
            }, 'Dependency created');
        },
    };

    function onClick(event) {
        const element = event.target.closest('[data-action]');
        if (!element) {
            return;
        }
        const action = ACTIONS[element.dataset.action];
        if (action) {
            event.preventDefault();
            action(element);
        }
    }

    /** Reposition the pixel-positioned layers after anything that changes the layout. */
    function reflow() {
        if (!state) {
            return;
        }
        window.requestAnimationFrame(function () {
            placeBars();
            drawDependencies();
            drawTodayLine();
        });
    }

    function applyCompact(enabled) {
        root.classList.toggle('rg-compact', enabled);
        try {
            window.localStorage.setItem(COMPACT_KEY, enabled ? '1' : '0');
        } catch (error) {
            /* private mode: the preference simply does not persist */
        }
        reflow();
    }

    async function load() {
        try {
            state = await api('GET', '/data');
            render();
        } catch (error) {
            root.innerHTML = '<div class="rg-empty text-danger">' + esc(error.message) + '</div>';
        }
    }

    function wire() {
        root.addEventListener('click', onClick);

        const panelElement = document.getElementById('rg-panel');
        if (panelElement) {
            panel = window.bootstrap.Offcanvas.getOrCreateInstance(panelElement);
            panelElement.addEventListener('click', onClick);
            panelElement.addEventListener('hidden.bs.offcanvas', function () {
                panelInitiativeId = null;
            });
        }

        const save = document.getElementById('rg-panel-save');
        if (save) {
            save.addEventListener('click', savePanel);
        }

        const search = document.getElementById('rg-search');
        if (search) {
            search.addEventListener('input', function () {
                searchTerm = search.value.trim().toLowerCase();
                render();
            });
        }

        const statusSelect = document.getElementById('rg-status-filter');
        if (statusSelect) {
            statusSelect.addEventListener('change', function () {
                statusFilter = statusSelect.value;
                render();
            });
        }

        const compact = document.getElementById('rg-compact-toggle');
        if (compact) {
            compact.addEventListener('click', function () {
                applyCompact(!root.classList.contains('rg-compact'));
            });
        }

        const goalForm = document.getElementById('rg-goal-form');
        if (goalForm) {
            goalForm.addEventListener('submit', function (event) {
                event.preventDefault();
                const name = document.getElementById('rg-new-goal-name').value;
                const color = document.getElementById('rg-new-goal-color').value;
                window.bootstrap.Modal.getInstance(document.getElementById('rg-goal-modal')).hide();
                goalForm.reset();
                mutate(function () {
                    return api('POST', '/goals', { name: name, color: color });
                }, 'Goal created');
            });
        }

        const initiativeForm = document.getElementById('rg-initiative-form');
        if (initiativeForm) {
            initiativeForm.addEventListener('submit', function (event) {
                event.preventDefault();
                const goalId = parseInt(document.getElementById('rg-new-initiative-goal').value, 10);
                const name = document.getElementById('rg-new-initiative-name').value;
                window.bootstrap.Modal.getInstance(
                    document.getElementById('rg-initiative-modal')).hide();
                initiativeForm.reset();
                mutate(function () {
                    return api('POST', '/initiatives', { goal_id: goalId, name: name });
                }, 'Initiative created');
            });
        }

        // The chart follows data-bs-theme through CSS, but the SVG overlay needs its
        // colours re-read imperatively when the user flips the theme.
        window.addEventListener('themechange', function () {
            if (state) {
                drawDependencies();
            }
        });

        window.addEventListener('resize', reflow);

        // Bars are positioned in pixels from the track's measured width, so anything
        // that changes the layout after paint (late fonts, a scrollbar appearing, the
        // sidebar collapsing) has to trigger a reposition.
        if (window.ResizeObserver) {
            new window.ResizeObserver(reflow).observe(root);
        }

        let persistedCompact = null;
        try {
            persistedCompact = window.localStorage.getItem(COMPACT_KEY);
        } catch (error) {
            persistedCompact = null;
        }
        if (persistedCompact === '1') {
            root.classList.add('rg-compact');
        }
    }

    wire();
    load();
}());
