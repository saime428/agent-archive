const state = {
  runs: [],
  selectedRunId: null,
};

const els = {
  workspace: document.querySelector("#workspace-pill"),
  provider: document.querySelector("#provider-chip"),
  model: document.querySelector("#model-chip"),
  runList: document.querySelector("#run-list"),
  summary: document.querySelector("#summary-view"),
  selectedRunTitle: document.querySelector("#selected-run-title"),
  runState: document.querySelector("#run-state"),
  toolList: document.querySelector("#tool-list"),
  toolCallList: document.querySelector("#tool-call-list"),
  runSearch: document.querySelector("#run-search"),
};

async function loadJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${path} failed: ${text}`);
  }
  return response.json();
}

async function boot() {
  try {
    const [health, tools, runs] = await Promise.all([
      loadJson("/api/health"),
      loadJson("/api/tools"),
      loadJson("/api/runs"),
    ]);
    renderHealth(health);
    renderTools(tools.tools);
    state.runs = runs.runs;
    renderRuns();
    if (state.runs.length > 0) {
      await selectRun(state.runs[0].run_id);
    } else {
      renderEmptyRuns();
    }
  } catch (error) {
    els.summary.textContent = error instanceof Error ? error.message : String(error);
  }
}

function renderHealth(health) {
  els.workspace.textContent = health.workspace;
  els.provider.textContent = `provider: ${health.provider}`;
  els.model.textContent = `model: ${health.model}`;
}

function renderTools(tools) {
  els.toolList.replaceChildren(
    ...tools.map((tool) => {
      const item = document.createElement("article");
      item.className = "tool-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="tool-category"></div>
        <div class="tool-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = tool.name;
      item.querySelector(".tool-category").textContent = tool.category;
      item.querySelector(".tool-meta").textContent = `dry-run: ${tool.dry_run} · ${tool.description}`;
      return item;
    }),
  );
}

function renderRuns() {
  const query = els.runSearch.value.trim().toLowerCase();
  const runs = query ? state.runs.filter((run) => run.run_id.toLowerCase().includes(query)) : state.runs;
  if (runs.length === 0) {
    els.runList.innerHTML = '<div class="empty-state">No matching runs.</div>';
    return;
  }
  els.runList.replaceChildren(
    ...runs.map((run) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `run-item${run.run_id === state.selectedRunId ? " selected" : ""}`;
      button.innerHTML = `
        <div class="run-id"></div>
        <div class="run-meta"></div>
      `;
      button.querySelector(".run-id").textContent = run.run_id;
      button.querySelector(".run-meta").textContent = new Date(run.updated_at).toLocaleString();
      button.addEventListener("click", () => selectRun(run.run_id));
      return button;
    }),
  );
}

function renderEmptyRuns() {
  els.selectedRunTitle.textContent = "No runs yet";
  els.runState.textContent = "waiting";
  els.summary.textContent = "Run `agent run` or `agent chat` to create durable logs, then refresh this page.";
  els.toolCallList.innerHTML = '<div class="empty-state">No tool calls yet.</div>';
}

async function selectRun(runId) {
  state.selectedRunId = runId;
  renderRuns();
  const detail = await loadJson(`/api/runs/${encodeURIComponent(runId)}`);
  els.selectedRunTitle.textContent = detail.run_id;
  els.summary.textContent = detail.summary || "(summary is empty)";
  const lastCall = detail.tool_calls[detail.tool_calls.length - 1];
  els.runState.textContent = lastCall?.data?.observation?.status || "loaded";
  renderToolCalls(detail.tool_calls);
}

function renderToolCalls(toolCalls) {
  if (!toolCalls.length) {
    els.toolCallList.innerHTML = '<div class="empty-state">No tool calls recorded.</div>';
    return;
  }
  els.toolCallList.replaceChildren(
    ...toolCalls.map((call) => {
      const action = call.data?.action?.action?.name || "invalid";
      const observation = call.data?.observation?.summary || call.error || "No summary.";
      const status = call.data?.observation?.status || (call.valid ? "ok" : "invalid");
      const item = document.createElement("article");
      item.className = "trace-item";
      item.innerHTML = `
        <div class="tool-name"></div>
        <div class="trace-meta"></div>
        <div class="trace-meta"></div>
      `;
      item.querySelector(".tool-name").textContent = action;
      item.querySelectorAll(".trace-meta")[0].textContent = `line ${call.line_number} · ${status}`;
      item.querySelectorAll(".trace-meta")[1].textContent = observation;
      return item;
    }),
  );
}

els.runSearch.addEventListener("input", renderRuns);

boot();
