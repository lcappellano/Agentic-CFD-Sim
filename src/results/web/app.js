import * as THREE from 'three';
import { ArcballControls } from '/vendor/ArcballControls.js';
const $ = id => document.getElementById(id);
let data, renderer, scene, camera, controls, objects = [], center, radius, marker;
const fieldKeys = {T_K:'T', p_absolute_Pa:'p', speed_m_s:'speed'};
const palette = ['#3b4cc0','#67a9cf','#f7f7f7','#ef8a62','#b2182b'].map(x => new THREE.Color(x));
const raycaster = new THREE.Raycaster();
let range = [0,1], lastProbe = null, halfHeight = 1;
const render = () => renderer?.render(scene,camera);
const key = () => fieldKeys[$('field').value];
function unit() { return key()==='T' ? ($('temperature-unit').value==='C'?'°C':'K') : key()==='p' ? 'bar '+$('pressure-unit').value : 'm/s'; }
function convert(v) { return key()==='T' ? v-($('temperature-unit').value==='C'?273.15:0) : key()==='p' ? (v-($('pressure-unit').value==='gauge'?data.pressure_reference_Pa:0))/100000 : v; }
function fmt(v) { return Number.isFinite(v) ? v.toLocaleString('en-US',{maximumFractionDigits:key()==='p'?5:3}) : 'Unavailable'; }
function color(v) { const t=Math.max(0,Math.min(1,(v-range[0])/(range[1]-range[0]||1)))*4; const i=Math.min(3,Math.floor(t)); return palette[i].clone().lerp(palette[i+1],t-i); }
function slices() { return objects.filter(o => o.userData.kind==='slice' && o.userData.source.axis===$('slice-axis').value); }
function chooseSlices(reset=false) { const list=slices(); $('slice-index').max=Math.max(0,list.length-1); if(reset) $('slice-index').value=Math.floor(list.length/2); const chosen=list[Number($('slice-index').value)]; $('slice-position').textContent=chosen ? `${chosen.userData.source.position_mm.toFixed(3)} mm` : 'No planes available'; $('slice-index').disabled=!list.length; return chosen; }
function update() {
  const selected=chooseSlices();
  $('temperature-control').hidden=key()!=='T'; $('pressure-control').hidden=key()!=='p'; $('reference-note').hidden=key()!=='p';
  $('reference-note').textContent=`Gauge reference: ${(data.pressure_reference_Pa/100000).toFixed(5)} bar absolute.`;
  $('opacity-value').textContent=Math.round(Number($('opacity').value)*100)+'%';
  const visible=[];
  for(const obj of objects) {
    const s=obj.userData.source, has=Array.isArray(s.values[key()]);
    const show=obj.userData.kind==='slice' ? $('show-slice').checked && obj===selected : s.region==='solid' ? $('show-solid').checked : $('show-fluid').checked;
    obj.visible=show && (s.region==='solid' || has);
    obj.userData.probeable=obj.visible && has && (s.region!=='solid'||Number($('opacity').value)>0.02);
    obj.material.opacity=s.region==='solid'?Number($('opacity').value):1;
    obj.material.transparent=obj.material.opacity<1; obj.material.depthWrite=obj.material.opacity>=1;
    if($('mesh').checked && !obj.userData.wire) {
      const wire=new THREE.LineSegments(new THREE.WireframeGeometry(obj.geometry),new THREE.LineBasicMaterial({color:0x263b48,transparent:true,opacity:0.16}));obj.add(wire);obj.userData.wire=wire;
    }
    if(obj.userData.wire)obj.userData.wire.visible=$('mesh').checked;
    if(obj.visible && has && obj.material.opacity>0.02) visible.push(obj);
  }
  let min=Infinity,max=-Infinity;
  for(const o of visible) for(const v of o.userData.source.values[key()]) {min=Math.min(min,convert(v));max=Math.max(max,convert(v));}
  range=min===Infinity?[0,1]:[min,max];
  for(const obj of objects) {
    if(!obj.visible) continue;
    const vals=obj.userData.source.values[key()], attr=obj.geometry.getAttribute('color');
    for(let t=0;t<attr.count/3;t++) { const c=vals ? color(convert(vals[t])) : new THREE.Color('#a8b9c3'); for(let j=0;j<3;j++) attr.setXYZ(t*3+j,c.r,c.g,c.b); }
    attr.needsUpdate=true;
  }
  const title=key()==='T'?'Temperature':key()==='p'?'Fluid pressure':'Fluid speed';
  $('field-title').textContent=`${title} · ${unit()}`; $('legend-title').textContent=`${title} (${unit()})`;
  $('legend-min').textContent=min===Infinity?'—':fmt(min); $('legend-max').textContent=min===Infinity?'—':fmt(max);
  $('range-note').textContent=min===Infinity?'No field-bearing layer visible':'Range over displayed data';
  if(lastProbe) renderProbe();
  render();
}
function configureControls() {
  controls?.dispose();
  controls=new ArcballControls(camera,renderer.domElement,scene);
  controls.target.copy(center);controls.setCamera(camera);controls.update();
  // Explicitly remove every default binding: left button belongs only to probing.
  for(const action of [...controls.mouseActions]) controls.unsetMouseAction(action.mouse,action.key);
  controls.setMouseAction('ROTATE',1);
  controls.setMouseAction('PAN',1,'CTRL');
  controls.setMouseAction('PAN',2);
  controls.setMouseAction('ZOOM','WHEEL');
  controls.enableAnimations=false;controls.enableFocus=false;
  controls.enableGizmos=false;controls.setGizmosVisible(false);
  controls.cursorZoom=false;controls.rotateSpeed=1;
  controls.minZoom=0.05;controls.maxZoom=100;
  controls.addEventListener('change',render);
}
function projection() {
  const viewport=$('viewport'),aspect=viewport.clientWidth/Math.max(1,viewport.clientHeight);
  camera.left=-halfHeight*aspect;camera.right=halfHeight*aspect;
  camera.top=halfHeight;camera.bottom=-halfHeight;camera.updateProjectionMatrix();
}
function fit(view=null) {
  const dirs={iso:[1,-1,0.8],front:[0,-1,0],back:[0,1,0],top:[0,0,1],bottom:[0,0,-1],left:[-1,0,0],right:[1,0,0]};
  // Fit preserves orientation; presets explicitly reset it, including the up vector.
  const direction=view ? new THREE.Vector3(...dirs[view]).normalize() : camera.getWorldDirection(new THREE.Vector3()).negate();
  if(view) camera.up.set(0,0,1);
  else camera.up.set(0,1,0).applyQuaternion(camera.quaternion);
  if(view==='top')camera.up.set(0,1,0);
  if(view==='bottom')camera.up.set(0,-1,0);
  halfHeight=radius*1.2/Math.min(1,$('viewport').clientWidth/Math.max(1,$('viewport').clientHeight));
  camera.zoom=1;camera.position.copy(center).addScaledVector(direction,radius*4);
  camera.near=radius/1000;camera.far=radius*100;projection();
  configureControls();render();
}
function renderProbe() {
  const {obj,triangle,point}=lastProbe,s=obj.userData.source, vals=s.values[key()];
  const value=vals?`${fmt(convert(vals[triangle]))} ${unit()}`:'Field not defined in this region';
  $('probe').textContent=`${s.region} · ${s.patch||`${s.axis.toUpperCase()} slice`} · ${value} | Position: ${point.map(v=>v.toFixed(3)).join(', ')} mm | ${s.face_ids?.length ? 'Face '+s.face_ids[triangle]+' · ':''}Cell ${s.cell_ids?.[triangle]??'unavailable'}. ${obj.userData.kind==='slice'?'Saved cell value (piecewise constant).':'Saved boundary-face value.'}`;
  marker.position.set(...point);marker.visible=true;render();
}
function addMesh(s,kind) {
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(s.positions_mm,3));geometry.setAttribute('color',new THREE.Float32BufferAttribute(new Float32Array(s.positions_mm.length),3));
  const material=new THREE.MeshBasicMaterial({vertexColors:true,side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:1,polygonOffsetUnits:1});
  const obj=new THREE.Mesh(geometry,material);obj.userData={source:s,kind};
  scene.add(obj);objects.push(obj);
}
function summaryEntry(label,value) { const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=String(value??'Unavailable');$('summary').append(dt,dd); }
function setup() {
  const viewport=$('viewport');scene=new THREE.Scene();scene.background=new THREE.Color('#edf3f7');
  camera=new THREE.OrthographicCamera(-1,1,1,-1,0.01,10000);renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));viewport.append(renderer.domElement);
  const bounds=new THREE.Box3(new THREE.Vector3(...data.bounds_mm[0]),new THREE.Vector3(...data.bounds_mm[1]));center=bounds.getCenter(new THREE.Vector3());radius=bounds.getSize(new THREE.Vector3()).length()/2;
  for(const s of data.surfaces) addMesh(s,'surface');for(const s of data.slices) addMesh(s,'slice');
  marker=new THREE.Mesh(new THREE.SphereGeometry(radius*0.008,12,8),new THREE.MeshBasicMaterial({color:0x122b3b,depthTest:false}));marker.visible=false;marker.renderOrder=10;scene.add(marker);
  const axes=new THREE.AxesHelper(radius*0.3);axes.position.set(...data.bounds_mm[0]);scene.add(axes);
  const resize=()=>{
    projection();renderer.setSize(viewport.clientWidth,viewport.clientHeight);
    // Arcball uses the visible frustum to map mouse motion to its virtual sphere.
    if(controls)controls.setTbRadius(controls.radiusFactor);
    render();
  };
  new ResizeObserver(resize).observe(viewport);resize();fit('iso');
  let down=null;
  const canvas=renderer.domElement;
  canvas.tabIndex=0;canvas.setAttribute('aria-label','3D result model. Middle drag rotates, Control middle drag or right drag pans, wheel zooms. F fits, Home resets.');
  canvas.addEventListener('pointerdown',e=>{
    if(e.button===1)e.preventDefault(); // Suppress browser middle-button autoscroll.
    canvas.focus({preventScroll:true});
    down=e.button===0 ? {id:e.pointerId,x:e.clientX,y:e.clientY,moved:false} : null;
  });
  window.addEventListener('pointermove',e=>{if(down?.id===e.pointerId && Math.hypot(e.clientX-down.x,e.clientY-down.y)>4)down.moved=true;});
  window.addEventListener('pointerup',e=>{
    const click=down;down=null;
    if(e.button!==0||!click||click.id!==e.pointerId||click.moved||e.target!==canvas||e.ctrlKey||e.shiftKey||e.metaKey)return;
    const r=canvas.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);
    const hit=raycaster.intersectObjects(objects.filter(o=>o.userData.probeable),false)[0];
    if(hit){lastProbe={obj:hit.object,triangle:hit.faceIndex,point:hit.point.toArray()};renderProbe();}
  });
  // Complete the native control gesture on cancellation / leaving the browser.
  const cancel=()=>{down=null;window.dispatchEvent(new PointerEvent('pointerup',{button:1,pointerType:'mouse'}));};
  canvas.addEventListener('pointercancel',cancel,true);window.addEventListener('blur',cancel);
  document.addEventListener('keydown',e=>{
    if(e.ctrlKey||e.metaKey||e.altKey||e.target.closest('input,select,textarea,[contenteditable]'))return;
    if(e.key.toLowerCase()==='f'){e.preventDefault();fit();}
    else if(e.key==='Home'){e.preventDefault();fit('iso');}
  });
  // Read-only diagnostics for reproducible browser navigation checks.
  // Arcball pans its internal gizmos without updating public target. Orthographic
  // zoom changes scale, not distance: the actual pivot remains radius*4 along
  // the view direction after both pan and rotation (established by fit above).
  window.resultsCameraState=()=>({position:camera.position.toArray(),up:camera.up.toArray(),quaternion:camera.quaternion.toArray(),zoom:camera.zoom,projection:camera.projectionMatrix.toArray(),orthographic:camera.isOrthographicCamera,center:center.toArray(),target:camera.getWorldDirection(new THREE.Vector3()).multiplyScalar(radius*4).add(camera.position).toArray()});
  $('loading').hidden=true;chooseSlices(true);update();
}
async function main() {
  const response=await fetch('/api/results');if(!response.ok)throw new Error(`Result data unavailable (${response.status})`);data=await response.json();
  $('run-title').textContent=data.run_id||data.run||'Saved simulation results';
  $('case-label').textContent=`${data.case_name||data.summary?.case||'Saved case'} · iteration ${data.time||data.summary?.latest_fields||'unknown'}`;
  const s=data.summary||{},m=s.monitor_last||{};
  summaryEntry('Heated-surface maximum',Number.isFinite(m.heatedMax)?`${(m.heatedMax-273.15).toFixed(2)} °C`:'Unavailable');
  summaryEntry('Temperature limit',Number.isFinite(data.temperature_limit_K)?`${(data.temperature_limit_K-273.15).toFixed(2)} °C`:'Unavailable');
  summaryEntry('Passage pressure drop',Number.isFinite(s.pressure_drop_Pa)?`${(s.pressure_drop_Pa/100000).toFixed(5)} bar`:'Unavailable');
  summaryEntry('Mass flow',Number.isFinite(m.outletMass)?`${m.outletMass.toFixed(4)} kg/s`:'Unavailable');
  if(data.temperature_extrema_K) {
    const e=data.temperature_extrema_K;
    summaryEntry('Copper maximum',`${(e.solid.max-273.15).toFixed(2)} °C`);
    summaryEntry('Water cell maximum',`${(e.fluid.internal_max-273.15).toFixed(2)} °C`);
    summaryEntry('Water-side wall maximum',Number.isFinite(m.wettedMax)?`${(m.wettedMax-273.15).toFixed(2)} °C`:'Unavailable');
    summaryEntry('Mixed outlet water',Number.isFinite(m.outletTemperature)?`${(m.outletTemperature-273.15).toFixed(2)} °C`:'Unavailable');
  }
  if(data.operating_point) {
    $('pressure-unit').value='absolute';
    const op=data.operating_point;
    summaryEntry('Specified flow',`${op.flow_L_min} L/min`);
    summaryEntry('Specified outlet pressure',`${(op.outlet_absolute_pressure_Pa/100000).toFixed(2)} bar absolute`);
    summaryEntry('Part total-pressure difference',Number.isFinite(s.total_pressure_drop_Pa)?`${(s.total_pressure_drop_Pa/100000).toFixed(3)} bar`:'Unavailable');
    if(Number.isFinite(op.differential_target_Pa))summaryEntry('Pressure-difference target',`${(op.differential_target_Pa/100000).toFixed(2)} bar (comparison only)`);
  }
  summaryEntry('Acceptance',typeof data.acceptance==='string'?data.acceptance:data.acceptance?.status?.replaceAll('_',' '));
  summaryEntry('Numerical criteria',data.acceptance?.numerical_criteria);
  summaryEntry('Experimental validation',data.acceptance?.experimental_validation||'Not experimentally validated');
  $('qualification').textContent=data.acceptance?.qualification||data.qualification||'Acceptance depends on the recorded numerical review and modeling qualifications. CFD verification does not establish experimental validation.';
  $('provenance').textContent=JSON.stringify({case:data.case_name||s.case,iteration:data.time||s.latest_fields,source:data.provenance,limitations:data.limitations},null,2);
  setup();
  for(const id of ['temperature-unit','pressure-unit','show-solid','show-fluid','show-slice','opacity','slice-index','mesh']) $(id).addEventListener('input',update);
  $('field').addEventListener('change',()=>{if(key()!=='T'){$('opacity').value='0.15';$('show-slice').checked=true;}update();});
  $('slice-axis').addEventListener('change',()=>{chooseSlices(true);update();});$('reset').addEventListener('click',()=>fit());
  document.querySelectorAll('[data-view]').forEach(el=>el.addEventListener('click',()=>fit(el.dataset.view)));
  document.documentElement.dataset.resultsReady='true';
}
main().catch(err=>{$('error').hidden=false;$('error').textContent=`Unable to display results: ${err.message}`;$('loading').textContent='Viewer unavailable. See the error above.';console.error(err);});
