const API_URL = "https://gold-ai-backend-p9el.onrender.com";
const $ = (id) => document.getElementById(id);

let selectedTimeframe = "M15";
let chart = null;
let candleSeries = null;
let candleResizeObserver = null;
let spotRequestInFlight = false;
let candleRequestInFlight = false;
let lastSpotPrice = null;
let lastCandleStamp = null;
let monitorRequestInFlight = false;
const monitoredTimeframes = ["M1", "M5", "M15", "M30", "H1", "H4"];
const feedHealth = new Map();
let marketAlerts = [];

function addMarketAlert(type, title, detail) {
  const alert = { type, title, detail, time: new Date() };
  marketAlerts.unshift(alert);
  marketAlerts = marketAlerts.slice(0, 8);
  renderMarketAlerts();
}

function renderMarketAlerts() {
  const list = $("alertList");
  if (!list) return;
  if (!marketAlerts.length) {
    list.innerHTML = '<div class="alert-empty">No feed alerts. Gold AI is monitoring the market data.</div>';
    return;
  }
  list.replaceChildren();
  marketAlerts.forEach((alert) => {
    const item = document.createElement("div");
    item.className = "market-alert " + alert.type;
    const marker = document.createElement("span");
    marker.className = "alert-marker";
    const copy = document.createElement("div");
    copy.className = "alert-copy";
    const heading = document.createElement("strong");
    heading.textContent = alert.title;
    const description = document.createElement("small");
    description.textContent = alert.detail;
    const time = document.createElement("time");
    time.textContent = alert.time.toLocaleTimeString();
    copy.append(heading, description);
    item.append(marker, copy, time);
    list.appendChild(item);
  });
}

function updateFeedAlert(key, healthy, label, detail) {
  const previous = feedHealth.get(key);
  feedHealth.set(key, healthy);
  if (previous === undefined && !healthy) {
    addMarketAlert("warning", label + " needs attention", detail);
  } else if (previous === true && !healthy) {
    addMarketAlert("warning", label + " became unavailable", detail);
  } else if (previous === false && healthy) {
    addMarketAlert("success", label + " recovered", detail);
  }
}

function setApiStatus(text, healthy = false) {
  $("apiStatus").textContent = text;
  const dot = document.querySelector(".connection-dot");
  if (dot) {
    dot.style.background = healthy ? "var(--green)" : "var(--gold)";
    dot.style.boxShadow = healthy ? "0 0 10px #25c58a66" : "none";
  }
}

function setChartStatus(text, state = "") {
  const status = $("chartStatus");
  status.className = "chart-status" + (state ? " " + state : "");
  status.innerHTML = "<i></i>" + text;
}

function initialiseChart() {
  const chartElement = $("priceChart");
  if (!chartElement || !window.LightweightCharts) {
    $("chartLoading").textContent = "Chart library could not load. Refresh the page to try again.";
    return false;
  }

  chart = LightweightCharts.createChart(chartElement, {
    width: chartElement.clientWidth,
    height: chartElement.clientHeight,
    layout: {
      background: { color: "#111a29" },
      textColor: "#8796aa",
      fontFamily: "DM Mono, monospace",
      fontSize: 10
    },
    grid: {
      vertLines: { color: "#1d2a3c" },
      horzLines: { color: "#1d2a3c" }
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: {
      borderColor: "#2b394d",
      scaleMargins: { top: 0.12, bottom: 0.12 }
    },
    timeScale: {
      borderColor: "#2b394d",
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 5,
      barSpacing: 8
    },
    localization: {
      priceFormatter: (price) => price.toFixed(2)
    },
    handleScroll: { vertTouchDrag: false }
  });

  candleSeries = chart.addCandlestickSeries({
    upColor: "#25c58a",
    downColor: "#ef6670",
    borderUpColor: "#25c58a",
    borderDownColor: "#ef6670",
    wickUpColor: "#25c58a",
    wickDownColor: "#ef6670",
    priceLineColor: "#e8b64d",
    priceLineWidth: 1
  });

  if (typeof ResizeObserver !== "undefined") {
    candleResizeObserver = new ResizeObserver(() => {
      if (chart && chartElement.clientWidth > 0 && chartElement.clientHeight > 0) {
        chart.applyOptions({
          width: chartElement.clientWidth,
          height: chartElement.clientHeight
        });
      }
    });
    candleResizeObserver.observe(chartElement);
  }

  return true;
}

function formatPrice(value) {
  return Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

async function loadGoldPrice() {
  if (spotRequestInFlight) return;
  spotRequestInFlight = true;
  try {
    const response = await fetch(API_URL + "/market/spot", { cache: "no-store" });
    if (!response.ok) throw new Error("Price endpoint returned " + response.status);
    const data = await response.json();
    if (data.price === undefined || data.price === null) throw new Error("Price missing");

    $("goldPrice").textContent = "$" + formatPrice(data.price);
    const receivedAt = new Date();
    $("priceUpdated").textContent = "Price received at " + receivedAt.toLocaleTimeString();
    const changed = lastSpotPrice !== null && Number(lastSpotPrice) !== Number(data.price);
    lastSpotPrice = data.price;
    $("monitorSpotState").textContent = "LIVE · $" + formatPrice(data.price);
    $("monitorSpotTime").textContent = "Checked " + receivedAt.toLocaleTimeString() + (changed ? " · price changed" : "");
    $("monitorMessage").textContent = "Spot feed reachable. Price updates are checked every 15 seconds; provider timestamps remain authoritative.";
    updateMonitorState();
    updateFeedAlert("spot", true, "Spot feed", "The reference spot-price endpoint is responding again.");
    setApiStatus("Connected", true);
  } catch (error) {
    $("goldPrice").textContent = "Unavailable";
    $("priceUpdated").textContent = "Could not retrieve the spot price";
    $("monitorSpotState").textContent = "OFFLINE";
    $("monitorSpotTime").textContent = "Last check failed";
    $("monitorMessage").textContent = "Spot feed request failed. Waiting for the next automatic check.";
    updateMonitorState();
    updateFeedAlert("spot", false, "Spot feed", "Gold AI could not retrieve the latest reference price.");
    setApiStatus("Offline", false);
  } finally {
    spotRequestInFlight = false;
  }
}

async function loadCandles(timeframe = selectedTimeframe) {
  if (candleRequestInFlight) return;
  candleRequestInFlight = true;
  selectedTimeframe = timeframe;
  $("selectedTimeframe").textContent = timeframe;
  $("chartLoading").classList.remove("hidden");
  $("chartLoading").textContent = "Loading " + timeframe + " candles...";
  setChartStatus("Loading candles");

  document.querySelectorAll("[data-timeframe]").forEach((button) => {
    button.classList.toggle("selected", button.dataset.timeframe === timeframe);
  });

  try {
    const response = await fetch(
      API_URL + "/market/candles?timeframe=" + encodeURIComponent(timeframe),
      { cache: "no-store" }
    );
    if (!response.ok) {
      let detail = "Candle request failed (" + response.status + ")";
      try {
        const body = await response.json();
        if (body.detail) detail = body.detail;
      } catch (_) {}
      throw new Error(detail);
    }

    const data = await response.json();
    if (!Array.isArray(data.candles) || data.candles.length === 0) {
      throw new Error("The provider returned no candles.");
    }
    if (!candleSeries && !initialiseChart()) throw new Error("Chart could not be initialised.");

    const chartCandles = data.candles.map((candle) => ({
      time: Number(candle.time),
      open: Number(candle.open),
      high: Number(candle.high),
      low: Number(candle.low),
      close: Number(candle.close)
    })).filter((candle) =>
      Number.isFinite(candle.time) &&
      Number.isFinite(candle.open) &&
      Number.isFinite(candle.high) &&
      Number.isFinite(candle.low) &&
      Number.isFinite(candle.close)
    );

    if (!chartCandles.length) throw new Error("No valid OHLC candles were received.");

    candleSeries.setData(chartCandles);
    chart.timeScale().fitContent();
    $("chartLoading").classList.add("hidden");
    $("candleCount").textContent = String(data.count ?? chartCandles.length);
    $("candleMeta").textContent = chartCandles.length + " candles · " + timeframe;
    $("lastCandleTime").textContent = data.last_candle_at
      ? "Last bar: " + new Date(data.last_candle_at).toLocaleString()
      : "Last bar time unavailable";

    const recent = data.data_status === "recent";
    const checkedAt = new Date();
    const candleStamp = data.last_candle_at ? new Date(data.last_candle_at) : null;
    const candleChanged = candleStamp && lastCandleStamp && candleStamp.getTime() !== lastCandleStamp.getTime();
    if (candleStamp) lastCandleStamp = candleStamp;
    $("monitorCandleState").textContent = recent ? "RECENT" : "STALE";
    $("monitorCandleTime").textContent = "Checked " + checkedAt.toLocaleTimeString() + (candleChanged ? " · new closed bar" : " · no new closed bar");
    $("monitorLastBar").textContent = candleStamp ? candleStamp.toLocaleTimeString() : "—";
    $("monitorBarAge").textContent = Number.isFinite(Number(data.age_seconds)) ? Math.floor(Number(data.age_seconds)) + " seconds old" : "Age unavailable";
    $("monitorMessage").textContent = recent ? "Candle feed is within its freshness limit. The monitor will continue checking for new completed bars." : "Candle feed is stale. Gold AI will show this warning and will not treat old candles as live conditions.";
    updateMonitorState();
    updateFeedAlert("chart-candles", recent, timeframe + " chart candles", recent ? "The selected timeframe has fresh closed candles." : "The selected timeframe data is older than its freshness limit.");
    $("feedStatus").textContent = recent ? "Recent" : "Stale";
    $("feedStatus").className = "status-text " + (recent ? "ok" : "bad");
    setChartStatus(recent ? "Recent data" : "Stale data", recent ? "connected" : "stale");
    setApiStatus("Connected", true);
  } catch (error) {
    $("chartLoading").classList.remove("hidden");
    $("chartLoading").textContent = error.message || "Could not load market candles.";
    $("candleCount").textContent = "—";
    $("candleMeta").textContent = "Candle data unavailable";
    $("lastCandleTime").textContent = "—";
    $("feedStatus").textContent = "Unavailable";
    $("feedStatus").className = "status-text bad";
    $("monitorCandleState").textContent = "UNAVAILABLE";
    $("monitorCandleTime").textContent = "Last check failed";
    $("monitorMessage").textContent = "Candle request failed. The monitor will retry automatically.";
    updateMonitorState();
    updateFeedAlert("chart-candles", false, timeframe + " chart candles", "The candle endpoint could not be reached.");
    setChartStatus("Feed unavailable", "error");
  } finally {
    candleRequestInFlight = false;
  }
}

async function refreshAllTimeframeMonitor() {
  if (monitorRequestInFlight) return;
  monitorRequestInFlight = true;
  const results = await Promise.all(monitoredTimeframes.map(async (timeframe) => {
    try {
      const response = await fetch(API_URL + "/market/candles?timeframe=" + timeframe, { cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      return { timeframe, recent: data.data_status === "recent", age: data.age_seconds, last: data.last_candle_at, count: data.count };
    } catch (error) {
      return { timeframe, error: error.message };
    }
  }));
  results.forEach((item) => {
    const healthy = !item.error && item.recent;
    updateFeedAlert("timeframe-" + item.timeframe, healthy, item.timeframe + " timeframe", item.error ? item.error : healthy ? "Closed-candle data is within its freshness limit." : "The latest closed candle is outside its freshness limit.");
    const state = $("tf-" + item.timeframe);
    const detail = $("tf-detail-" + item.timeframe);
    if (!state || !detail) return;
    if (item.error) {
      state.textContent = "OFFLINE";
      state.className = "tf-state bad";
      detail.textContent = item.error;
    } else {
      state.textContent = item.recent ? "RECENT" : "STALE";
      state.className = "tf-state " + (item.recent ? "ok" : "bad");
      const age = Number.isFinite(Number(item.age)) ? Math.floor(Number(item.age)) + "s old" : "age n/a";
      const bar = item.last ? new Date(item.last).toLocaleTimeString() : "bar time n/a";
      detail.textContent = bar + " · " + age;
    }
  });
  const healthy = results.filter((item) => !item.error && item.recent).length;
  const summary = $("monitorTimeframeSummary");
  if (summary) summary.textContent = healthy + " / " + monitoredTimeframes.length + " timeframes recent";
  monitorRequestInFlight = false;
}

function updateMonitorState() {
  const spotText = $("monitorSpotState").textContent;
  const spotOk = spotText !== "OFFLINE" && spotText !== "Checking";
  const candleText = $("monitorCandleState").textContent;
  const candleOk = candleText === "RECENT";
  const state = $("monitorState");
  if (!state) return;
  state.className = "monitor-pill " + (spotOk && candleOk ? "online" : spotOk || candleText === "STALE" ? "warning" : "offline");
  state.innerHTML = "<i></i>" + (spotOk && candleOk ? "FEEDS HEALTHY" : spotOk ? "CHECK FEED" : "CONNECTING / OFFLINE");
}

async function analyseGold() {
  const button = $("analyzeBtn");
  button.disabled = true;
  button.innerHTML = "<span>✳</span> Analysing market...";

  try {
    const response = await fetch(API_URL + "/analyse", { cache: "no-store" });
    if (!response.ok) throw new Error("Analysis request failed (" + response.status + ")");
    const data = await response.json();
    const signal = String(data.signal || "WAIT").toUpperCase();

    $("signal").textContent = signal;
    $("signal").className = "signal-value " + (
      signal === "BUY" ? "buy" : signal === "SELL" ? "sell" : "wait"
    );
    const researchSignal = String(data.research_signal || "WAIT").toUpperCase();
    const technicalBias = String(data.technical_bias || "NEUTRAL").toUpperCase();
    const alignment = Number(data.alignment_score);
    const alignmentText = Number.isFinite(alignment)
      ? " Alignment score: " + alignment.toFixed(3) + "."
      : "";
    $("message").textContent =
      (data.message || "No analysis message was returned.") +
      " Research-only bias: " + technicalBias +
      " (" + researchSignal + ")." + alignmentText;
    $("signalState").textContent = data.execution_ready ? "BROKER VERIFIED" : "RESEARCH ONLY";
    $("modelStatus").textContent = data.ai_trained
      ? "Model status reported as trained. Always review the data and risk before trading."
      : "This is indicator-based research, not a trained AI model or live trade recommendation.";
    const regime = data.market_regime || {};
    $("regimeLabel").textContent = regime.label || "UNCONFIRMED";
    $("regimeDirection").textContent = regime.direction || "NEUTRAL";
    $("regimeState").textContent = regime.label === "UNCONFIRMED" ? "DATA INCOMPLETE" : "RESEARCH ONLY";
    $("regimeExplanation").textContent = regime.explanation || "Regime classification unavailable.";
    $("regimeHigher").textContent = regime.higher_timeframe_alignment || "—";
    $("regimeEntry").textContent = regime.entry_timeframe_alignment || "—";
    $("regimeScore").textContent = Number.isFinite(Number(regime.alignment_score)) ? Number(regime.alignment_score).toFixed(3) : "—";
    $("regimeRisk").textContent = regime.risk_note || "Research context only; verify broker data.";
    $("entryValue").textContent = data.entry ?? "—";
    $("stopValue").textContent = data.stop_loss ?? "—";
    $("targetValue").textContent = data.take_profit ?? "—";
  } catch (error) {
    $("signal").textContent = "ERROR";
    $("signal").className = "signal-value wait";
    $("signalState").textContent = "OFFLINE";
    $("message").textContent = error.message || "Gold AI could not complete the analysis.";
  } finally {
    button.disabled = false;
    button.innerHTML = "<span>✳</span> Analyse gold market <b>→</b>";
  }
}

function addChatMessage(role, message) {
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble " + (role === "user" ? "user-bubble" : "assistant-bubble");
  const label = document.createElement("span");
  label.textContent = role === "user" ? "YOU" : "GOLD AI";
  bubble.appendChild(label);
  bubble.appendChild(document.createTextNode(message));
  $("chatMessages").appendChild(bubble);
  $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
  return bubble;
}

async function sendAssistantMessage(event) {
  event.preventDefault();
  const input = $("userPrompt");
  const prompt = input.value.trim();
  if (!prompt) return;

  addChatMessage("user", prompt);
  input.value = "";
  const reply = addChatMessage("assistant", "Thinking...");
  const sendButton = $("sendPrompt");
  sendButton.disabled = true;

  try {
    const response = await fetch(API_URL + "/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt })
    });
    if (!response.ok) throw new Error("Assistant request failed.");
    const data = await response.json();
    reply.lastChild.textContent = data.response || "I could not prepare a response.";
  } catch (error) {
    reply.lastChild.textContent = "I cannot connect to the assistant right now. Please try again.";
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
}

document.querySelectorAll("[data-timeframe]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.timeframe !== selectedTimeframe) {
      loadCandles(button.dataset.timeframe);
    }
  });
});

$("analyzeBtn").addEventListener("click", analyseGold);
$("clearAlerts").addEventListener("click", () => { marketAlerts = []; renderMarketAlerts(); });
$("refreshBtn").addEventListener("click", () => {
  loadGoldPrice();
  loadCandles(selectedTimeframe);
});
$("chatForm").addEventListener("submit", sendAssistantMessage);

loadGoldPrice();
loadCandles("M15");
refreshAllTimeframeMonitor();
setInterval(loadGoldPrice, 15000);
setInterval(() => loadCandles(selectedTimeframe), 60000);
setInterval(refreshAllTimeframeMonitor, 60000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    loadGoldPrice();
    loadCandles(selectedTimeframe);
    refreshAllTimeframeMonitor();
  }
});
