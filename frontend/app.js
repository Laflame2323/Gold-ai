
const analyzeBtn = document.getElementById("analyzeBtn");
const signal = document.getElementById("signal");
const message = document.getElementById("message");

analyzeBtn.addEventListener("click", function () {
  signal.textContent = "WAIT";
  message.textContent = "Gold AI is waiting for real market data. No trade recommendation is available yet.";
  signal.style.color = "#f5bd45";
});
