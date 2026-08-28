// ============================================================
// MAP SETTINGS
// ============================================================

const DEFAULT_CENTER = [23.3441, 85.3096];

// Change this value to increase/decrease the analysis area.
const DEFAULT_RADIUS_KM = 100;


// ============================================================
// INITIALIZE MAP
// ============================================================

const map = L.map("map", {
  zoomControl: true
}).setView(DEFAULT_CENTER, 8);

L.tileLayer(
  "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
  {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors"
  }
).addTo(map);


// ============================================================
// MAP STATE
// ============================================================

const hotspotLayer = L.layerGroup().addTo(map);

let selectionMarker = null;
let selectionCircle = null;

let selectedCenter = {
  lat: DEFAULT_CENTER[0],
  lon: DEFAULT_CENTER[1]
};


// ============================================================
// DOM ELEMENTS
// ============================================================

const $ = id => document.getElementById(id);

const details = $("hotspotDetails");
const emptyState = $("emptyState");
const statusEl = $("status");
const selectionBadge = $("selectionBadge");
const searchResults = $("searchResults");


// ============================================================
// SECURITY / HTML ESCAPE
// ============================================================

function esc(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    c => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    }[c])
  );
}


// ============================================================
// RISK COLORS
// ============================================================

function markerColor(level) {
  return {
    HIGH: "#ef4444",
    MEDIUM: "#f59e0b",
    LOW: "#16a34a"
  }[level] || "#16a34a";
}


// ============================================================
// MAP ICONS
// ============================================================

function hotspotIcon(level) {

  return L.divIcon({
    className: "hotspot-icon",
    html: `
      <div
        class="hotspot-dot"
        style="background:${markerColor(level)}"
      >🔥</div>
    `,
    iconSize: [20, 20],
    iconAnchor: [10, 10]
  });

}


// ============================================================
// SHOW HOTSPOT DETAILS
// ============================================================

function showDetails(h) {

  emptyState.classList.add("hidden");
  details.classList.remove("hidden");

  const score = Number(h.risk_score || 0);
  const level = h.risk_level || "LOW";

  details.innerHTML = `
    <div class="detail-content">

      <div class="detail-hero">

        <div class="hero-row">

          <div>
            <h2 class="hero-title">
              🔥 Thermal hotspot
            </h2>

            <p class="hero-sub">
              ${esc(h.acq_date)}
              •
              ${esc(h.acq_time)}
              UTC
            </p>
          </div>

          <span class="risk-chip risk-${esc(level)}">
            ${esc(level)} RISK
          </span>

        </div>

        <div class="score-row">

          <div
            class="score-ring"
            style="--score:${score}%"
            data-score="${score}"
          ></div>

          <div class="score-copy">
            <span>Prototype risk score</span>
            <b>${esc(h.classification)}</b>
          </div>

        </div>

      </div>


      <section class="detail-section">

        <h3 class="section-title">
          Satellite signal
        </h3>

        <div class="data-grid">

          <div class="data-item">
            <span>FRP</span>
            <b>${esc(h.frp)}</b>
          </div>

          <div class="data-item">
            <span>Confidence</span>
            <b>${esc(h.confidence)}</b>
          </div>

          <div class="data-item">
            <span>Brightness T4</span>
            <b>${esc(h.bright_ti4)}</b>
          </div>

          <div class="data-item">
            <span>Brightness T5</span>
            <b>${esc(h.bright_ti5)}</b>
          </div>

          <div class="data-item">
            <span>Satellite</span>
            <b>${esc(h.satellite)}</b>
          </div>

          <div class="data-item">
            <span>Day / Night</span>
            <b>${esc(h.daynight)}</b>
          </div>

        </div>

      </section>


      <section class="detail-section">

        <h3 class="section-title">
          Location
        </h3>

        <div class="data-grid">

          <div class="data-item">
            <span>Latitude</span>
            <b>${Number(h.latitude).toFixed(5)}</b>
          </div>

          <div class="data-item">
            <span>Longitude</span>
            <b>${Number(h.longitude).toFixed(5)}</b>
          </div>

          <div class="data-item">
            <span>Scan</span>
            <b>${esc(h.scan)}</b>
          </div>

          <div class="data-item">
            <span>Track</span>
            <b>${esc(h.track)}</b>
          </div>

        </div>

      </section>


      <section class="detail-section">

        <h3 class="section-title">
          Interpretation
        </h3>

        <p class="interpretation">
          FIRMS has detected a thermal anomaly at
          this coordinate. This prototype combines
          thermal signal strength (FRP), satellite
          confidence and brightness temperature to
          calculate a relative risk score. It does
          not prove the source type and is not an
          official NASA fire-risk classification.
        </p>

      </section>

    </div>
  `;
}


// ============================================================
// LOCATION SELECTION
// ============================================================

function setSelection(lat, lon, label = null) {

  selectedCenter = { lat, lon };

  selectionMarker?.remove();
  selectionCircle?.remove();

  selectionMarker = L.marker(
    [lat, lon],
    {
      icon: L.divIcon({
        className: "context-icon",
        html: "📍",
        iconSize: [28, 28],
        iconAnchor: [14, 28]
      })
    }
  ).addTo(map);

  selectionCircle = L.circle(
    [lat, lon],
    {
      radius: DEFAULT_RADIUS_KM * 1000,
      color: "#2563eb",
      weight: 1.5,
      fillOpacity: 0.035
    }
  ).addTo(map);

  selectionBadge.textContent =
    `📍 ${
      label ||
      `${lat.toFixed(4)}, ${lon.toFixed(4)}`
    } • ${DEFAULT_RADIUS_KM} km`;

  selectionBadge.classList.remove("hidden");
}


// ============================================================
// CREATE FIRMS BOUNDING BOX
// ============================================================

function bboxForCenter(
  lat,
  lon,
  radiusKm = DEFAULT_RADIUS_KM
) {

  const latDelta = radiusKm / 111;

  const lonDelta =
    radiusKm /
    (111 * Math.cos(lat * Math.PI / 180));

  return [
    lon - lonDelta,
    lat - latDelta,
    lon + lonDelta,
    lat + latDelta
  ].join(",");
}


// ============================================================
// LOAD HOTSPOTS
// ============================================================

async function loadHotspots() {

  statusEl.textContent =
    "Loading NASA FIRMS data…";

  hotspotLayer.clearLayers();

  const days = $("days").value;

  const bbox = bboxForCenter(
    selectedCenter.lat,
    selectedCenter.lon
  );

  try {

    const response = await fetch(
      `/api/hotspots?days=${encodeURIComponent(days)}&bbox=${encodeURIComponent(bbox)}`
    );

    const data = await response.json();

    if (!data.ok) {
      throw new Error(data.error);
    }

    const counts = {
      HIGH: 0,
      MEDIUM: 0,
      LOW: 0
    };


    // --------------------------------------------------------
    // CREATE HOTSPOT MARKERS
    // --------------------------------------------------------

    data.hotspots.forEach(h => {

      counts[h.risk_level] =
        (counts[h.risk_level] || 0) + 1;

      const marker = L.marker(
        [h.latitude, h.longitude],
        {
          icon: hotspotIcon(h.risk_level)
        }
      );

      marker.bindTooltip(
        `${h.risk_level} • FRP ${h.frp}`,
        {
          direction: "top",
          opacity: 0.92
        }
      );

      marker.on("click", () => {

        map.flyTo(
          [h.latitude, h.longitude],
          Math.max(map.getZoom(), 10),
          { duration: 0.55 }
        );

        showDetails(h);
      });

      marker.addTo(hotspotLayer);

    });


    // --------------------------------------------------------
    // UPDATE STATISTICS
    // --------------------------------------------------------

    $("total").textContent = data.count;
    $("high").textContent = counts.HIGH;
    $("medium").textContent = counts.MEDIUM;
    $("low").textContent = counts.LOW;


    // --------------------------------------------------------
    // UPDATE STATUS
    // --------------------------------------------------------

    statusEl.textContent =
      `Loaded ${data.count} hotspot(s) • ${days}-day window`;


    // --------------------------------------------------------
    // SHOW FIRST RESULT
    // --------------------------------------------------------

    if (data.count) {

      showDetails(data.hotspots[0]);

    } else {

      emptyState.classList.remove("hidden");
      details.classList.add("hidden");

      statusEl.textContent =
        `No hotspots found in this area for ${days} day(s).`;

    }

  } catch (err) {

    statusEl.textContent =
      "FIRMS request failed";

    emptyState.classList.add("hidden");
    details.classList.remove("hidden");

    details.innerHTML = `
      <div class="detail-content">
        <div class="detail-section">

          <h3 class="section-title">
            Unable to load data
          </h3>

          <p class="interpretation">
            ${esc(err.message)}
          </p>

          <p class="interpretation">
            Check your FIRMS MAP_KEY,
            internet connection and
            selected area.
          </p>

        </div>
      </div>
    `;
  }
}


// ============================================================
// SEARCH PLACE
// ============================================================

async function searchPlace() {

  const query = $("placeSearch").value.trim();

  if (!query) return;

  statusEl.textContent =
    "Searching OpenStreetMap…";

  searchResults.classList.remove("hidden");

  searchResults.innerHTML =
    `<div class="search-result">Searching…</div>`;

  try {

    const response = await fetch(
      `/api/search?q=${encodeURIComponent(query)}`
    );

    const data = await response.json();

    if (!data.ok) {
      throw new Error(data.error);
    }

    if (!data.results.length) {

      searchResults.innerHTML =
        `<div class="search-result">No places found.</div>`;

      return;
    }


    // --------------------------------------------------------
    // DISPLAY RESULTS
    // --------------------------------------------------------

    searchResults.innerHTML =
      data.results.map((r, i) => `
        <button
          class="search-result"
          data-index="${i}"
        >
          <strong>
            ${esc(
              r.display_name
                .split(",")
                .slice(0, 2)
                .join(",")
            )}
          </strong>

          <small>
            ${esc(r.display_name)}
          </small>
        </button>
      `).join("");


    // --------------------------------------------------------
    // RESULT SELECTION
    // --------------------------------------------------------

    searchResults
      .querySelectorAll(".search-result")
      .forEach(button => {

        button.addEventListener(
          "click",
          () => {

            const result =
              data.results[
                Number(button.dataset.index)
              ];

            const lat = Number(result.lat);
            const lon = Number(result.lon);

            const label =
              result.display_name
                .split(",")
                .slice(0, 2)
                .join(",");

            setSelection(
              lat,
              lon,
              label
            );

            map.flyTo(
              [lat, lon],
              10,
              { duration: 0.8 }
            );

            searchResults.classList.add(
              "hidden"
            );

            statusEl.textContent =
              "Location selected. Click Analyze area.";
          }
        );

      });

  } catch (err) {

    searchResults.innerHTML =
      `<div class="search-result">${esc(err.message)}</div>`;
  }
}


// ============================================================
// MAP EVENTS
// ============================================================

map.on("click", e => {

  setSelection(
    e.latlng.lat,
    e.latlng.lng
  );

  statusEl.textContent =
    "Map point selected. Click Analyze area.";
});


map.on("locationfound", e => {

  setSelection(
    e.latlng.lat,
    e.latlng.lng,
    "Your map location"
  );

  statusEl.textContent =
    "Your location selected. Click Analyze area.";
});


map.on("locationerror", e => {

  console.warn(
    "Location error:",
    e.message
  );

  statusEl.textContent =
    "Unable to access your location.";
});


// ============================================================
// BUTTON EVENTS
// ============================================================

$("searchBtn").addEventListener(
  "click",
  searchPlace
);

$("placeSearch").addEventListener(
  "keydown",
  e => {
    if (e.key === "Enter") {
      searchPlace();
    }
  }
);

$("loadBtn").addEventListener(
  "click",
  loadHotspots
);

$("locateBtn").addEventListener(
  "click",
  () => {
    map.locate({
      setView: true,
      maxZoom: 10
    });
  }
);

$("closeDetails").addEventListener(
  "click",
  () => {
    details.classList.add("hidden");
    emptyState.classList.remove("hidden");
  }
);


// ============================================================
// INITIAL LOAD
// ============================================================

loadHotspots();