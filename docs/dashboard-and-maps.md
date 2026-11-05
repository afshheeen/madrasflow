# Marina Ops: run, maps, explanations and deployment

## Run the connected dashboard

From the project directory, activate the Python environment used for the model pipeline:

```powershell
python scripts/build_dashboard_data.py
python run.py serve --port 8765
```

Open http://127.0.0.1:8765/ for operations and http://127.0.0.1:8765/driver.html for reporting. The dashboard consumes `/api/snapshot`, not handwritten passenger counts. The snapshot is exported from the model-derived profiles. After daily ingestion and profile generation, rerun the export; the API reads the updated snapshot without needing a server restart.

For a phone on the same trusted network, run with `--host 0.0.0.0`, find the computer's LAN IPv4 address using `ipconfig`, and open `http://LAN-IP:8765/driver.html`. Windows may require an incoming firewall allowance. The prototype has no user authentication; do not expose this API directly to the public internet. Do not put 127.0.0.1 into a phone: that refers to the phone itself.

## Hosted version versus local API

The hosted Site contains a real forecast snapshot and runs filters, map styling, explanations and service arithmetic in the browser. Hosted snapshot incident reports are saved **only in that browser** and are explicitly labeled that way. They do not synchronize across a driver's phone and a manager's computer.

The local Python deployment provides shared SQLite reports, status changes, server-verified scenarios and a grounded explanation endpoint. For cross-device public operation, deploy that API behind authenticated HTTPS and connect the frontend to it. A static hosted Site cannot run the Python/XGBoost process or read a laptop's local data automatically. Do not describe the current hosted snapshot as a live shared operations deployment.

## No-key map setup: Leaflet and OpenStreetMap

This is the default already implemented. No OpenStreetMap API account is required to display the basemap. Leaflet is pinned to stable **1.9.4**, with one GeoJSON line per geographically matched stage interval.

1. Keep the visible OpenStreetMap attribution.
2. Use HTTPS standard tiles: `https://tile.openstreetmap.org/{z}/{x}/{y}.png`.
3. Keep normal browser Referer and caching behavior. No offline city downloads, tile prefetching or forced cache bypass.
4. For heavier production traffic, select a suitable tile provider or self-host; public OSM tiles are best-effort shared infrastructure.
5. The supplied GIS coordinates are WGS84. GeoJSON coordinate order is longitude, latitude; Leaflet's direct latLng methods use latitude, longitude.

The map does not infer ETM stages. Current automatic matches require an exact normalized stop name, proximity within 400 metres of the route, matching route endpoints and forward stage ordering. Matches remain unreviewed, and roads with no stage match remain grey. A colored stage strip/list is available for all estimated stage intervals; it is explicitly schematic.

Map colors are a function of the selected day/hour forecast and the user's assumed trips/hour: <=40 free; >40–<50 light; 50–<60 medium; 60–<70 crowded; >=70 very crowded. These are planning load proxies because section crossing times and a verified timetable are unavailable. Changing the service assumption changes the scenario, not the underlying demand estimate.

Official references: [Leaflet 1.9.4](https://leafletjs.com/reference-1.9.4.html), [GeoJSON styling](https://leafletjs.com/reference-1.9.4.html#geojson), [OSM tile policy](https://operations.osmfoundation.org/policies/tiles/).

## Google Maps alternative

No Google key is needed for the existing implementation. If you choose Google:

1. Create/select a Google Cloud project.
2. Link billing for standard production use and enable **Maps JavaScript API**. Google's setup page also describes a prototype-only Demo Key option; check its current limits before relying on it.
3. Create a key under Credentials.
4. Restrict applications to **Websites**, listing your real origins, for example `http://localhost:8765/*`, `http://127.0.0.1:8765/*` and your deployed HTTPS origin.
5. Restrict the key to Maps JavaScript API, unless another API is deliberately enabled.
6. Configure usage monitoring/quotas. A browser key is visible to visitors; restrictions are essential. Keep server-side keys out of frontend source and Git.
7. Draw each mapped section as a `google.maps.Polyline`; set its `strokeColor` from the same load-band function. No Routes API is needed merely to display supplied route geometry. Feasible navigation/rerouting is a separate capability.

Official references: [Google setup](https://developers.google.com/maps/documentation/javascript/get-api-key), [API security](https://developers.google.com/maps/api-security-best-practices), [Polylines](https://developers.google.com/maps/documentation/javascript/shapes).

## Explainable AI without another paid API

The selected model is currently a historical profile. Its explanation can therefore state the day/hour reference, predicted section flow, assumed trips, arithmetic, missing-destination share and source date directly. `/api/explain` builds that response from the selected route's data. The hosted version uses the same structured facts locally. No LLM key is required.

The explainer does not diagnose an accident, weather effect or event without evidence. If a generative assistant is added later, give it these structured facts and require it to cite them; it must not invent forecast causes or intervention benefits. XGBoost SHAP values would explain model associations if that model were selected. They would not prove an intervention causes a particular outcome.

## API contract

- `GET /api/health`: connectivity mode and data cutoff.
- `GET /api/snapshot`: real forecast snapshot, route geometry, coverage and error evidence.
- `GET /api/incidents`: shared local-server reports.
- `POST /api/incidents`: route, type, description and optional stage interval.
- `POST /api/incidents/status`: acknowledge or resolve a report.
- `POST /api/scenario`: route_id, day_type, hour, integer trips, optional target_load.
- `POST /api/explain`: the same selected context plus an optional question.

Cross-origin writes are rejected. Serving the UI and API from the same origin avoids exposing a permissive CORS endpoint. Before a public shared deployment, add authentication, roles, HTTPS, operational constraints and an explicit ETM delivery schedule.
