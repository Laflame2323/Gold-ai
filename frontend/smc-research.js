/* Gold AI SMC meta-label research UI.
   Uses the existing causal SMC + ATR triple-barrier research endpoint.
   Research only: no model persistence and no trade execution. */
(() => {
  const API_URL = "https://gold-ai-mtf-research.onrender.com";
  const $ = (id) => document.getElementById(id);
  const pct = (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(2) + "%" : "—";
  const KEY = "goldAiResearchHistoryV1";

  function historyRead() {
    try {
      const value = JSON.parse(localStorage.getItem(KEY) || "[]");
      return Array.isArray(value) ? value.slice(0, 10) : [];
    } catch (_) { return []; }
  }
  function historySave(item) {
    try {
      const items = historyRead();
      items.unshift(item);
      localStorage.setItem(KEY, JSON.stringify(items.slice(0, 10)));
    } catch (_) {}
  }
  function updateLabels() {
    const metrics = $("researchMetrics");
    if (metrics) {
      const labels = metrics.querySelectorAll(":scope > div > span");
      const notes = metrics.querySelectorAll(":scope > div > small");
      if (labels[0]) labels[0].textContent = "UNSEEN TEST WIN RATE · 60%+ SCORE";
      if (notes[0]) notes[0].textContent = "Accepted setups only · not all candles";
      if (labels[1]) labels[1].textContent = "META-MODEL BALANCED ACCURACY";
      if (notes[1]) notes[1].textContent = "How well it identifies winning rule-based setups";
      if (labels[2]) labels[2].textContent = "TEST MAJORITY BASELINE";
      if (notes[2]) notes[2].textContent = "Benchmark on the same test setups";
      if (labels[3]) labels[3].textContent = "ELIGIBLE SETUPS";
      if (notes[3]) notes[3].textContent = "Before confidence filtering";
    }
    const report = $("researchReport");
    if (report) {
      const labels = report.querySelectorAll(":scope > div > span");
      if (labels[4]) labels[4].textContent = "TRAINING META ACCURACY";
      if (labels[5]) labels[5].textContent = "VALIDATION META ACCURACY";
      if (labels[6]) labels[6].textContent = "TEST META SAMPLES";
    }
    const historyHeading = document.querySelector("#training-lab .history-heading strong");
    if (historyHeading) historyHeading.textContent = "Recent SMC research runs";
    const historyTable = document.querySelector("#researchHistory table");
    if (historyTable) {
      const headers = historyTable.querySelectorAll("th");
      if (headers[1]) headers[1].textContent = "WIN RATE";
    }
  }

  function render(data) {
    const model = data.meta_model_test || {};
    const baseline = data.test_majority_baseline_accuracy_pct;
    const threshold = (data.confidence_coverage || []).find((item) =>
      Number(item.meta_probability_threshold) === 0.60
    ) || (data.confidence_coverage || []).find((item) =>
      Number(item.meta_probability_threshold) === 0.55
    );
    const winRate = threshold ? threshold.accepted_trade_win_rate_pct : null;
    const accepted = threshold ? threshold.accepted_trades : 0;
    const coverage = threshold ? threshold.coverage_pct : 0;
    const gap = Number.isFinite(Number(model.accuracy_pct)) && Number.isFinite(Number(baseline))
      ? Number(model.accuracy_pct) - Number(baseline) : null;

    $("researchTestAccuracy").textContent = pct(winRate);
    $("researchTestSamples").textContent = accepted + " accepted / " + (model.samples || 0) + " unseen setups";
    $("researchBalancedAccuracy").textContent = pct(model.balanced_accuracy_pct);
    $("researchBaseline").textContent = pct(baseline);
    $("researchBaselineGap").textContent = gap === null
      ? "Comparison unavailable"
      : (gap >= 0 ? "+" : "") + gap.toFixed(2) + " points vs baseline";
    $("researchSamples").textContent = String(data.eligible_samples ?? "—");
    const splits = data.split_samples || {};
    $("researchSplits").textContent = "Train " + (splits.train ?? "—") +
      " · Validation " + (splits.validation ?? "—") + " · Test " + (splits.test ?? "—");
    const timeframes = data.timeframes || ["H4", "H1", "M30", "M15"];
    $("researchTimeframes").textContent = Array.from(new Set([data.base_timeframe || "M30", ...timeframes])).join(" + ");
    $("researchModelStatus").textContent = data.candidate_model_trained
      ? "SMC meta-candidate · not deployed" : "Not trained";
    $("researchSource").textContent = data.data_source || "Authenticated MT5 archive";
    $("researchTestStatus").textContent = data.status === "complete"
      ? "Untouched chronological test" : (data.status || "Incomplete");
    const best = (data.validation_candidates || []).slice().sort((a, b) =>
      Number(b.validation?.balanced_accuracy_pct || 0) - Number(a.validation?.balanced_accuracy_pct || 0)
    )[0];
    $("researchTrainAccuracy").textContent = "Not reported";
    $("researchValidationAccuracy").textContent = pct(best?.validation?.accuracy_pct);
    $("researchWalkForward").textContent = String(model.samples ?? "—") + " test setups";

    const limitations = " Meta-model accepted " + accepted + " setups (" + pct(coverage) +
      " coverage) at the 60% score threshold. " +
      "SMC features are causal price-action proxies, not verified institutional order flow.";
    let warning;
    if (!accepted) warning = "No test setups passed the confidence threshold; do not lower it just to create signals.";
    else if (winRate !== null && winRate < 50) warning = "Accepted-signal win rate is below 50%; this candidate is not ready.";
    else warning = "Review sample count, baseline and trading costs before drawing conclusions.";
    $("researchState").textContent = "SMC + ATR triple-barrier evaluation complete. " + warning + limitations;

    if (data.status === "complete") {
      historySave({
        createdAt: new Date().toISOString(),
        accuracy: winRate,
        balanced: model.balanced_accuracy_pct,
        baseline,
        samples: accepted
      });
      if (typeof window.renderResearchHistory === "function") window.renderResearchHistory();
      else if ($("researchHistory")) $("researchHistory").textContent = "Saved on this device.";
    }
    updateLabels();
  }

  async function run() {
    const button = $("runResearchBtn");
    const state = $("researchState");
    button.disabled = true;
    button.textContent = "Running SMC research…";
    state.textContent = "Loading the MT5 archive. Testing causal market-structure features with ATR-based profit and stop barriers. This can take a few minutes.";
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 180000);
    try {
      const url = API_URL + "/research/ml/evaluate-triple-barrier-mtf" +
        "?base_timeframe=M30&horizon=24&pt_atr=1.5&sl_atr=1.0";
      const response = await fetch(url, { cache: "no-store", signal: controller.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "SMC evaluation failed (" + response.status + ").");
      if (data.status !== "complete") {
        state.textContent = data.message || "SMC evaluation returned: " + (data.status || "unknown");
        return;
      }
      render(data);
    } catch (error) {
      state.textContent = error.name === "AbortError"
        ? "The research request exceeded three minutes. Check the research server before retrying."
        : (error.message || "Could not complete SMC research. Check the research server and MT5 archive.");
    } finally {
      clearTimeout(timeout);
      button.disabled = false;
      button.innerHTML = "<span>✳</span> Test SMC meta-model <b>→</b>";
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest && event.target.closest("#runResearchBtn");
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    run();
  }, true);

  updateLabels();
  const button = $("runResearchBtn");
  if (button) button.innerHTML = "<span>✳</span> Test SMC meta-model <b>→</b>";
})();
