(function () {
  async function api(method, url, body) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const r = await fetch(url, opts);
    return r.ok ? r.json() : null;
  }

  function refreshMap() {
    if (typeof loadClusters === 'function') loadClusters().then(() => {
      if (typeof setupDropTargets === 'function') setupDropTargets();
      if (typeof loadSpreads === 'function') loadSpreads();
    });
  }

  function refreshMetrics() {
    if (typeof loadMetricsSummary === 'function') loadMetricsSummary();
  }

  const STAGES = [
    // --- Act 1: Setup ---
    {
      id: 'healthy-fleet',
      section: 'walkthrough',
      title: '1. Healthy Fleet',
      desc: 'Three clusters on the map, all green: vai (California, 8 GPUs), satch (Portland, 4 GPUs), and bumblefoot (New York, 4 GPUs). Models are loaded but GPUs are idle — no traffic is flowing yet. Click any cluster marker to inspect.',
      async enter() {
        await api('POST', '/api/demo/reset');
        await api('POST', '/api/demo/scenario', {
          cluster_overrides: {
            vai: { health: 'green', health_details: 'healthy', gpu_avg: 3.0 },
            satch: { health: 'green', health_details: 'healthy', gpu_avg: 2.0 },
            bumblefoot: { health: 'green', health_details: 'healthy', gpu_avg: 1.0 },
          },
          traffic_multipliers: { satch: 0, bumblefoot: 0 },
        });
        refreshMap();
        refreshMetrics();
      },
    },
    {
      id: 'explore-cluster',
      section: 'walkthrough',
      title: '2. Explore a Cluster',
      desc: 'Click vai (California). The sidebar shows 2 deployed models (Qwen3-0.6B and Granite 8B, both Ready), 5/5 nodes healthy, OCP 4.18.6 on Azure, and RHOAI operator components all Succeeded.',
      enter() {
        const marker = typeof markers !== 'undefined' && markers['vai'];
        if (marker) marker.fire('click');
      },
    },
    {
      id: 'deploy-model',
      section: 'walkthrough',
      title: '3. Deploy a Model',
      desc: 'Drag a model from the Model Library (top of sidebar) onto a cluster marker on the map. The deploy dialog lets you set replicas and GPU count. The model appears in the cluster panel as "Progressing."',
      enter() {
        const sidebar = document.getElementById('sidebar');
        if (sidebar) sidebar.scrollTop = 0;
      },
    },
    {
      id: 'register-spread',
      section: 'walkthrough',
      title: '4. Register a Spread',
      desc: 'Under Spreads in the sidebar, click "+ Register Spread." Select a model, pick vai as the hub (it has the "hub" tag), and choose spoke clusters. Traffic lines appear on the map — but no requests are flowing yet.',
      enter() {},
    },
    // --- Act 2: Growth ---
    {
      id: 'traffic-begins',
      section: 'walkthrough',
      title: '5. Traffic Begins',
      desc: 'First requests start flowing through the spreads. Thin animated lines appear between the hub and spokes. Traffic is light — around 8-12 req/min per spoke. GPU utilization begins climbing from idle.',
      async enter() {
        await api('POST', '/api/demo/scenario', {
          cluster_overrides: {
            vai: { health: 'green', health_details: 'healthy', gpu_avg: 25.0 },
            satch: { health: 'green', health_details: 'healthy', gpu_avg: 20.0 },
            bumblefoot: { health: 'green', health_details: 'healthy', gpu_avg: 15.0 },
          },
          traffic_multipliers: { satch: 0.2, bumblefoot: 0.2 },
        });
        refreshMap();
        refreshMetrics();
      },
    },
    {
      id: 'traffic-ramps',
      section: 'walkthrough',
      title: '6. Traffic Ramps Up',
      desc: 'Load increases to full production rate. Lines thicken as traffic climbs to ~50 req/min per spoke. GPU utilization rises significantly across the fleet — the metrics strip shows the growth.',
      async enter() {
        await api('POST', '/api/demo/scenario', {
          cluster_overrides: {
            vai: { health: 'green', health_details: 'healthy', gpu_avg: 55.0 },
            satch: { health: 'green', health_details: 'healthy', gpu_avg: 48.0 },
            bumblefoot: { health: 'green', health_details: 'healthy', gpu_avg: 38.0 },
          },
          traffic_multipliers: {},
        });
        refreshMap();
        refreshMetrics();
      },
    },
    // --- Act 3: Crisis ---
    {
      id: 'cluster-pressure',
      section: 'walkthrough',
      title: '7. Cluster Under Pressure',
      desc: 'Satch turns yellow. GPU jumps to 92%, one worker node goes NotReady. Traffic still flows but latency is creeping up. A warning sign of what is coming.',
      async enter() {
        await api('POST', '/api/demo/scenario', {
          cluster_overrides: {
            vai: { health: 'green', health_details: 'healthy', gpu_avg: 60.0 },
            satch: {
              health: 'yellow',
              health_details: 'GPU pressure — 1 worker NotReady',
              gpu_avg: 92.0,
            },
            bumblefoot: { health: 'green', health_details: 'healthy', gpu_avg: 42.0 },
          },
        });
        refreshMap();
        refreshMetrics();
      },
    },
    {
      id: 'cluster-overload',
      section: 'walkthrough',
      title: '8. Cluster Overloaded',
      desc: 'Satch goes red. GPU hits 98%, 2 workers NotReady, latency spikes. Vai and bumblefoot turn yellow absorbing rerouted inference. Fleet-wide GPU utilization jumps in the metrics strip.',
      async enter() {
        await api('POST', '/api/demo/scenario', {
          cluster_overrides: {
            satch: {
              health: 'red',
              health_details: 'GPU thermal throttle — 2 workers NotReady',
              gpu_avg: 98.0,
            },
            vai: {
              health: 'yellow',
              health_details: 'GPU pressure — absorbing rerouted load',
              gpu_avg: 78.0,
            },
            bumblefoot: {
              health: 'yellow',
              health_details: 'GPU pressure — absorbing rerouted load',
              gpu_avg: 68.0,
            },
          },
        });
        refreshMap();
        refreshMetrics();
      },
    },
    {
      id: 'traffic-reroute',
      section: 'walkthrough',
      title: '9. Traffic Re-routes',
      desc: 'The routing layer detects satch is degraded (latency 1800ms). Traffic diverts: satch drops to a trickle while bumblefoot absorbs the load at 2.5x. Watch the line thickness shift on the map.',
      async enter() {
        await api('POST', '/api/demo/scenario', {
          cluster_overrides: {
            satch: {
              health: 'red',
              health_details: 'GPU thermal throttle — 2 workers NotReady',
              gpu_avg: 98.0,
              latency_ms: 1800,
            },
            vai: {
              health: 'yellow',
              health_details: 'GPU pressure — absorbing rerouted load',
              gpu_avg: 82.0,
            },
            bumblefoot: {
              health: 'yellow',
              health_details: 'GPU pressure — absorbing rerouted load',
              gpu_avg: 74.0,
            },
          },
          traffic_multipliers: {
            satch: 0.05,
            bumblefoot: 2.5,
          },
        });
        refreshMap();
        refreshMetrics();
      },
    },
    // --- Act 4: Resolution ---
    {
      id: 'recovery',
      section: 'walkthrough',
      title: '10. Recovery',
      desc: 'Satch recovers: GPU drops to 30%, workers come back online, marker turns green. Vai and bumblefoot cool down as load rebalances — their markers return to green. Traffic begins normalizing.',
      async enter() {
        await api('POST', '/api/demo/scenario', {
          cluster_overrides: {
            satch: {
              health: 'green',
              health_details: 'recovered — all nodes ready',
              gpu_avg: 30.0,
            },
            vai: {
              health: 'green',
              health_details: 'load normalizing',
              gpu_avg: 52.0,
            },
            bumblefoot: {
              health: 'green',
              health_details: 'load normalizing',
              gpu_avg: 40.0,
            },
          },
          traffic_multipliers: {
            satch: 0.6,
            bumblefoot: 1.4,
          },
        });
        refreshMap();
        refreshMetrics();
      },
    },
    {
      id: 'steady-state',
      section: 'walkthrough',
      title: '11. Steady State',
      desc: 'Fleet fully recovered. All three clusters green, GPU utilization at healthy production levels, traffic balanced. Open the Chart panel (bottom strip) to see GPU and throughput trends over time.',
      async enter() {
        await api('POST', '/api/demo/scenario', {
          cluster_overrides: {
            vai: { health: 'green', health_details: 'healthy', gpu_avg: 52.0 },
            satch: { health: 'green', health_details: 'healthy', gpu_avg: 45.0 },
            bumblefoot: { health: 'green', health_details: 'healthy', gpu_avg: 35.0 },
          },
          traffic_multipliers: {},
        });
        refreshMap();
        refreshMetrics();
      },
    },
    // --- Explore on Your Own ---
    {
      id: 'try-add-cluster',
      section: 'explore',
      title: 'Add a Cluster',
      desc: 'Scroll down in the sidebar and click "+ Add Cluster." Enter a name, display name, and coordinates. No kubeconfig or connectivity check in demo mode — the cluster appears on the map immediately.',
      enter() {
        const sidebar = document.getElementById('sidebar');
        if (sidebar) sidebar.scrollTop = sidebar.scrollHeight;
      },
    },
    {
      id: 'try-move-model',
      section: 'explore',
      title: 'Move a Model',
      desc: 'Click a cluster to see its deployed models. Drag any model from the cluster panel onto a different cluster marker. The model is removed from the source and added to the target.',
      enter() {},
    },
    {
      id: 'try-deploy-app',
      section: 'explore',
      title: 'Deploy an App',
      desc: 'Expand the Apps section in the sidebar. Drag "Reverse Words" or "KDummy" onto a cluster, or click "+ Custom App" to define your own image. Deployed apps show a clickable route URL.',
      enter() {},
    },
  ];

  const WALKTHROUGH_COUNT = STAGES.filter(s => s.section === 'walkthrough').length;

  const style = document.createElement('style');
  style.textContent = `
    #demo-guide-btn {
      position: fixed; top: 10px; right: 380px;
      width: 32px; height: 32px; border-radius: 50%;
      background: #ee0000; color: #fff; border: none;
      font-size: 16px; font-weight: 700; cursor: pointer;
      z-index: 1002; display: flex; align-items: center; justify-content: center;
      font-family: 'Red Hat Display', sans-serif;
      box-shadow: 0 2px 8px rgba(238,0,0,0.4);
      transition: transform 0.2s, box-shadow 0.2s;
    }
    #demo-guide-btn:hover {
      transform: scale(1.1);
      box-shadow: 0 4px 16px rgba(238,0,0,0.6);
    }
    #demo-guide-btn.active {
      background: #fff; color: #ee0000;
      box-shadow: 0 0 0 2px #ee0000;
    }
    #demo-guide-btn .pulse-ring {
      position: absolute; width: 100%; height: 100%;
      border-radius: 50%; border: 2px solid #ee0000;
      animation: demo-pulse 2s ease-out infinite;
    }
    @keyframes demo-pulse {
      0% { transform: scale(1); opacity: 0.6; }
      100% { transform: scale(2.2); opacity: 0; }
    }

    #demo-guide-panel {
      display: none; position: fixed; top: 50px; right: 380px;
      width: 360px; max-height: calc(100vh - 120px);
      background: #1a1a1a; border: 1px solid #ee0000; border-radius: 8px;
      z-index: 1002; overflow-y: auto; font-family: 'Red Hat Display', sans-serif;
      box-shadow: 0 8px 32px rgba(0,0,0,0.6);
    }
    #demo-guide-panel.open { display: block; }

    #demo-guide-header {
      padding: 14px 16px 10px; border-bottom: 1px solid #333;
      display: flex; justify-content: space-between; align-items: center;
    }
    #demo-guide-header h3 {
      font-size: 13px; font-weight: 600; color: #ee0000;
      text-transform: uppercase; letter-spacing: 1px; margin: 0;
    }
    #demo-guide-header .demo-badge {
      font-size: 10px; background: #ee0000; color: #fff;
      padding: 2px 8px; border-radius: 10px; font-weight: 600;
      letter-spacing: 0.5px;
    }

    .demo-section-divider {
      padding: 10px 16px 6px; font-size: 10px; font-weight: 600;
      color: #666; text-transform: uppercase; letter-spacing: 1.5px;
      border-bottom: 1px solid #262626;
      background: #141414;
    }

    .demo-stage {
      padding: 12px 16px; border-bottom: 1px solid #262626;
      cursor: pointer; transition: background 0.15s;
    }
    .demo-stage:last-child { border-bottom: none; }
    .demo-stage:hover { background: #222; }
    .demo-stage.current { background: #2a1a1a; border-left: 3px solid #ee0000; }
    .demo-stage.completed { opacity: 0.55; }

    .demo-stage-title {
      font-size: 13px; font-weight: 600; color: #fff; margin-bottom: 4px;
      display: flex; align-items: center; gap: 8px;
    }
    .demo-stage-check {
      width: 16px; height: 16px; border-radius: 50%;
      border: 2px solid #444; display: inline-flex;
      align-items: center; justify-content: center;
      font-size: 10px; flex-shrink: 0;
      transition: border-color 0.2s, background 0.2s;
    }
    .demo-stage.completed .demo-stage-check {
      border-color: #00cc66; background: #00cc66; color: #fff;
    }
    .demo-stage.current .demo-stage-check {
      border-color: #ee0000;
    }
    .demo-stage-desc {
      font-size: 12px; color: #999; line-height: 1.5;
      margin-left: 24px; display: none;
    }
    .demo-stage.current .demo-stage-desc { color: #ccc; display: block; }

    #demo-guide-footer {
      padding: 10px 16px; border-top: 1px solid #333;
      display: flex; gap: 8px;
    }
    #demo-guide-footer button {
      flex: 1; padding: 6px 12px; border-radius: 4px;
      font-family: inherit; font-size: 12px; font-weight: 500;
      cursor: pointer; border: none; transition: background 0.2s;
    }
    #demo-guide-prev {
      background: #333; color: #ccc;
    }
    #demo-guide-prev:hover { background: #444; }
    #demo-guide-prev:disabled { opacity: 0.3; cursor: default; }
    #demo-guide-next {
      background: #ee0000; color: #fff;
    }
    #demo-guide-next:hover { background: #cc0000; }

    body.light #demo-guide-panel { background: #fff; border-color: #ee0000; box-shadow: 0 8px 32px rgba(0,0,0,0.15); }
    body.light .demo-section-divider { background: #f9fafb; color: #9ca3af; border-bottom-color: #eee; }
    body.light .demo-stage:hover { background: #f9f9f9; }
    body.light .demo-stage.current { background: #fff5f5; }
    body.light .demo-stage-title { color: #111; }
    body.light .demo-stage-desc { color: #666; }
    body.light .demo-stage.current .demo-stage-desc { color: #333; }
    body.light .demo-stage { border-bottom-color: #eee; }
    body.light #demo-guide-header { border-bottom-color: #eee; }
    body.light #demo-guide-footer { border-top-color: #eee; }
    body.light #demo-guide-prev { background: #e5e7eb; color: #374151; }
    body.light #demo-guide-prev:hover { background: #d1d5db; }
    body.light #demo-guide-btn.active { background: #fff; }

    #demo-nav {
      position: fixed; top: 10px; right: 420px;
      display: flex; align-items: center; gap: 0;
      z-index: 1002; font-family: 'Red Hat Display', sans-serif;
      background: #1a1a1a; border: 1px solid #333; border-radius: 6px;
      overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.4);
      height: 32px;
    }
    #demo-nav button {
      background: none; border: none; color: #ccc;
      font-size: 14px; font-weight: 600; cursor: pointer;
      width: 28px; height: 32px; display: flex;
      align-items: center; justify-content: center;
      transition: background 0.15s, color 0.15s;
      font-family: inherit;
    }
    #demo-nav button:hover { background: #333; color: #fff; }
    #demo-nav button:disabled { opacity: 0.25; cursor: default; background: none; }
    #demo-nav-label {
      font-size: 11px; font-weight: 500; color: #ccc;
      padding: 0 10px; white-space: nowrap; user-select: none;
      max-width: 180px; overflow: hidden; text-overflow: ellipsis;
      border-left: 1px solid #333; border-right: 1px solid #333;
    }

    body.light #demo-nav { background: #fff; border-color: #d1d5db; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
    body.light #demo-nav button { color: #374151; }
    body.light #demo-nav button:hover { background: #f3f4f6; color: #111; }
    body.light #demo-nav-label { color: #374151; border-color: #e5e7eb; }
  `;
  document.head.appendChild(style);

  const nav = document.createElement('div');
  nav.id = 'demo-nav';
  nav.innerHTML = `
    <button id="demo-nav-prev" title="Previous stage" disabled>&lsaquo;</button>
    <span id="demo-nav-label">1. Healthy Fleet</span>
    <button id="demo-nav-next" title="Next stage">&rsaquo;</button>
  `;
  document.body.appendChild(nav);

  const btn = document.createElement('button');
  btn.id = 'demo-guide-btn';
  btn.title = 'Demo Guide';
  btn.innerHTML = '?<span class="pulse-ring"></span>';
  document.body.appendChild(btn);

  const panel = document.createElement('div');
  panel.id = 'demo-guide-panel';
  panel.innerHTML = `
    <div id="demo-guide-header">
      <h3>Demo Walkthrough</h3>
      <span class="demo-badge">DEMO MODE</span>
    </div>
    <div id="demo-guide-stages"></div>
    <div id="demo-guide-footer">
      <button id="demo-guide-prev" disabled>Previous</button>
      <button id="demo-guide-next">Next</button>
    </div>
  `;
  document.body.appendChild(panel);

  const stagesContainer = panel.querySelector('#demo-guide-stages');
  let lastSection = null;

  STAGES.forEach((stage, i) => {
    if (stage.section !== lastSection) {
      lastSection = stage.section;
      const divider = document.createElement('div');
      divider.className = 'demo-section-divider';
      divider.textContent = stage.section === 'walkthrough'
        ? 'Guided Walkthrough'
        : 'Explore on Your Own';
      stagesContainer.appendChild(divider);
    }

    const el = document.createElement('div');
    el.className = 'demo-stage' + (i === 0 ? ' current' : '');
    el.dataset.index = i;
    el.innerHTML = `
      <div class="demo-stage-title">
        <span class="demo-stage-check"></span>
        ${stage.title}
      </div>
      <div class="demo-stage-desc">${stage.desc}</div>
    `;
    el.addEventListener('click', () => goToStage(i));
    stagesContainer.appendChild(el);
  });

  let currentStage = 0;
  const completed = new Set();
  let transitioning = false;

  async function goToStage(index) {
    if (index < 0 || index >= STAGES.length || transitioning) return;

    transitioning = true;
    if (currentStage !== index) completed.add(currentStage);
    currentStage = index;
    updateStages();

    const stage = STAGES[index];
    if (stage.enter) {
      try { await stage.enter(); } catch (e) { /* ignore */ }
    }

    const current = stagesContainer.querySelector('.demo-stage.current');
    if (current) current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    transitioning = false;
  }

  function updateStages() {
    const els = stagesContainer.querySelectorAll('.demo-stage');
    els.forEach((el, i) => {
      el.classList.toggle('current', i === currentStage);
      el.classList.toggle('completed', completed.has(i));
      const check = el.querySelector('.demo-stage-check');
      check.textContent = completed.has(i) ? '✓' : '';
    });

    const prevBtn = panel.querySelector('#demo-guide-prev');
    const nextBtn = panel.querySelector('#demo-guide-next');
    prevBtn.disabled = currentStage === 0;
    if (currentStage === STAGES.length - 1) {
      nextBtn.textContent = 'Reset Demo';
    } else if (currentStage === WALKTHROUGH_COUNT - 1) {
      nextBtn.textContent = 'Explore More';
    } else {
      nextBtn.textContent = 'Next';
    }

    const navLabel = document.getElementById('demo-nav-label');
    const navPrev = document.getElementById('demo-nav-prev');
    const navNext = document.getElementById('demo-nav-next');
    if (navLabel) navLabel.textContent = STAGES[currentStage].title;
    if (navPrev) navPrev.disabled = currentStage === 0;
    if (navNext) navNext.disabled = currentStage === STAGES.length - 1;
  }

  panel.querySelector('#demo-guide-prev').addEventListener('click', () => {
    goToStage(currentStage - 1);
  });

  panel.querySelector('#demo-guide-next').addEventListener('click', async () => {
    if (currentStage === STAGES.length - 1) {
      await goToStage(0);
      completed.clear();
      updateStages();
    } else {
      await goToStage(currentStage + 1);
    }
  });

  document.getElementById('demo-nav-prev').addEventListener('click', () => {
    goToStage(currentStage - 1);
  });

  document.getElementById('demo-nav-next').addEventListener('click', () => {
    goToStage(currentStage + 1);
  });

  function togglePanel() {
    const isOpen = panel.classList.toggle('open');
    btn.classList.toggle('active', isOpen);
    const pulseRing = btn.querySelector('.pulse-ring');
    if (pulseRing && isOpen) pulseRing.remove();
  }

  btn.addEventListener('click', togglePanel);

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && panel.classList.contains('open')) {
      togglePanel();
    }
    if (e.key === 'ArrowLeft' && !e.target.closest('input, select, textarea')) {
      e.preventDefault();
      e.stopPropagation();
      goToStage(currentStage - 1);
    }
    if (e.key === 'ArrowRight' && !e.target.closest('input, select, textarea')) {
      e.preventDefault();
      e.stopPropagation();
      goToStage(currentStage + 1);
    }
  });
})();
