import asyncio, json, serial, random, math
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

SERIAL_PORT = "/dev/ttyACM0"
BAUD = 115200

SENSOR_LAT = 0.0
SENSOR_LON = 0.0

app = FastAPI()
clients = set()
mock_tasks = []

PAGE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Aerial Signal Monitor</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#f4f6f9;--panel:#fff;--panel2:#f8fafc;--line:#e2e8f0;
  --text:#0f172a;--dim:#64748b;--faint:#94a3b8;
  --drone:#dc2626;--drone-bg:#fef2f2;--cand:#0891b2;--cand-bg:#ecfeff;
  --ok:#16a34a;--accent:#1e40af;--warn:#d97706;
}
body{background:var(--bg);color:var(--text);height:100vh;display:flex;flex-direction:column;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:13px;overflow:hidden}
header{display:flex;align-items:center;gap:16px;padding:0 18px;height:54px;background:var(--panel);
  border-bottom:1px solid var(--line);flex-shrink:0;box-shadow:0 1px 3px rgba(15,23,42,.04);z-index:500}
.logo{display:flex;align-items:center;gap:10px}
.logo .mark{width:30px;height:30px;border-radius:7px;background:linear-gradient(135deg,#1e40af,#0891b2);
  display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:15px}
.logo h1{font-size:14px;font-weight:700;line-height:1.1}
.logo p{font-size:10px;color:var(--dim);letter-spacing:.05em;text-transform:uppercase}
.hclock{font-variant-numeric:tabular-nums;font-size:12px;color:var(--dim);font-weight:600;
  background:var(--panel2);border:1px solid var(--line);border-radius:6px;padding:5px 10px}
.hclock b{color:var(--text)}
.demo{display:flex;align-items:center;gap:6px;background:var(--panel2);border:1px solid var(--line);
  border-radius:6px;padding:4px 6px 4px 10px}
.demo label{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em;font-weight:600}
.demo input{width:42px;border:1px solid var(--line);border-radius:5px;padding:4px 6px;font-size:12px;
  text-align:center;font-family:inherit;font-variant-numeric:tabular-nums}
.demo button{border:none;border-radius:5px;padding:5px 10px;font-size:11px;font-weight:600;cursor:pointer;font-family:inherit}
.demo .go{background:var(--accent);color:#fff} .demo .go:hover{background:#1a3a9e}
.demo .stop{background:var(--panel);border:1px solid var(--line);color:var(--dim)}
.demo .stop:hover{border-color:var(--drone);color:var(--drone)}
.pill{display:flex;align-items:center;gap:7px;padding:5px 11px;border-radius:6px;background:var(--panel2);
  border:1px solid var(--line);font-size:11px;color:var(--dim);font-weight:500;cursor:pointer;user-select:none}
.pill:hover{border-color:var(--dim)}
.dot{width:7px;height:7px;border-radius:50%;background:var(--faint)}
.dot.live{background:var(--ok);box-shadow:0 0 0 0 rgba(22,163,74,.5);animation:p 2s infinite}
.dot.paused{background:var(--warn)}
@keyframes p{70%{box-shadow:0 0 0 6px rgba(22,163,74,0)}100%{box-shadow:0 0 0 0 rgba(22,163,74,0)}}
.stats{margin-left:auto;display:flex;gap:9px}
.kpi{background:var(--panel2);border:1px solid var(--line);border-radius:7px;padding:6px 12px;text-align:center;min-width:58px}
.kpi b{display:block;font-size:18px;font-weight:700;line-height:1.1;font-variant-numeric:tabular-nums}
.kpi small{color:var(--dim);font-size:9px;text-transform:uppercase;letter-spacing:.07em}
.kpi.d b{color:var(--drone)} .kpi.c b{color:var(--cand)}
main{flex:1;display:flex;min-height:0}
.mapwrap{flex:1;position:relative;min-width:0}
#map{position:absolute;inset:0;background:#e8edf2}
.ticker{position:absolute;left:0;right:0;bottom:0;height:30px;background:rgba(255,255,255,.94);
  border-top:1px solid var(--line);display:flex;align-items:center;gap:8px;padding:0 12px;z-index:400;
  font-size:11px;color:var(--dim);overflow:hidden}
.ticker .lab{font-weight:700;color:var(--text);text-transform:uppercase;letter-spacing:.06em;font-size:9px;flex-shrink:0}
.ticker .feed{display:flex;gap:16px;white-space:nowrap;overflow:hidden;flex:1}
.ticker .ev{flex-shrink:0}
.ev.d b{color:var(--drone)} .ev.c b{color:var(--cand)}
aside{width:400px;flex-shrink:0;background:var(--panel);border-left:1px solid var(--line);
  display:flex;flex-direction:column;min-height:0}
.sec{display:flex;flex-direction:column;min-height:0;flex:1}
.sec+.sec{border-top:1px solid var(--line)}
.sec-h{display:flex;align-items:center;gap:8px;padding:11px 15px 8px;flex-shrink:0}
.sec-h .tag{width:9px;height:9px;border-radius:3px}
.sec-h h2{font-size:12px;font-weight:700}
.sec-h .n{margin-left:auto;font-variant-numeric:tabular-nums;font-weight:700;font-size:12px}
.sec-h .ib{width:17px;height:17px;border-radius:50%;border:1px solid var(--line);background:var(--panel2);
  color:var(--dim);font-size:10px;font-weight:700;cursor:pointer;line-height:15px;text-align:center}
.sec-h .ib:hover{border-color:var(--dim);color:var(--text)}
.sec-h .clr{border:1px solid var(--line);background:var(--panel2);color:var(--dim);font-size:10px;
  border-radius:5px;padding:2px 8px;cursor:pointer;font-weight:600}
.sec-h .clr:hover{border-color:var(--drone);color:var(--drone)}
.tools{display:flex;gap:6px;padding:0 15px 8px;flex-shrink:0}
.tools input{flex:1;border:1px solid var(--line);border-radius:6px;padding:5px 9px;font-size:11px;
  background:var(--panel2);color:var(--text);font-family:inherit}
.tools input:focus{outline:none;border-color:var(--accent)}
.tools select{border:1px solid var(--line);border-radius:6px;padding:5px 7px;font-size:11px;
  background:var(--panel2);color:var(--dim);font-family:inherit;cursor:pointer}
.info{margin:0 15px 8px;padding:9px 11px;background:var(--panel2);border:1px solid var(--line);
  border-radius:7px;font-size:11px;line-height:1.55;color:var(--dim);display:none}
.info.open{display:block}
.info b{color:var(--text)} .info .lim{color:var(--warn);font-weight:600}
.d-info{border-left:3px solid var(--drone)} .c-info{border-left:3px solid var(--cand)}
.list{overflow-y:auto;padding:0 12px 12px;flex:1}
.list::-webkit-scrollbar{width:8px}
.list::-webkit-scrollbar-thumb{background:var(--line);border-radius:4px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;margin-bottom:7px;overflow:hidden;animation:in .22s ease}
@keyframes in{from{opacity:0;transform:translateY(-4px)}to{opacity:1}}
.card.drone{border-left:3px solid var(--drone)} .card.cand{border-left:3px solid var(--cand)}
.card.sel{box-shadow:0 0 0 2px var(--accent);border-color:var(--accent)}
.card.stale{opacity:.5}
.ch{display:flex;align-items:center;gap:8px;padding:8px 11px;cursor:pointer}
.ch:hover{background:var(--panel2)}
.badge{font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase;letter-spacing:.04em}
.card.drone .badge{background:var(--drone-bg);color:var(--drone)}
.card.cand .badge{background:var(--cand-bg);color:var(--cand)}
.cid{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;font-weight:600}
.live-tick{width:6px;height:6px;border-radius:50%;background:var(--ok);flex-shrink:0;opacity:0;transition:opacity .1s}
.live-tick.on{opacity:1}
.ct{margin-left:auto;color:var(--faint);font-size:10px;font-variant-numeric:tabular-nums}
.del{width:18px;height:18px;border:none;background:transparent;color:var(--faint);cursor:pointer;
  font-size:14px;line-height:1;border-radius:4px;flex-shrink:0}
.del:hover{background:var(--drone-bg);color:var(--drone)}
.cbody{padding:2px 11px 10px;display:grid;grid-template-columns:1fr 1fr;gap:5px 12px}
.f{display:flex;flex-direction:column;gap:1px}
.f .k{font-size:9px;color:var(--faint);text-transform:uppercase;letter-spacing:.05em}
.f .v{font-size:11.5px;font-weight:500;font-variant-numeric:tabular-nums}
.f.wide{grid-column:1/-1}
.sig{display:flex;align-items:center;gap:6px}
.bar{flex:1;height:4px;background:var(--line);border-radius:2px;overflow:hidden;max-width:70px}
.bar i{display:block;height:100%;border-radius:2px}
.card.drone .bar i{background:var(--drone)} .card.cand .bar i{background:var(--cand)}
.empty{color:var(--faint);font-size:11px;padding:10px 6px;font-style:italic}
.leaflet-container{background:#e8edf2;font:inherit}
.legend{background:rgba(255,255,255,.96);border:1px solid var(--line);border-radius:8px;
  padding:9px 11px;font-size:11px;color:var(--dim);box-shadow:0 2px 8px rgba(15,23,42,.08)}
.legend b{display:block;color:var(--text);font-size:9px;text-transform:uppercase;letter-spacing:.07em;margin-bottom:5px;font-weight:700}
.legend .r{display:flex;align-items:center;gap:7px;line-height:1.85}
.legend i{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.legend i.ring{border:2px dashed var(--cand);background:transparent;border-radius:50%}
.cmark{background:var(--cand);width:11px;height:11px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.3)}
</style></head><body>

<header>
  <div class="logo"><div class="mark">◈</div>
    <div><h1>Aerial Signal Monitor</h1><p>Passive RF &middot; Remote ID Surveillance</p></div></div>
  <div class="demo"><label>Demo</label>
    <input id="ndrones" type="number" min="1" max="20" value="3">
    <button class="go" onclick="spawn()">Launch</button>
    <button class="stop" onclick="clearAll('drone')">Clear</button></div>
  <div class="hclock">T+<b id="uptime">00:00:00</b></div>
  <div class="pill" id="pausebtn"><span class="dot" id="dot"></span><span id="stat">connecting</span></div>
  <div class="stats">
    <div class="kpi d"><b id="nd">0</b><small>Drones</small></div>
    <div class="kpi c"><b id="nc">0</b><small>Candidates</small></div>
    <div class="kpi"><b id="ntot">0</b><small>Contacts</small></div>
  </div>
</header>

<main>
  <div class="mapwrap"><div id="map"></div>
    <div class="ticker"><span class="lab">Event Feed</span><div class="feed" id="feed"></div></div></div>
  <aside>
    <div class="sec">
      <div class="sec-h"><span class="tag" style="background:#dc2626"></span>
        <h2>Remote ID Drones</h2><span class="ib" onclick="tog('di')">i</span>
        <span class="clr" onclick="clearAll('drone')">Clear</span>
        <span class="n" style="color:#dc2626" id="cd">0</span></div>
      <div class="info d-info" id="di">
        <b>Confirmed aircraft</b> broadcasting an FAA-mandated Remote ID beacon over WiFi or Bluetooth.
        Carries a real identifier, GPS position, and altitude, so these plot at true coordinates.
        <span class="lim">Limitation:</span> only sees drones that choose to broadcast — most units over
        250&nbsp;g. Compliant-but-spoofed IDs and non-broadcasting or sub-250&nbsp;g aircraft are invisible here.
      </div>
      <div class="tools"><input id="fd" placeholder="Filter by ID, MAC, vendor..." oninput="render('drone')">
        <select id="sd" onchange="render('drone')"><option value="new">Newest</option><option value="old">Oldest</option></select></div>
      <div class="list" id="drones"><div class="empty">No broadcasting aircraft detected</div></div>
    </div>
    <div class="sec">
      <div class="sec-h"><span class="tag" style="background:#0891b2"></span>
        <h2>RF Candidates</h2><span class="ib" onclick="tog('ci')">i</span>
        <span class="clr" onclick="clearAll('cand')">Clear</span>
        <span class="n" style="color:#0891b2" id="cc">0</span></div>
      <div class="info c-info" id="ci">
        <b>Unidentified transmitters</b> nearby whose signal strength swung enough to suggest motion.
        Derived only from a MAC address and signal strength — no protocol decode.
        <span class="lim">Limitation:</span> no bearing or true position — range is a rough RSSI estimate,
        drawn as a ring around the sensor. Cannot distinguish a drone from a phone, laptop, or any moving
        2.4&nbsp;GHz device. Treat as leads, not confirmed aircraft.
      </div>
      <div class="tools"><input id="fc" placeholder="Filter by MAC, vendor..." oninput="render('cand')">
        <select id="sc" onchange="render('cand')"><option value="new">Newest</option><option value="old">Oldest</option></select></div>
      <div class="list" id="rf"><div class="empty">Listening for transmitters...</div></div>
    </div>
  </aside>
</main>

<script>
var SENSOR=[__LAT__,__LON__];
var CAND_TTL=180000, STALE=30000, T0=Date.now(), paused=false;

var OUI={
 "58:e6":"Espressif","f4:cb":"Espressif","60:55":"Espressif","d8:3a":"Espressif",
 "34:ab":"Espressif","90:3a":"Parrot","fa:0b":"OpenDroneID","64:7a":"Realtek",
 "00:26":"DJI","60:60":"DJI","34:d2":"DJI","48:1c":"DJI","28:39":"Autel","94:2c":"Skydio"
};
var DRONE_OUI={"90:3a":1,"00:26":1,"60:60":1,"34:d2":1,"48:1c":1,"28:39":1,"94:2c":1,"fa:0b":1};

function tog(id){document.getElementById(id).classList.toggle('open');}
function pad(n){return n<10?'0'+n:n;}
function clock(){var d=new Date();return pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());}
function dist(r){return Math.pow(10,(-45-r)/(10*2.6));}
function pct(r){return Math.max(4,Math.min(100,(r+100)*1.8));}
function quality(r){return r>-55?'Strong':r>-70?'Moderate':r>-82?'Weak':'Very weak';}
function macType(m){return (parseInt(m.slice(0,2),16)&0x02)?'Randomized (private)':'Universal (hardware)';}
function vendor(m){var p=m.slice(0,5).toLowerCase();return OUI[p]||(((parseInt(m.slice(0,2),16)&0x02))?'—':'Unknown');}
function isDroneOui(m){return DRONE_OUI[m.slice(0,5).toLowerCase()]?true:false;}
function fmt(n){return n.toFixed(6);}

function spawn(){var n=Math.max(1,Math.min(20,parseInt(document.getElementById('ndrones').value)||1));fetch('/test?count='+n);}

var map=L.map('map',{zoomControl:false}).setView(SENSOR,14);
L.control.zoom({position:'bottomright'}).addTo(map);
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
 {maxZoom:19,attribution:'&copy; OpenStreetMap, &copy; CARTO'}).addTo(map);

L.circleMarker(SENSOR,{radius:7,color:'#16a34a',weight:2,fillColor:'#16a34a',fillOpacity:.85})
 .addTo(map).bindPopup('<b>Sensor Station</b><br>Board B &middot; '+fmt(SENSOR[0])+', '+fmt(SENSOR[1]));

var lg=L.control({position:'topright'});
lg.onAdd=function(){var d=L.DomUtil.create('div','legend');
 d.innerHTML='<b>Legend</b>'+
 '<div class="r"><i style="background:#dc2626"></i>Drone — GPS-confirmed</div>'+
 '<div class="r"><i class="ring"></i>Candidate — range est.</div>'+
 '<div class="r"><i style="background:#16a34a"></i>Sensor station</div>';return d;};
lg.addTo(map);

var drones={},cands={},sel=null;

function pseudoAngle(mac){var h=0;for(var i=0;i<mac.length;i++)h=(h*31+mac.charCodeAt(i))%360;return h*Math.PI/180;}
function ringPoint(m,mac){var a=pseudoAngle(mac),dLat=(m*Math.cos(a))/111320,
 dLon=(m*Math.sin(a))/(111320*Math.cos(SENSOR[0]*Math.PI/180));return [SENSOR[0]+dLat,SENSOR[1]+dLon];}

function feed(cls,txt){var f=document.getElementById('feed');var e=document.createElement('span');
 e.className='ev '+cls;e.innerHTML=txt;f.insertBefore(e,f.firstChild);
 while(f.children.length>12)f.removeChild(f.lastChild);}

function focus(key){sel=key;var o=drones[key]||cands[key];if(!o)return;
 if(o.marker){map.panTo(o.marker.getLatLng());o.marker.openPopup();}render('drone');render('cand');}

function wipe(o){
 if(o.marker)map.removeLayer(o.marker);
 if(o.ring)map.removeLayer(o.ring);
 if(o.trail)map.removeLayer(o.trail);
 if(o.dots){o.dots.forEach(function(d){map.removeLayer(d);});}
}

function delOne(kind,key,ev){if(ev)ev.stopPropagation();var obj=(kind==='drone'?drones:cands);var o=obj[key];if(!o)return;
 wipe(o);delete obj[key];counts();render(kind);}

function clearAll(kind){var obj=(kind==='drone'?drones:cands);
 for(var k in obj){wipe(obj[k]);}
 if(kind==='drone'){drones={};fetch('/stopmock');}else cands={};
 counts();render(kind);}

function counts(){
 document.getElementById('nd').textContent=Object.keys(drones).length;
 document.getElementById('cd').textContent=Object.keys(drones).length;
 document.getElementById('nc').textContent=Object.keys(cands).length;
 document.getElementById('cc').textContent=Object.keys(cands).length;
 document.getElementById('ntot').textContent=Object.keys(drones).length+Object.keys(cands).length;}

function fields(arr){return arr.map(function(f){
 return '<div class="f'+(f[2]?' wide':'')+'"><span class="k">'+f[0]+'</span><span class="v">'+f[1]+'</span></div>';}).join('');}

function dcard(o){var s=o.d,age=Math.round((Date.now()-o.first)/1000),stale=Date.now()-o.last>STALE;
 var name=s.basic_id||s.mac,hasgps=!(s.drone_lat===0&&s.drone_long===0),haspilot=s.pilot_lat&&s.pilot_lat!==0;
 return '<div class="card drone'+(sel===o.key?' sel':'')+(stale?' stale':'')+'" onclick="focus(\''+o.key+'\')">'+
  '<div class="ch"><span class="badge">Drone</span><span class="live-tick'+(Date.now()-o.last<1500?' on':'')+'"></span>'+
  '<span class="cid">'+name+'</span><span class="ct">'+o.time+'</span>'+
  '<button class="del" onclick="delOne(\'drone\',\''+o.key+'\',event)">✕</button></div>'+
  '<div class="cbody">'+fields([
   ['Signal','<span class="sig">'+s.rssi+' dBm<span class="bar"><i style="width:'+pct(s.rssi)+'%"></i></span></span>'],
   ['Quality',quality(s.rssi)],['Altitude',s.drone_altitude+' m MSL'],['Vendor',vendor(s.mac)],
   ['Position',hasgps?fmt(s.drone_lat)+', '+fmt(s.drone_long):'Not reported',true],
   ['Operator',haspilot?fmt(s.pilot_lat)+', '+fmt(s.pilot_long):'Not reported',true],
   ['MAC',s.mac],['Node',s.node_id||'—'],['First seen',age+'s ago'],['Updates',o.count+'×']
  ])+'</div></div>';}

function ccard(o){var s=o.d,age=Math.round((Date.now()-o.first)/1000),stale=Date.now()-o.last>STALE;
 var flag=isDroneOui(s.mac)?'<span style="color:#dc2626;font-weight:700">⚠ drone-vendor OUI</span>':'—';
 return '<div class="card cand'+(sel===o.key?' sel':'')+(stale?' stale':'')+'" onclick="focus(\''+o.key+'\')">'+
  '<div class="ch"><span class="badge">RF</span><span class="live-tick'+(Date.now()-o.last<1500?' on':'')+'"></span>'+
  '<span class="cid">'+s.mac+'</span><span class="ct">'+o.time+'</span>'+
  '<button class="del" onclick="delOne(\'cand\',\''+o.key+'\',event)">✕</button></div>'+
  '<div class="cbody">'+fields([
   ['Signal','<span class="sig">'+s.rssi+' dBm<span class="bar"><i style="width:'+pct(s.rssi)+'%"></i></span></span>'],
   ['Quality',quality(s.rssi)],['Est. range','~'+o.range+' m'],['Bearing','Unknown'],
   ['MAC type',macType(s.mac)],['Vendor',vendor(s.mac)],
   ['First seen',age+'s ago'],['Detections',o.count+'×'],['Vendor flag',flag,true]
  ])+'</div></div>';}

function render(which){
 if(which==='drone'){var q=document.getElementById('fd').value.toLowerCase(),sort=document.getElementById('sd').value;
  var arr=Object.values(drones).filter(function(o){var s=o.d;
   return !q||(s.basic_id||'').toLowerCase().includes(q)||s.mac.includes(q)||vendor(s.mac).toLowerCase().includes(q);});
  arr.sort(function(a,b){return sort==='old'?a.first-b.first:b.first-a.first;});
  var box=document.getElementById('drones');
  box.innerHTML=arr.length?arr.map(dcard).join(''):'<div class="empty">No broadcasting aircraft detected</div>';
 }else{var q=document.getElementById('fc').value.toLowerCase(),sort=document.getElementById('sc').value;
  var arr=Object.values(cands).filter(function(o){var s=o.d;return !q||s.mac.includes(q)||vendor(s.mac).toLowerCase().includes(q);});
  arr.sort(function(a,b){return sort==='old'?a.first-b.first:b.first-a.first;});
  var box=document.getElementById('rf');
  box.innerHTML=arr.length?arr.map(ccard).join(''):'<div class="empty">Listening for transmitters...</div>';}}

var ws=new WebSocket("ws://"+location.host+"/ws");
ws.onopen=function(){if(!paused){document.getElementById('stat').textContent='live';document.getElementById('dot').className='dot live';}};
ws.onclose=function(){document.getElementById('stat').textContent='disconnected';document.getElementById('dot').className='dot';};

document.getElementById('pausebtn').onclick=function(){paused=!paused;
 document.getElementById('stat').textContent=paused?'paused':'live';
 document.getElementById('dot').className='dot '+(paused?'paused':'live');};

ws.onmessage=function(ev){if(paused)return;var d=JSON.parse(ev.data);
 if(d.type==="rf_candidate"){
   var o=cands[d.mac]||{key:d.mac,first:Date.now(),count:0};o.count++;o.last=Date.now();o.d=d;o.time=clock();
   o.range=Math.round(dist(d.rssi));cands[d.mac]=o;
   var pt=ringPoint(o.range,d.mac);
   if(o.ring)map.removeLayer(o.ring);
   o.ring=L.circle(SENSOR,{radius:o.range,color:'#0891b2',weight:1.2,opacity:.4,dashArray:'5,6',fill:false}).addTo(map);
   if(!o.marker){o.marker=L.marker(pt,{icon:L.divIcon({className:'',html:'<div class="cmark"></div>',iconSize:[11,11]})}).addTo(map);}
   else o.marker.setLatLng(pt);
   o.marker.bindPopup('<b>RF Candidate</b><br>'+d.mac+'<br>'+d.rssi+' dBm &middot; est. '+o.range+' m<br><i>Position is range-only — bearing unknown</i>');
   feed('c','<b>'+d.mac.slice(0,8)+'…</b> RF '+d.rssi+'dBm ~'+o.range+'m');counts();render('cand');
 } else if(d.mac && d.drone_lat!==undefined){
   var o=drones[d.mac]||{key:d.mac,first:Date.now(),count:0};o.count++;o.last=Date.now();o.d=d;o.time=clock();drones[d.mac]=o;
   var name=d.basic_id||d.mac,hasgps=!(d.drone_lat===0&&d.drone_long===0);
   if(hasgps){var p=[d.drone_lat,d.drone_long];
    if(!o.dots)o.dots=[];
    o.dots.push(L.circleMarker(p,{radius:3,color:'#dc2626',weight:0,fillOpacity:.5}).addTo(map));
    if(!o.trail)o.trail=L.polyline([],{color:'#dc2626',weight:2.5,opacity:.5}).addTo(map);o.trail.addLatLng(p);
    if(!o.marker)o.marker=L.marker(p).addTo(map);else o.marker.setLatLng(p);
    o.marker.bindPopup('<b>'+name+'</b><br>Alt '+d.drone_altitude+' m &middot; '+d.rssi+' dBm<br>'+fmt(d.drone_lat)+', '+fmt(d.drone_long));
    if(!window._follow){map.setView(p,15);window._follow=true;}}
   feed('d','<b>'+name+'</b> drone alt '+d.drone_altitude+'m '+d.rssi+'dBm');counts();render('drone');}};

setInterval(function(){var t=Date.now();
 for(var k in cands){if(t-cands[k].last>CAND_TTL){wipe(cands[k]);delete cands[k];}}
 counts();render('drone');render('cand');},5000);

setInterval(function(){var s=Math.floor((Date.now()-T0)/1000);
 document.getElementById('uptime').textContent=pad(Math.floor(s/3600))+':'+pad(Math.floor(s/60)%60)+':'+pad(s%60);},1000);
</script></body></html>"""

PAGE = PAGE.replace("__LAT__", str(SENSOR_LAT)).replace("__LON__", str(SENSOR_LON))


@app.get("/")
async def index():
    return HTMLResponse(PAGE)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(websocket)


async def broadcast(msg):
    dead = []
    for c in list(clients):
        try:
            await c.send_text(msg)
        except Exception:
            dead.append(c)
    for c in dead:
        clients.discard(c)


async def serial_reader():
    loop = asyncio.get_running_loop()
    while True:
        ser = None
        try:
            ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)
            print(f"[backend] connected to {SERIAL_PORT}", flush=True)
            while True:
                raw = await loop.run_in_executor(None, ser.readline)
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "heartbeat" in data:
                    continue
                print("[rx]", line, flush=True)
                await broadcast(json.dumps(data))
        except Exception as e:
            print(f"[backend] serial error: {e} - retrying in 5s", flush=True)
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass
        await asyncio.sleep(5)


@app.get("/test")
async def test_drones(count: int = 3):
    count = max(1, min(20, count))
    vendors = ["60:60:1f", "34:d2:4f", "28:39:5e", "94:2c:11", "48:1c:b7"]
    for i in range(count):
        pre = random.choice(vendors)
        mac = f"{pre}:{random.randint(0,255):02x}:{random.randint(0,255):02x}:{random.randint(0,255):02x}"
        t = asyncio.create_task(mock_flight(f"MOCK-{i+1:02d}", mac))
        mock_tasks.append(t)
    return {"status": f"{count} mock drones launched"}


@app.get("/stopmock")
async def stop_mock():
    n = 0
    for t in mock_tasks:
        if not t.done():
            t.cancel()
            n += 1
    mock_tasks.clear()
    return {"status": f"stopped {n} mock flights"}


async def mock_flight(name, mac):
    lat = SENSOR_LAT + random.uniform(-0.003, 0.003)
    lon = SENSOR_LON + random.uniform(-0.003, 0.003)
    heading = random.uniform(0, 6.28)
    step = random.uniform(0.0004, 0.0008)
    try:
        for _ in range(40):
            heading += random.uniform(-0.4, 0.4)
            lat += step * math.cos(heading) + random.uniform(-0.0001, 0.0001)
            lon += step * math.sin(heading) + random.uniform(-0.0001, 0.0001)
            msg = {
                "mac": mac,
                "rssi": random.randint(-72, -42),
                "drone_lat": round(lat, 6),
                "drone_long": round(lon, 6),
                "drone_altitude": random.randint(40, 160),
                "pilot_lat": SENSOR_LAT,
                "pilot_long": SENSOR_LON,
                "basic_id": name,
                "node_id": "TEST",
            }
            print("[mock]", json.dumps(msg), flush=True)
            await broadcast(json.dumps(msg))
            await asyncio.sleep(2)
    except asyncio.CancelledError:
        pass


@app.on_event("startup")
async def startup():
    asyncio.create_task(serial_reader())
