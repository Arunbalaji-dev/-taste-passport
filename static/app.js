const button = document.getElementById("check-btn");
const result = document.getElementById("result");

// Small helper: one line showing a key as configured / not configured.
function keyLine(label, configured) {
  const mark = configured ? "✅ configured" : "⚠️ not configured";
  return `<li>${label}: ${mark}</li>`;
}

async function checkConnection() {
  button.disabled = true;
  result.innerHTML = '<p class="text-slate-500">Checking…</p>';
  try {
    // Relative URL: works on localhost and on the deployed site.
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("Server returned " + response.status);
    const data = await response.json();
    result.innerHTML = `
      <div class="rounded-xl border border-green-200 bg-green-50 p-4 text-green-800">
        <p class="font-semibold">Connected (v${data.version})</p>
        <ul class="mt-2 space-y-1 text-sm">
          ${keyLine("Qloo key", data.qloo_key_configured)}
          ${keyLine("LLM key", data.llm_key_configured)}
        </ul>
      </div>`;
  } catch (err) {
    result.innerHTML = `
      <div class="rounded-xl border border-red-200 bg-red-50 p-4 text-red-800">
        Couldn't reach the server. If the app was asleep, wait a few seconds and try again.
      </div>`;
  } finally {
    button.disabled = false;
  }
}

button.addEventListener("click", checkConnection);
