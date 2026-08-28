// ============================================================
// THERMAL SOURCE INTELLIGENCE
// FIRMS + RANDOM FOREST AI + AREA TYPE
// ============================================================


// ============================================================
// MAP SETTINGS
// ============================================================

const DEFAULT_CENTER = [23.3441, 85.3096];

// Analysis radius in kilometres
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
  }[String(level).toUpperCase()] || "#16a34a";

}


// ============================================================
// RISK CSS CLASS
// ============================================================

function riskClass(level) {

  const value =
    String(level || "")
      .toUpperCase();

  if (value === "HIGH") {
    return "risk-HIGH";
  }

  if (value === "MEDIUM") {
    return "risk-MEDIUM";
  }

  if (value === "LOW") {
    return "risk-LOW";
  }

  return "risk-UNKNOWN";

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
// AI PROBABILITY BAR
// ============================================================

function probabilityBar(label, value) {

  let number = Number(value);

  if (!Number.isFinite(number)) {
    number = 0;
  }

  number = Math.max(0, Math.min(100, number));

  return `

    <div class="ai-probability-row">

      <div class="ai-probability-head">

        <span>${esc(label)}</span>

        <strong>
          ${number.toFixed(1)}%
        </strong>

      </div>

      <div class="ai-probability-track">

        <div
          class="ai-probability-fill ${riskClass(label)}"
          style="width:${number}%"
        ></div>

      </div>

    </div>

  `;

}


// ============================================================
// AREA TYPE
// ============================================================

async function getAreaType(lat, lon) {

  try {

    const response = await fetch(
      `/api/area-type?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`
    );

    if (!response.ok) {
      throw new Error("Area type request failed");
    }

    const data = await response.json();

    if (
      data.ok &&
      data.area_type
    ) {

      return data.area_type;

    }

  } catch (error) {

    console.warn(
      "Area type unavailable:",
      error
    );

  }

  return {

    name: "Unknown / Unclassified",

    icon: "❓",

    description:
      "Land-use information is not available for this hotspot."

  };

}


// ============================================================
// AI EXPLANATION
// ============================================================

function aiExplanation(
  level,
  confidence,
  areaName
) {

  const upper =
    String(level || "")
      .toUpperCase();

  let message;

  if (upper === "HIGH") {

    message =
      "The Random Forest model classifies this thermal " +
      "observation as HIGH risk.";

  } else if (upper === "MEDIUM") {

    message =
      "The Random Forest model classifies this thermal " +
      "observation as MEDIUM risk.";

  } else if (upper === "LOW") {

    message =
      "The Random Forest model classifies this thermal " +
      "observation as LOW risk.";

  } else {

    message =
      "The Random Forest prediction is unavailable.";

  }

  if (areaName) {

    message +=
      ` The surrounding area is classified as ${areaName}.`;

  }

  if (
    confidence !== null &&
    confidence !== undefined &&
    Number.isFinite(Number(confidence))
  ) {

    message +=
      ` Model confidence: ${Number(confidence).toFixed(1)}%.`;

  }

  return message;

}


// ============================================================
// SHOW HOTSPOT DETAILS
// ============================================================

async function showDetails(h) {

  emptyState.classList.add("hidden");

  details.classList.remove("hidden");


  // ----------------------------------------------------------
  // EXISTING PROTOTYPE RESULT
  // ----------------------------------------------------------

  const score =
    Number(h.risk_score || 0);

  const prototypeLevel =
    h.risk_level || "LOW";


  // ----------------------------------------------------------
  // AI RESULT
  // ----------------------------------------------------------

  const aiLevel =
    h.ml_risk_level ||
    prototypeLevel ||
    "UNKNOWN";


  let aiConfidence = null;

  if (
    h.ml_confidence !== null &&
    h.ml_confidence !== undefined &&
    h.ml_confidence !== ""
  ) {

    aiConfidence =
      Number(h.ml_confidence);

  }


  const probabilities =
    h.ml_probabilities || {};


  // ----------------------------------------------------------
  // GET AREA TYPE
  // ----------------------------------------------------------

  details.innerHTML = `

    <div class="detail-content">

      <div class="detail-section">

        <p class="interpretation">
          Loading AI and area information…
        </p>

      </div>

    </div>

  `;


  const areaType =
    await getAreaType(
      h.latitude,
      h.longitude
    );


  // ==========================================================
  // COMPLETE DETAILS PANEL
  // ==========================================================

  details.innerHTML = `

    <div class="detail-content">


      <!-- ====================================================
           HEADER
      ===================================================== -->

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


          <span
            class="
              risk-chip
              risk-${esc(aiLevel)}
            "
          >
            ${esc(aiLevel)} RISK
          </span>

        </div>


        <!-- ==================================================
             EXISTING PROTOTYPE SCORE
        =================================================== -->

        <div class="score-row">

          <div
            class="score-ring"
            style="--score:${score}%"
            data-score="${score}"
          ></div>


          <div class="score-copy">

            <span>
              Prototype risk score
            </span>

            <b>
              ${esc(h.classification)}
            </b>

          </div>

        </div>

      </div>


      <!-- ====================================================
           AI MODEL
      ===================================================== -->

      <section class="detail-section ai-section">

        <div class="ai-header">

          <div class="ai-title">

            <span class="ai-icon">
              🤖
            </span>

            <div>

              <h3 class="section-title">
                AI Fire Risk
              </h3>

              <small>
                Random Forest Classifier
              </small>

            </div>

          </div>


          <span
            class="
              ai-model-status
              ${h.ml_risk_level ? "available" : "unavailable"}
            "
          >

            ${
              h.ml_risk_level
                ? "AI ACTIVE"
                : "AI UNAVAILABLE"
            }

          </span>

        </div>


        <div class="ai-main-result">

          <div
            class="
              ai-risk-value
              ${riskClass(aiLevel)}
            "
          >

            ${esc(aiLevel)}

          </div>


          ${
            aiConfidence !== null &&
            Number.isFinite(aiConfidence)

            ?

            `

            <div class="ai-confidence-box">

              <span>
                AI Confidence
              </span>

              <strong>
                ${aiConfidence.toFixed(1)}%
              </strong>

            </div>

            `

            :

            `

            <div class="ai-confidence-box">

              <span>
                AI Confidence
              </span>

              <strong>
                —
              </strong>

            </div>

            `

          }

        </div>


        <!-- ==================================================
             AI PROBABILITIES
        =================================================== -->

        <div class="ai-probabilities">

          <div class="ai-probability-title">

            Prediction probability

          </div>


          ${probabilityBar(
            "HIGH",
            probabilities.HIGH || 0
          )}


          ${probabilityBar(
            "MEDIUM",
            probabilities.MEDIUM || 0
          )}


          ${probabilityBar(
            "LOW",
            probabilities.LOW || 0
          )}

        </div>


       

      </section>


      <!-- ====================================================
           AREA TYPE
      ===================================================== -->

      <section class="detail-section area-section">

        <h3 class="section-title">
          📍 Area Type
        </h3>


        <div class="area-type-card">

          <div class="area-type-icon">

            ${areaType.icon || "❓"}

          </div>


          <div class="area-type-content">

            <strong>

              ${esc(
                areaType.name ||
                "Unknown"
              )}

            </strong>

            <p>

              ${esc(
                areaType.description ||
                "Area classification unavailable."
              )}

            </p>

          </div>

        </div>

      </section>


      
      <!-- ====================================================
           LOCATION
      ===================================================== -->

      <section class="detail-section">

        <h3 class="section-title">
          Location
        </h3>


        <div class="data-grid">


          <div class="data-item">

            <span>
              Latitude
            </span>

            <b>

              ${Number(
                h.latitude
              ).toFixed(5)}

            </b>

          </div>


          <div class="data-item">

            <span>
              Longitude
            </span>

            <b>

              ${Number(
                h.longitude
              ).toFixed(5)}

            </b>

          </div>


          <div class="data-item">

            <span>
              Scan
            </span>

            <b>
              ${esc(h.scan)}
            </b>

          </div>


          <div class="data-item">

            <span>
              Track
            </span>

            <b>
              ${esc(h.track)}
            </b>

          </div>


        </div>

      </section>


    </div>

  `;

}


// ============================================================
// LOCATION SELECTION
// ============================================================

function setSelection(
  lat,
  lon,
  label = null
) {

  selectedCenter = {
    lat,
    lon
  };


  // Remove old selection marker

  if (selectionMarker) {
    selectionMarker.remove();
  }


  // Remove old circle

  if (selectionCircle) {
    selectionCircle.remove();
  }


  // ----------------------------------------------------------
  // SELECTED LOCATION MARKER
  // ----------------------------------------------------------

  selectionMarker = L.marker(
    [lat, lon],
    {

      icon: L.divIcon({

        className:
          "context-icon",

        html:
          "📍",

        iconSize:
          [28, 28],

        iconAnchor:
          [14, 28]

      })

    }
  ).addTo(map);


  // ----------------------------------------------------------
  // ORIGINAL CIRCULAR ANALYSIS AREA
  // ----------------------------------------------------------

  selectionCircle = L.circle(
    [lat, lon],
    {

      radius:
        DEFAULT_RADIUS_KM * 1000,

      color:
        "#2563eb",

      weight:
        1.5,

      fillOpacity:
        0.035

    }
  ).addTo(map);


  // ----------------------------------------------------------
  // BADGE
  // ----------------------------------------------------------

  selectionBadge.textContent =
    `📍 ${
      label ||
      `${lat.toFixed(4)}, ${lon.toFixed(4)}`
    } • ${DEFAULT_RADIUS_KM} km`;


  selectionBadge.classList.remove(
    "hidden"
  );

}


// ============================================================
// CREATE FIRMS BOUNDING BOX
// ============================================================

function bboxForCenter(
  lat,
  lon,
  radiusKm = DEFAULT_RADIUS_KM
) {

  const latDelta =
    radiusKm / 111;


  const lonDelta =
    radiusKm /
    (
      111 *
      Math.cos(
        lat * Math.PI / 180
      )
    );


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


  const days =
    $("days").value;


  const bbox =
    bboxForCenter(
      selectedCenter.lat,
      selectedCenter.lon
    );


  try {

    const response =
      await fetch(
        `/api/hotspots?days=${encodeURIComponent(days)}&bbox=${encodeURIComponent(bbox)}`
      );


    const data =
      await response.json();


    if (!data.ok) {

      throw new Error(
        data.error
      );

    }


    const counts = {

      HIGH: 0,

      MEDIUM: 0,

      LOW: 0

    };


    // ========================================================
    // CREATE HOTSPOT MARKERS
    // ========================================================

    data.hotspots.forEach(h => {


      // Use AI result for marker color
      // when available.

      const markerLevel =
        h.ml_risk_level ||
        h.risk_level ||
        "LOW";


      // Keep original prototype statistics.

      const prototypeLevel =
        h.risk_level ||
        "LOW";


      counts[prototypeLevel] =
        (counts[prototypeLevel] || 0) + 1;


      const marker =
        L.marker(

          [
            h.latitude,
            h.longitude
          ],

          {

            icon:
              hotspotIcon(
                markerLevel
              )

          }

        );


      // ------------------------------------------------------
      // TOOLTIP
      // ------------------------------------------------------

      marker.bindTooltip(

        `
          <strong>
            ${esc(markerLevel)} AI RISK
          </strong>

          <br>

          FRP:
          ${esc(h.frp)}

          ${
            h.ml_confidence !== null &&
            h.ml_confidence !== undefined

            ?

            `<br>
             AI:
             ${Number(h.ml_confidence).toFixed(1)}%`

            :

            ""
          }

        `,

        {

          direction:
            "top",

          opacity:
            0.92

        }

      );


      // ------------------------------------------------------
      // CLICK
      // ------------------------------------------------------

      marker.on(
        "click",
        () => {

          map.flyTo(

            [
              h.latitude,
              h.longitude
            ],

            Math.max(
              map.getZoom(),
              10
            ),

            {
              duration:
                0.55
            }

          );


          showDetails(h);

        }
      );


      marker.addTo(
        hotspotLayer
      );

    });


    // ========================================================
    // UPDATE STATISTICS
    // ========================================================

    $("total").textContent =
      data.count;


    $("high").textContent =
      counts.HIGH;


    $("medium").textContent =
      counts.MEDIUM;


    $("low").textContent =
      counts.LOW;


    // ========================================================
    // AI STATUS
    // ========================================================

    const aiAvailable =
      data.ml_model_available === true;


    // ========================================================
    // STATUS
    // ========================================================

    statusEl.textContent =
      `Loaded ${data.count} hotspot(s) • ${days}-day window` +
      (
        aiAvailable
          ? " • AI active"
          : " • AI model unavailable"
      );


    // ========================================================
    // FIRST RESULT
    // ========================================================

    if (data.count) {

      showDetails(
        data.hotspots[0]
      );

    } else {

      emptyState.classList.remove(
        "hidden"
      );

      details.classList.add(
        "hidden"
      );


      statusEl.textContent =
        `No hotspots found in this area for ${days} day(s).`;

    }


  } catch (err) {

    console.error(err);


    statusEl.textContent =
      "FIRMS request failed";


    emptyState.classList.add(
      "hidden"
    );


    details.classList.remove(
      "hidden"
    );


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

  const query =
    $("placeSearch")
      .value
      .trim();


  if (!query) {
    return;
  }


  statusEl.textContent =
    "Searching OpenStreetMap…";


  searchResults.classList.remove(
    "hidden"
  );


  searchResults.innerHTML =
    `<div class="search-result">
      Searching…
    </div>`;


  try {

    const response =
      await fetch(
        `/api/search?q=${encodeURIComponent(query)}`
      );


    const data =
      await response.json();


    if (!data.ok) {

      throw new Error(
        data.error
      );

    }


    if (!data.results.length) {

      searchResults.innerHTML =
        `
          <div class="search-result">
            No places found.
          </div>
        `;

      return;

    }


    // ========================================================
    // DISPLAY SEARCH RESULTS
    // ========================================================

    searchResults.innerHTML =

      data.results.map(
        (r, i) => `

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

              ${esc(
                r.display_name
              )}

            </small>

          </button>

        `
      ).join("");


    // ========================================================
    // SEARCH RESULT SELECTION
    // ========================================================

    searchResults
      .querySelectorAll(
        ".search-result"
      )
      .forEach(button => {

        button.addEventListener(
          "click",
          () => {


            const result =
              data.results[
                Number(
                  button.dataset.index
                )
              ];


            const lat =
              Number(result.lat);


            const lon =
              Number(result.lon);


            const label =
              result.display_name
                .split(",")
                .slice(0, 2)
                .join(",");


            // Set location + circle

            setSelection(
              lat,
              lon,
              label
            );


            // Move map

            map.flyTo(

              [lat, lon],

              10,

              {
                duration:
                  0.8
              }

            );


            // Hide results

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

      `
        <div class="search-result">

          ${esc(err.message)}

        </div>
      `;

  }

}


// ============================================================
// MAP EVENTS
// ============================================================

map.on(
  "click",
  e => {

    setSelection(

      e.latlng.lat,

      e.latlng.lng

    );


    statusEl.textContent =
      "Map point selected. Click Analyze area.";

  }
);


map.on(
  "locationfound",
  e => {

    setSelection(

      e.latlng.lat,

      e.latlng.lng,

      "Your map location"

    );


    statusEl.textContent =
      "Your location selected. Click Analyze area.";

  }
);


map.on(
  "locationerror",
  e => {

    console.warn(
      "Location error:",
      e.message
    );


    statusEl.textContent =
      "Unable to access your location.";

  }
);


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

      setView:
        true,

      maxZoom:
        10

    });

  }
);


$("closeDetails").addEventListener(
  "click",
  () => {

    details.classList.add(
      "hidden"
    );

    emptyState.classList.remove(
      "hidden"
    );

  }
);


// ============================================================
// INITIAL LOAD
// ============================================================

loadHotspots();