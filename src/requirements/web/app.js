const $ = (id) => document.getElementById(id);
const form = $('requirements-form');
const roles = ['inlet', 'outlet', 'heated'];
const colors = { inlet: 0x2188ee, outlet: 0x28a669, heated: 0xf38737, cad: 0xb9c8d3, cap: 0xa985dd };
let state, draft, dirty = false, busy = false, conflicted = false;
let activeRole = 'inspect', selectedId = null, viewerReady = false;
let THREE, renderer, scene, camera, controls, group, raycaster;
let meshes = new Map(), faceButtons = new Map(), faces = new Map();
let renderedFingerprint = null;

function message(text, success = false) {
  $('message').textContent = text;
  $('message').className = success ? 'success' : '';
  $('message').hidden = !text;
}
function numberValue(name) {
  const value = form.elements[name].value.trim();
  return value === '' ? null : Number(value);
}
function pressurePa(name) {
  const value = numberValue(name);
  return value === null ? null : Number((value * 100000).toPrecision(15));
}
function roleOf(id) {
  return roles.find((role) => draft.selections[role].includes(id)) || null;
}
function readForm() {
  const requirements = { ...draft.requirements };
  for (const key of ['title', 'solid_material', 'coolant_material', 'objective', 'other_thermal_boundaries', 'notes']) requirements[key] = form.elements[key].value;
  for (const key of ['inlet_temperature_K', 'maximum_surface_temperature_K']) requirements[key] = numberValue(key);
  requirements.temperature_limit_scope = 'heated_surfaces';
  requirements.units_confirmed = form.elements.units_confirmed.checked;
  requirements.mass_flow_bounds_kg_s = [numberValue('flow_min'), numberValue('flow_max')];
  const pressure = { mode: form.elements.pressure_mode.value, bounds_Pa: [pressurePa('pressure_min'), pressurePa('pressure_max')], reference_pressure_Pa: form.elements.pressure_mode.value === 'gauge' ? pressurePa('pressure_reference') : null };
  requirements.pressure_input = pressure;
  requirements.outlet_absolute_pressure_bounds_Pa = pressure.mode === 'gauge'
    ? pressure.bounds_Pa.map((value) => Number.isFinite(value) && Number.isFinite(pressure.reference_pressure_Pa) && pressure.reference_pressure_Pa > 0 ? value + pressure.reference_pressure_Pa : null)
    : [...pressure.bounds_Pa];
  requirements.heat_load = { mode: form.elements.heat_mode.value, value: numberValue('heat_value') };
  draft.requirements = requirements;
  updatePressureDescription();
}
function fillForm() {
  const r = draft.requirements;
  for (const key of ['title', 'solid_material', 'coolant_material', 'objective', 'other_thermal_boundaries', 'notes', 'inlet_temperature_K', 'maximum_surface_temperature_K']) form.elements[key].value = r[key] ?? '';
  form.elements.units_confirmed.checked = r.units_confirmed;
  form.elements.flow_min.value = r.mass_flow_bounds_kg_s?.[0] ?? '';
  form.elements.flow_max.value = r.mass_flow_bounds_kg_s?.[1] ?? '';
  form.elements.pressure_mode.value = r.pressure_input?.mode || 'absolute';
  form.elements.pressure_reference.value = r.pressure_input?.reference_pressure_Pa == null ? '' : r.pressure_input.reference_pressure_Pa / 100000;
  const pressureBounds = r.pressure_input?.bounds_Pa || r.outlet_absolute_pressure_bounds_Pa;
  form.elements.pressure_min.value = pressureBounds?.[0] == null ? '' : pressureBounds[0] / 100000;
  form.elements.pressure_max.value = pressureBounds?.[1] == null ? '' : pressureBounds[1] / 100000;
  form.elements.heat_mode.value = r.heat_load.mode;
  form.elements.heat_value.value = r.heat_load.value ?? '';
  updateHeatDescription();
  updatePressureDescription();
}
function updatePressureDescription() {
  const gauge = form.elements.pressure_mode.value === 'gauge';
  $('pressure-reference-field').hidden = !gauge;
  $('pressure-min-label').textContent = `Outlet pressure lower (bar ${gauge ? 'gauge' : 'absolute'})`;
  $('pressure-max-label').textContent = `Outlet pressure upper (bar ${gauge ? 'gauge' : 'absolute'})`;
  $('pressure-help').textContent = gauge
    ? 'Zero gauge pressure means the ambient/reference pressure. Absolute = gauge + reference. Enter lower ≤ upper; equal bounds give a fixed pressure.'
    : 'Both absolute-pressure bounds must be greater than zero, with lower ≤ upper. For a fixed pressure, enter the same value in both boxes.';
  const values = draft.requirements.outlet_absolute_pressure_bounds_Pa;
  $('pressure-conversion').textContent = gauge && values.every(Number.isFinite)
    ? `Absolute pressure used by the simulation: ${format(values[0]/100000)}–${format(values[1]/100000)} bar.` : '';
}
function updateHeatDescription() {
  const power = draft.requirements.heat_load.mode === 'total_heat_load_W';
  $('heat-value-unit').textContent = power ? 'Total power (W)' : 'Heat flux (W/m²)';
  $('heat-explanation').textContent = power ? 'Uniform distribution over the combined selected heated area; heat flows into the solid.' : 'Uniform heat flux into the solid on every orange surface.';
  const area = draft.selections.heated.reduce((sum, id) => sum + (faces.get(id)?.area_mm2 || 0), 0);
  const load = draft.requirements.heat_load.value;
  const derived = Number.isFinite(load) && load > 0 && area > 0
    ? power ? ` Equivalent uniform flux: ${format(load/(area*1e-6))} W/m².`
      : ` Total applied heat: ${format(load*area*1e-6)} W.` : '';
  $('heated-area').textContent = `Selected heated area: ${format(area)} mm².${derived}`;
}
function format(number) {
  return Number.isFinite(number) ? Number(number).toLocaleString(undefined, { maximumSignificantDigits: 6 }) : 'unknown';
}
function markDirty() {
  dirty = JSON.stringify({ selections: draft.selections, requirements: draft.requirements }) !== JSON.stringify({ selections: state.draft.selections, requirements: state.draft.requirements });
  $('confirm-review').checked = false;
  $('handoff-result').textContent = '';
  updateStatus();
}
function liveBoundsErrors() {
  const errors = {};
  for (const [key, prefix, label, unit] of [
    ['mass_flow_bounds_kg_s', 'flow', 'Mass flow', 'kg/s'],
    ['outlet_absolute_pressure_bounds_Pa', 'pressure', 'Outlet pressure', 'bar absolute']
  ]) {
    const pressure = draft.requirements.pressure_input;
    const gauge = prefix === 'pressure' && pressure?.mode === 'gauge';
    const [lower, upper] = prefix === 'pressure' && pressure ? pressure.bounds_Pa : draft.requirements[key];
    const shownUnit = gauge ? 'bar gauge' : unit;
    const scale = prefix === 'pressure' ? 100000 : 1;
    const reference = pressure?.reference_pressure_Pa;
    if (gauge && (!Number.isFinite(reference) || reference <= 0)) errors.pressure_reference = 'Enter an ambient/reference absolute pressure greater than 0 bar to convert gauge pressure.';
    for (const [field, position, value] of [[`${prefix}_min`, 'lower', lower], [`${prefix}_max`, 'upper', upper]]) {
      if (value === null) errors[field] = `Enter the ${label.toLowerCase()} ${position} bound in ${shownUnit}.`;
      else if (!Number.isFinite(value)) errors[field] = `${label} ${position} bound must be a finite number in ${shownUnit}.`;
      else if (gauge) { if (Number.isFinite(reference) && reference > 0 && value + reference <= 0) errors[field] = `${label} ${position} bound corresponds to ${(value + reference)/scale} bar absolute. The converted absolute pressure must be greater than 0 bar.`; }
      else if (value <= 0) errors[field] = `${label} ${position} bound is ${value/scale} ${shownUnit}. Enter a value greater than 0 ${shownUnit}.${prefix === 'pressure' ? ' If you meant gauge pressure, convert it using your ambient/reference pressure.' : ''}`;
    }
    if (Number.isFinite(lower) && Number.isFinite(upper) && lower > upper) errors[`${prefix}_min`] = `${label} lower bound (${lower/scale} ${shownUnit}) exceeds the upper bound (${upper/scale} ${shownUnit}). Correct the range.`;
  }
  return errors;
}
function updateStatus() {
  if (!state) return;
  const errors = !dirty && state.field_errors ? state.field_errors : liveBoundsErrors();
  for (const name of ['flow_min', 'flow_max', 'pressure_min', 'pressure_max', 'pressure_reference']) {
    const error = errors[name] || '';
    $(`${name}-error`).textContent = error;
    $(`${name}-error`).hidden = !error;
    form.elements[name].setAttribute('aria-invalid', String(Boolean(error)));
  }
  const approved = state.approved && !dirty && !conflicted;
  $('review-status').textContent = conflicted ? 'Reload required' : dirty ? 'Unsaved changes' : approved ? 'Approved for CAD' : 'Awaiting your review';
  $('review-status').className = `status${approved ? ' approved' : dirty ? ' dirty' : ''}`;
  $('save-state').textContent = dirty ? 'Save changes before approval.' : `Saved revision ${state.draft.revision}`;
  $('save').disabled = busy || !dirty || conflicted;
  $('reload').disabled = busy;
  $('approve').disabled = !viewerReady || busy || conflicted || dirty || state.approved || state.issues.length > 0 || !$('confirm-review').checked || !$('reviewer').value.trim();
  $('handoff').disabled = !viewerReady || busy || !approved;
  $('confirm-review').disabled = busy || dirty || conflicted || state.issues.length > 0 || state.approved;
  $('issues-panel').hidden = state.issues.length === 0;
  $('issues').replaceChildren(...state.issues.map((issue) => { const li = document.createElement('li'); li.textContent = issue; return li; }));
  if (dirty && state.approved) $('approval-details').textContent = 'These edits require a new approval after saving.';
  else if (state.approved) $('approval-details').textContent = `Current saved review approved${state.approval?.reviewer ? ` by ${state.approval.reviewer}` : ''}. Approval covers the requested setup; CAD and engineering checks remain.`;
  else $('approval-details').textContent = dirty ? 'The list above describes the last saved revision. Save to validate your changes.' : 'Save a complete draft, then confirm the displayed selections and values.';
}
async function api(path, body) {
  const options = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Review-Token': state.csrf_token }, body: JSON.stringify(body) };
  const response = await fetch(path, { ...options, cache: 'no-store' });
  let result;
  try { result = await response.json(); } catch { throw new Error(`The review server returned an unreadable response (${response.status}).`); }
  if (!response.ok) {
    if (response.status === 409) { conflicted = true; updateStatus(); throw new Error(`${result.error || 'This saved review changed in another session.'} Reload the saved review before continuing. Your unsaved changes have not overwritten it.`); }
    throw new Error(result.error || `Request failed (${response.status}).`);
  }
  return result;
}
async function withBusy(action) {
  if (busy) return;
  busy = true; message('');
  for (const element of form.elements) element.disabled = true;
  updateStatus();
  try { await action(); } catch (error) { message(error.message); }
  finally { busy = false; for (const element of form.elements) element.disabled = false; updateStatus(); }
}
function adoptState(next) {
  state = next; draft = structuredClone(next.draft); dirty = false; conflicted = false;
  $('confirm-review').checked = false;
  faces = new Map([...state.model.faces, ...(state.model.virtual_faces || [])].map((face) => [face.id, face]));
  if (!faces.has(selectedId)) selectedId = null;
  fillForm(); renderModelDetails(); renderFaceList();
  if (renderer && renderedFingerprint !== state.model.import_fingerprint) buildModel();
  refreshSelections(); updateStatus();
}
function renderModelDetails() {
  const model = state.model, b = model.bounds;
  $('model-name').textContent = model.source.name;
  $('model-dimensions').textContent = `Bounding dimensions: ${format(b[3]-b[0])} × ${format(b[4]-b[1])} × ${format(b[5]-b[2])} mm · ${model.solid_count} solid(s)`;
  $('source-details').replaceChildren();
  for (const text of [`Source: ${model.source.name}`, `Source SHA-256: ${model.source.sha256}`, `Import fingerprint: ${model.import_fingerprint}`, 'Port caps are proposed fluid boundaries, not source CAD faces. Their connectivity and final boundary mapping need CAD verification.']) { const p = document.createElement('p'); p.textContent = text; $('source-details').append(p); }
  $('geometry-warnings').replaceChildren(...(model.warnings || []).map((warning) => { const li = document.createElement('li'); li.textContent = typeof warning === 'string' ? warning : JSON.stringify(warning); return li; }));
}
function renderFaceList() {
  faceButtons = new Map(); $('face-list').replaceChildren();
  for (const face of faces.values()) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'face-button'; button.dataset.faceId = face.id;
    const label = document.createElement('span'); label.textContent = `${face.id} · ${face.kind === 'virtual_port' ? 'proposed port cap' : face.surface_type}`;
    const role = document.createElement('span'); role.className = 'role-label'; button.append(label, role);
    button.addEventListener('click', () => selectFace(face.id));
    $('face-list').append(button); faceButtons.set(face.id, button);
  }
}
function selectFace(id) {
  if (busy || conflicted) return;
  selectedId = id;
  if (activeRole !== 'inspect') {
    if (activeRole === 'heated' && faces.get(id).kind === 'virtual_port') message('A proposed fluid port cap cannot be a heated solid surface. Choose a source CAD face for heating.');
    else {
      for (const role of roles) draft.selections[role] = draft.selections[role].filter((faceId) => faceId !== id);
      if (roles.includes(activeRole)) draft.selections[activeRole].push(id);
      markDirty(); message('');
    }
  }
  refreshSelections();
}
function refreshSelections() {
  $('selection-summary').replaceChildren(...roles.map((role) => {
    const span = document.createElement('span'); span.className = `badge ${role}`;
    span.textContent = `${role === 'heated' ? 'Heat into solid' : role === 'inlet' ? 'Inlet' : 'Outlet'} · ${draft.selections[role].length}`;
    span.title = draft.selections[role].join(', ') || 'No surfaces selected'; return span;
  }));
  for (const [id, button] of faceButtons) {
    const role = roleOf(id); button.classList.toggle('selected', id === selectedId); button.setAttribute('aria-pressed', String(id === selectedId));
    const label = button.querySelector('.role-label'); label.className = `role-label ${role || ''}`; label.textContent = role === 'heated' ? 'Heat into solid' : role ? `${role[0].toUpperCase()}${role.slice(1)}` : 'Unassigned';
  }
  const face = faces.get(selectedId);
  $('inspector').textContent = face ? `${face.id} · ${face.kind === 'virtual_port' ? 'Proposed fluid port cap' : face.surface_type} · ${roleOf(face.id) || 'unassigned'} · Area ${format(face.area_mm2)} mm² · Center (${face.centroid_mm.map(format).join(', ')}) mm${face.radius_mm ? ` · Radius ${format(face.radius_mm)} mm` : ''}${face.kind === 'virtual_port' ? '. This cap is a proposal; assigning it does not verify the passage.' : ''}` : 'Select a surface to inspect it. Purple caps are proposed openings, awaiting your assignment.';
  updateHeatDescription(); updateMeshes();
}
async function initViewer() {
  THREE = await import('three');
  const { OrbitControls } = await import('/vendor/OrbitControls.js');
  const viewport = $('viewport');
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  viewport.prepend(renderer.domElement); renderer.domElement.setAttribute('aria-label', 'Interactive CAD review. The surface list below provides a keyboard alternative.');
  scene = new THREE.Scene(); camera = new THREE.PerspectiveCamera(40, 1, .01, 100000);
  camera.up.set(0, 0, 1);
  controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x667788, 2.5));
  const light = new THREE.DirectionalLight(0xffffff, 2.1); light.position.set(1, -1, 2); scene.add(light);
  const fill = new THREE.DirectionalLight(0xffffff, 1); fill.position.set(-1, 1, -1); scene.add(fill);
  raycaster = new THREE.Raycaster();
  const resize = () => { const w = viewport.clientWidth, h = viewport.clientHeight; renderer.setSize(w, h); camera.aspect = w/h; camera.updateProjectionMatrix(); };
  new ResizeObserver(resize).observe(viewport); resize();
  let pointerStart;
  renderer.domElement.addEventListener('pointerdown', (event) => { pointerStart = { x: event.clientX, y: event.clientY, button: event.button }; });
  renderer.domElement.addEventListener('pointerup', (event) => {
    if (!pointerStart || pointerStart.button !== 0 || Math.hypot(event.clientX-pointerStart.x, event.clientY-pointerStart.y)>5) return;
    const rect = renderer.domElement.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1, -(event.clientY-rect.top)/rect.height*2+1), camera);
    const hit = raycaster.intersectObjects([...meshes.values()].filter((mesh) => mesh.visible), false)[0];
    if (hit) selectFace(hit.object.userData.faceId);
  });
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  $('viewer-placeholder').hidden = true; buildModel(); viewerReady = true; updateStatus();
}
function buildModel() {
  if (group) { group.traverse((object) => { object.geometry?.dispose(); object.material?.dispose(); }); scene.remove(group); }
  group = new THREE.Group(); meshes = new Map();
  for (const face of faces.values()) {
    if (!face.positions?.length || !face.triangles?.length) continue;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(face.positions, 3));
    geometry.setIndex(face.triangles); geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({ color: colors.cad, side: THREE.DoubleSide, roughness: .72, metalness: .08, polygonOffset: true, polygonOffsetFactor: face.kind === 'virtual_port' ? -1 : 1, polygonOffsetUnits: 1 });
    const mesh = new THREE.Mesh(geometry, material); mesh.userData.faceId = face.id;
    group.add(mesh); meshes.set(face.id, mesh);
  }
  scene.add(group); renderedFingerprint = state.model.import_fingerprint; fitView(); updateMeshes();
}
function updateMeshes() {
  for (const [id, mesh] of meshes) {
    const face = faces.get(id), role = roleOf(id), cap = face.kind === 'virtual_port';
    mesh.visible = (!cap || $('show-caps').checked) && (!$('solo').checked || !selectedId || selectedId === id);
    mesh.material.color.setHex(role ? colors[role] : cap ? colors.cap : colors.cad);
    mesh.material.emissive.setHex(selectedId === id ? 0x293c4b : 0x000000);
    mesh.material.opacity = cap && !role ? .45 : $('xray').checked && !cap && !role ? .22 : 1;
    mesh.material.transparent = mesh.material.opacity < 1;
    mesh.material.depthWrite = !mesh.material.transparent;
    mesh.material.needsUpdate = true;
  }
}
function fitView() {
  if (!camera || !state) return;
  const b = state.model.bounds;
  const center = new THREE.Vector3((b[0]+b[3])/2, (b[1]+b[4])/2, (b[2]+b[5])/2);
  const radius = Math.max(Math.hypot(b[3]-b[0], b[4]-b[1], b[5]-b[2])/2, .001);
  const fov = Math.min(camera.fov*Math.PI/180, 2*Math.atan(Math.tan(camera.fov*Math.PI/360)*camera.aspect));
  const distance = radius/Math.sin(fov/2)*1.15;
  camera.position.copy(center).add(new THREE.Vector3(1,-1,.85).normalize().multiplyScalar(distance));
  camera.near = radius/1000; camera.far = radius*1000; camera.updateProjectionMatrix();
  controls.target.copy(center); controls.maxDistance = radius*500; controls.minDistance = radius/100; controls.update();
}
form.addEventListener('submit', (event) => event.preventDefault());
form.addEventListener('input', () => { if (!state) return; readForm(); updateHeatDescription(); markDirty(); });
for (const button of document.querySelectorAll('[data-role]')) button.addEventListener('click', () => { activeRole = button.dataset.role; for (const other of document.querySelectorAll('[data-role]')) other.setAttribute('aria-pressed', String(other === button)); });
for (const id of ['show-caps', 'xray', 'solo']) $(id).addEventListener('change', updateMeshes);
$('fit-view').addEventListener('click', fitView);
$('reviewer').addEventListener('input', updateStatus); $('confirm-review').addEventListener('change', updateStatus);
$('save').addEventListener('click', () => withBusy(async () => { readForm(); const next = await api('/api/draft', { expected_revision: state.draft.revision, draft: { selections: draft.selections, requirements: draft.requirements } }); adoptState(next); message(next.issues.length ? `Draft saved. ${next.issues.length} item(s) still need correction before approval; see the highlighted fields and review list.` : 'Draft saved. Review the current selections and requirements before approval.', true); }));
$('reload').addEventListener('click', () => { if (dirty && !window.confirm('Reload the saved review and discard your unsaved changes?')) return; withBusy(async () => { adoptState(await api('/api/state')); message('Loaded the saved review.', true); }); });
$('approve').addEventListener('click', () => withBusy(async () => { if (!viewerReady || dirty || conflicted || !$('confirm-review').checked || !$('reviewer').value.trim()) throw new Error('Save the current draft and explicitly confirm your review first.'); const next = await api('/api/approve', { expected_revision: state.draft.revision, draft_sha256: state.draft_sha256, confirmed: true, reviewer: $('reviewer').value.trim() }); adoptState(next); message('Your review is approved for CAD preparation.', true); }));
$('handoff').addEventListener('click', () => withBusy(async () => { if (!viewerReady || dirty || conflicted || !state.approved) throw new Error('The current unchanged draft must be approved before handoff.'); const result = await api('/api/handoff', {}); $('handoff-result').textContent = `CAD handoff created: ${result.handoff_directory}. No simulation has started.`; message('Approved requirements are ready for the CAD specialist.', true); }));
window.addEventListener('beforeunload', (event) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } });
(async () => { try { adoptState(await api('/api/state')); await initViewer(); } catch (error) { message(`Review could not fully load: ${error.message}`); $('viewer-placeholder').textContent = '3D viewer unavailable. Check the visible error before continuing.'; $('review-status').textContent = 'Review unavailable'; $('approve').disabled = true; $('handoff').disabled = true; } })();
