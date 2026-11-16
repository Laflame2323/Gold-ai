
const API_URL = "https://gold-ai-backend-p9el.onrender.com";

const analyzeBtn = document.getElementById("analyzeBtn");
const signal = document.getElementById("signal");
const message = document.getElementById("message");

analyzeBtn.addEventListener("click", async function () {
    signal.textContent = "ANALYSING...";
    message.textContent = "Connecting to Gold AI server...";

    analyzeBtn.disabled = true;

    try {
        const response = await fetch(`${API_URL}/analyse`);

        if (!response.ok) {
            throw new Error("Server request failed");
        }

        const data = await response.json();

        signal.textContent = data.signal;
        message.textContent = data.message;

        if (data.signal === "BUY") {
            signal.style.color = "#22c55e";
        } else if (data.signal === "SELL") {
            signal.style.color = "#ef4444";
        } else {
            signal.style.color = "#f5bd45";
        }

    } catch (error) {
        signal.textContent = "ERROR";
        message.textContent = "Could not connect to Gold AI. Please try again.";
    }

    analyzeBtn.disabled = false;
});

