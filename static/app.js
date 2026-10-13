// Taste Passport front end. Plain JavaScript, no build step.
// The dial control doubles as the tabs: each dial setting is fetched the first
// time it is chosen and kept in `state.cache`, so switching back is instant and
// we never run several AI requests at once (the free AI tier has a tight limit).

const DIALS = {
  comfort: { label: "Comfort", color: "#2f6fde", pin: "#2f6fde" },
  bridge: { label: "Bridge", color: "#b87a00", pin: "#e0a100" },
  adventure: { label: "Adventure", color: "#d6336c", pin: "#d6336c" },
};

const $ = (selector) => document.querySelector(selector);
const resultsBody = $("#results-body");
const form = $("#passport-form");

// Everything from Qloo or the AI is inserted as text, never as raw HTML.
const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = {
  search: null,   // what was searched: { city, favourites, people }
  cache: {},      // dial -> result from the server
  resolved: null, // favourites Qloo matched, reused when the dial changes
  busy: false,
  requestId: 0,   // lets us ignore answers to an out-of-date request
  map: null,
};

// ---------------------------------------------------------------- form

function addPersonRow(name = "", favourites = "") {
  const list = $("#people-list");
  const row = document.createElement("div");
  row.className = "person-row";
  row.innerHTML = `
    <input type="text" class="person-name" placeholder="Name" maxlength="30" aria-label="Person's name" value="${esc(name)}">
    <input type="text" class="person-favs" placeholder="Their favourites" maxlength="300" aria-label="Their favourites" value="${esc(favourites)}">
    <button type="button" aria-label="Remove this person">&times;</button>`;
  row.querySelector("button").addEventListener("click", () => {
    row.remove();
    updateAddButton();
  });
  list.appendChild(row);
  updateAddButton();
}

function updateAddButton() {
  const count = document.querySelectorAll(".person-row").length;
  $("#add-person").hidden = count >= 4;
  document.querySelectorAll(".person-row button").forEach((b) => (b.hidden = count <= 2));
}

function currentMode() {
  return form.elements.mode.value;
}

function selectedDial() {
  return form.elements.dial.value;
}

function showFormError(message) {
  const box = $("#form-error");
  box.textContent = message || "";
  box.hidden = !message;
}

function setBusy(busy) {
  state.busy = busy;
  $("#submit-btn").disabled = busy;
  $("#dial-group").setAttribute("aria-busy", String(busy));
  form.elements.dial.forEach((radio) => (radio.disabled = busy));
}

function readForm() {
  const city = form.elements.city.value.trim();
  if (city.length < 2) return { error: "Enter a city, for example Tokyo." };

  if (currentMode() === "group") {
    const people = [...document.querySelectorAll(".person-row")]
      .map((row) => ({
        name: row.querySelector(".person-name").value.trim(),
        favourites: row.querySelector(".person-favs").value.trim(),
      }))
      .filter((p) => p.name || p.favourites);
    if (people.length < 2 || people.some((p) => !p.name || p.favourites.length < 2)) {
      return { error: "Add a name and at least one favourite for each of at least two people." };
    }
    return { search: { city, favourites: "", people } };
  }

  const favourites = form.elements.favourites.value.trim();
  if (favourites.length < 2) return { error: "Tell me at least one thing you love, for example a film or an artist." };
  return { search: { city, favourites, people: null } };
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.busy) return;
  const { search, error } = readForm();
  showFormError(error);
  if (error) return;
  // A new search starts fresh: forget the old results and matched favourites.
  state.search = search;
  state.cache = {};
  state.resolved = null;
  showDial(selectedDial());
});

form.elements.dial.forEach((radio) =>
  radio.addEventListener("change", () => {
    if (state.search && !state.busy) showDial(selectedDial());
  })
);

form.elements.mode.forEach((radio) =>
  radio.addEventListener("change", () => {
    const group = currentMode() === "group";
    $("#solo-fields").hidden = group;
    $("#group-fields").hidden = !group;
    if (group && !document.querySelector(".person-row")) {
      addPersonRow();
      addPersonRow();
    }
  })
);

$("#add-person").addEventListener("click", () => addPersonRow());

$("#example-btn").addEventListener("click", () => {
  form.elements.mode.value = "solo";
  form.elements.mode[0].dispatchEvent(new Event("change"));
  form.elements.city.value = "Tokyo";
  form.elements.favourites.value = "Interstellar, A.R. Rahman";
  showFormError("");
  form.elements.favourites.focus();
});

// ---------------------------------------------------------------- loading data

async function showDial(dial) {
  if (state.cache[dial]) {
    render(dial);
    return;
  }
  const myRequest = ++state.requestId;
  setBusy(true);
  renderLoading(dial);
  // The free server sleeps when idle; say so if the wait is long.
  const slowTimer = setTimeout(() => {
    const slow = $("#slow-note");
    if (slow) slow.hidden = false;
  }, 8000);

  try {
    const body = {
      city: state.search.city,
      dial,
      favourites: state.search.favourites,
      people: state.search.people,
      resolved: state.resolved,
    };
    const controller = new AbortController();
    const abortTimer = setTimeout(() => controller.abort(), 120000);
    const response = await fetch("/api/passport", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    clearTimeout(abortTimer);
    let data = null;
    try {
      data = await response.json();
    } catch (_) {
      /* not JSON: handled below */
    }
    if (myRequest !== state.requestId) return; // a newer search replaced this one
    if (!response.ok || !data || data.error) {
      renderError((data && data.error) || "Something went wrong on our side. Please try again in a moment.", dial);
      return;
    }
    state.cache[dial] = data;
    if (!state.resolved && data.favourites.length) {
      state.resolved = data.favourites.map((f) => ({
        entity_id: f.entity_id, name: f.name, type: f.type || null, person: f.person || null,
      }));
    }
    render(dial);
  } catch (err) {
    if (myRequest !== state.requestId) return;
    renderError(
      err.name === "AbortError"
        ? "This is taking too long. The server may be waking up, so please try again."
        : "Could not reach the server. Check your connection and try again.",
      dial
    );
  } finally {
    clearTimeout(slowTimer);
    if (myRequest === state.requestId) setBusy(false);
  }
}

// ---------------------------------------------------------------- rendering

function stampSVG(city, dial) {
  // Repeat the phrase so the words run all the way around the ring.
  let text = `${city} • ${DIALS[dial].label} • `.toUpperCase();
  while (text.length < 26) text += text;
  const id = "stamp-path";
  return `
    <svg class="stamp land" viewBox="0 0 120 120" role="img" aria-label="${esc(DIALS[dial].label)} stamp for ${esc(city)}">
      <circle cx="60" cy="60" r="56" fill="none" stroke="currentColor" stroke-width="3"/>
      <circle cx="60" cy="60" r="39" fill="none" stroke="currentColor" stroke-width="1.5"/>
      <defs><path id="${id}" d="M60,60 m-47,0 a47,47 0 1,1 94,0 a47,47 0 1,1 -94,0"/></defs>
      <text font-family="Bricolage Grotesque, sans-serif" font-weight="700" font-size="11" letter-spacing="1.6" fill="currentColor">
        <textPath href="#${id}" startOffset="0" textLength="288" lengthAdjust="spacing">${esc(text.slice(0, 30))}</textPath>
      </text>
      <text x="60" y="66" text-anchor="middle" font-family="Bricolage Grotesque, sans-serif" font-weight="800" font-size="17" fill="currentColor">${esc(DIALS[dial].label)}</text>
    </svg>`;
}

function renderLoading(dial) {
  resultsBody.innerHTML = `
    <div class="loading" style="--dial:${DIALS[dial].color}">
      <div class="spinner"></div>
      <h2>Finding ${esc(DIALS[dial].label)} places in ${esc(state.search.city)}</h2>
      <p>Matching your favourites in Qloo and looking for places that fit. This usually takes 10 to 20 seconds.</p>
      <p id="slow-note" class="notice" hidden>Still working. The free server may be waking up, which can take up to a minute.</p>
    </div>`;
}

function renderError(message, dial) {
  resultsBody.innerHTML = `
    <div class="message error" role="alert">
      <h2>That didn't work</h2>
      <p>${esc(message)}</p>
      <button type="button" id="retry-btn" class="retry">Try again</button>
    </div>`;
  $("#retry-btn").addEventListener("click", () => {
    if (!state.busy) showDial(dial);
  });
}

// Group the match shares by person for a Group Passport, or by favourite for a solo one.
function fitRows(fits) {
  if (fits.some((f) => f.person)) {
    const byPerson = new Map();
    fits.forEach((f) => byPerson.set(f.person || "Shared", (byPerson.get(f.person || "Shared") || 0) + f.share));
    return [...byPerson].map(([name, share]) => ({ name, share }));
  }
  return fits.map((f) => ({ name: f.name, share: f.share }));
}

function fitsHTML(fits) {
  if (!fits || !fits.length) return `<p class="no-fits">Qloo did not give a breakdown of which favourites matched this one.</p>`;
  const rows = fitRows(fits)
    .map(
      (r) => `<li class="fit"><span class="fit-name" title="${esc(r.name)}">${esc(r.name)}</span>
        <span class="fit-bar"><i style="width:${Math.round(r.share * 100)}%"></i></span>
        <span class="fit-pct">${Math.round(r.share * 100)}%</span></li>`
    )
    .join("");
  return `<ul class="fits" aria-label="How much each favourite contributed to this match">${rows}</ul>`;
}

function cardHTML(item, dial, isPlace) {
  const text = item.note || (item.description ? item.description.slice(0, 160) : "Qloo has little other detail on this one.");
  const chips = [];
  if (item.affinity != null) chips.push(`Taste match ${Math.round(item.affinity * 100)}%`);
  if (item.popularity != null) chips.push(`Popularity ${Math.round(item.popularity * 100)}/100`);
  // A letter tile always sits underneath; the photo only covers it if it loads.
  // (Qloo's image server often returns an error for place photos.)
  const thumb = `<div class="thumb-wrap">
      <div class="thumb" aria-hidden="true">${esc(Array.from(item.name)[0] || "?")}</div>
      ${item.image ? `<img class="thumb-img" src="${esc(item.image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}
    </div>`;
  const clickable = isPlace && item.lat != null && item.lon != null;
  return `
    <article class="place${clickable ? " clickable" : ""}" data-id="${esc(item.entity_id)}" style="--dial:${DIALS[dial].color}">
      ${thumb}
      <div>
        <h4>${esc(item.name)}</h4>
        ${isPlace && item.address ? `<p class="addr">${esc(item.address)}</p>` : ""}
        <p class="note">${esc(text)}</p>
        ${fitsHTML(item.fits)}
        <ul class="chips">${chips.map((c) => `<li class="chip">${esc(c)}</li>`).join("")}</ul>
      </div>
    </article>`;
}

function render(dial) {
  const data = state.cache[dial];
  const { city } = state.search;
  const who = state.search.people
    ? state.search.people.map((p) => `${p.name}: ${p.favourites}`).join("; ")
    : (data.favourites.map((f) => f.name).join(", ") || state.search.favourites);

  let html = `
    <div class="results-head" style="--dial:${DIALS[dial].color}">
      ${stampSVG(city, dial)}
      <div>
        <h2>${esc(DIALS[dial].label)} picks in ${esc(city)}</h2>
        <p>Based on ${esc(who)}</p>
      </div>
    </div>`;

  if (data.message) {
    html += `<div class="message"><p>${esc(data.message)}</p></div>`;
  }
  if (data.fallback) {
    html += `<p class="notice">The AI notes were not available this time, so these are Qloo's own top matches with Qloo's descriptions.</p>`;
  }

  const hasPins = data.places.some((p) => p.lat != null && p.lon != null);
  if (hasPins) {
    html += `<div id="map" role="img" aria-label="Map of the suggested places"></div>
      <p class="map-legend" id="map-legend"></p>`;
  }
  if (data.places.length) {
    html += `<h3 class="section-title">Places</h3>` + data.places.map((p) => cardHTML(p, dial, true)).join("");
  }
  if (data.culture.length) {
    html += `<h3 class="section-title">Culture Qloo ties to ${esc(city)}</h3>
      <p class="section-note">Qloo ranks these higher for ${esc(city)} and your taste. They are not necessarily from ${esc(city)}.</p>
      <div class="culture-grid">${data.culture.map((c) => cardHTML(c, dial, false)).join("")}</div>`;
  }
  resultsBody.innerHTML = html;

  if (hasPins) drawMap(dial);
  wireCards();
  if (window.matchMedia("(max-width: 1023px)").matches) {
    $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// ---------------------------------------------------------------- map

const markers = {}; // entity_id -> Leaflet marker, for the cards to find

function drawMap(activeDial) {
  if (typeof L === "undefined") {
    $("#map").outerHTML = `<p class="notice">The map could not load, but the places are listed below.</p>`;
    return;
  }
  if (state.map) state.map.remove();
  Object.keys(markers).forEach((k) => delete markers[k]);
  const map = L.map("map", { scrollWheelZoom: false });
  state.map = map;
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(map);

  // Show pins for every dial setting loaded so far; the active one stands out.
  const activePoints = [];
  const loaded = [];
  Object.entries(state.cache).forEach(([dial, data]) => {
    const isActive = dial === activeDial;
    let count = 0;
    data.places.forEach((p) => {
      if (p.lat == null || p.lon == null) return;
      count++;
      const marker = L.circleMarker([p.lat, p.lon], {
        radius: isActive ? 9 : 6,
        color: "#ffffff",
        weight: 2,
        fillColor: DIALS[dial].pin,
        fillOpacity: isActive ? 0.95 : 0.4,
      }).addTo(map);
      marker.bindTooltip(p.name);
      if (isActive) {
        activePoints.push([p.lat, p.lon]);
        markers[p.entity_id] = marker;
        marker.on("click", () => focusCard(p.entity_id));
      }
    });
    if (count) loaded.push(dial);
  });

  if (activePoints.length) map.fitBounds(activePoints, { padding: [30, 30], maxZoom: 15 });
  else map.setView([0, 0], 2);

  $("#map-legend").innerHTML = loaded
    .map((d) => `<span><span class="legend-dot" style="background:${DIALS[d].pin}"></span>${DIALS[d].label}${d === activeDial ? " (showing below)" : ""}</span>`)
    .join("");
}

function focusCard(id) {
  const card = [...document.querySelectorAll(".place")].find((el) => el.dataset.id === id);
  if (!card) return;
  document.querySelectorAll(".place.highlight").forEach((el) => el.classList.remove("highlight"));
  card.classList.add("highlight");
  card.scrollIntoView({ behavior: "smooth", block: "center" });
}

function wireCards() {
  document.querySelectorAll(".place.clickable").forEach((card) => {
    card.addEventListener("click", () => {
      const marker = markers[card.dataset.id];
      if (!marker || !state.map) return;
      document.querySelectorAll(".place.highlight").forEach((el) => el.classList.remove("highlight"));
      card.classList.add("highlight");
      state.map.flyTo(marker.getLatLng(), 15);
      marker.openTooltip();
      $("#map").scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
}

// If a picture fails to load, hide it so the letter tile underneath shows.
// (Error events do not bubble, so listen in the capture phase. Set up once.)
resultsBody.addEventListener("error", (event) => {
  if (event.target.tagName === "IMG") event.target.style.display = "none";
}, true);

// ---------------------------------------------------------------- start

resultsBody.innerHTML = `
  <div class="empty">
    <h2>Where to next?</h2>
    <p>Enter a city and a few things you love. Taste Passport asks Qloo for places and local culture that match your taste,
    then you can slide from familiar to adventurous.</p>
  </div>`;
