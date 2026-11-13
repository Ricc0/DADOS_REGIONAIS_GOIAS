# -*- coding: utf-8 -*-
"""
Gera o mapa interativo (HTML autocontido) de indicadores de saude de Goias.

Junta:
  - geometria das 18 regioes de saude (BR_Regionais_Simplificado.geojson, est 52)
  - geometria dos 246 municipios (Dados/malha_municipios_go.geojson, IBGE)
  - indicadores (indicadores_go.json, gerado por build_indicadores.py)

Saida: mapa_indicadores_goias.html
"""
import os, json, math

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REG_GEO = os.path.join(HERE, "shapefile_das_regionais_de_saude_sus-master", "BR_Regionais_Simplificado.geojson")
MUN_GEO = os.path.join(HERE, "Dados", "malha_municipios_go.geojson")
IND = os.path.join(HERE, "indicadores_go.json")

NOMES_REG = {
    "52001":"Central","52002":"Centro Sul","52003":"Entorno Norte","52004":"Entorno Sul",
    "52005":"Estrada de Ferro","52006":"Nordeste I","52007":"Nordeste II","52008":"Norte",
    "52009":"Oeste I","52010":"Oeste II","52011":"Pirineus","52012":"Rio Vermelho",
    "52013":"São Patrício I","52014":"Serra da Mesa","52015":"Sudoeste I","52016":"Sudoeste II",
    "52017":"Sul","52018":"São Patrício II",
}

# ---------- geometria ----------
def rings(geom):
    if geom["type"] == "Polygon":
        for r in geom["coordinates"]:
            yield r
    else:
        for poly in geom["coordinates"]:
            for r in poly:
                yield r

reg_gj = json.loads(open(REG_GEO, encoding="latin-1").read())
reg_feats = {str(f["properties"]["reg_id"]): f["geometry"]
             for f in reg_gj["features"] if f["properties"]["est_id"] == 52}
mun_gj = json.loads(open(MUN_GEO, encoding="utf-8").read())
mun_feats = {f["properties"]["codarea"][:6]: f["geometry"] for f in mun_gj["features"]}

# bbox comum (usa municipios, que cobrem todo o estado)
minx = miny = 1e9; maxx = maxy = -1e9
for g in mun_feats.values():
    for r in rings(g):
        for x, y in r:
            minx = min(minx, x); maxx = max(maxx, x); miny = min(miny, y); maxy = max(maxy, y)

W, H, PAD = 720, 660, 12
lat0 = math.radians((miny + maxy) / 2); kx = math.cos(lat0)
scale = min((W - 2*PAD) / ((maxx - minx) * kx), (H - 2*PAD) / (maxy - miny))
ox = (W - (maxx - minx) * kx * scale) / 2
oy = (H - (maxy - miny) * scale) / 2

def proj(x, y):
    return (ox + (x - minx) * kx * scale, oy + (maxy - y) * scale)

def path_d(geom):
    parts = []
    for r in rings(geom):
        pts = [proj(x, y) for x, y in r]
        parts.append("M" + "L".join(f"{px:.1f},{py:.1f}" for px, py in pts) + "Z")
    return "".join(parts)

def centroid(geom):
    best = max(rings(geom), key=len)
    xs = [p[0] for p in best]; ys = [p[1] for p in best]
    return proj(sum(xs)/len(xs), sum(ys)/len(ys))

reg_paths = {rid: path_d(g) for rid, g in reg_feats.items()}
reg_cent = {rid: [round(c, 1) for c in centroid(g)] for rid, g in reg_feats.items()}
mun_paths = {cod: path_d(g) for cod, g in mun_feats.items()}
mun_cent = {cod: [round(c, 1) for c in centroid(g)] for cod, g in mun_feats.items()}

DATA = json.load(open(IND, encoding="utf-8"))

# ---- mescla morbidade (SIH), se disponivel ----
MORB_PATH = os.path.join(HERE, "morbidade_go.json")
HAS_MORB = os.path.exists(MORB_PATH)
if HAS_MORB:
    MORB = json.load(open(MORB_PATH, encoding="utf-8"))
    campos = ("taxa_internacao", "internacoes", "internacoes_transmissiveis",
              "obitos_hospitalares", "letalidade_hosp", "valor_total", "causas_internacao")
    for lvl in ("regioes", "municipios"):
        for aid, d in MORB[lvl].items():
            if aid in DATA[lvl]:
                DATA[lvl][aid].update({k: d[k] for k in campos if k in d})
    DATA["meta"]["indicadores"].update(MORB["meta"]["indicadores"])
    DATA["meta"]["periodo_morb"] = MORB["meta"]["periodo"]
    DATA["meta"]["fonte_morb"] = MORB["meta"]["fonte"]

# ---- mescla SINAN (agravos), se disponivel ----
SINAN_PATH = os.path.join(HERE, "sinan_go.json")
HAS_SINAN = os.path.exists(SINAN_PATH)
if HAS_SINAN:
    SIN = json.load(open(SINAN_PATH, encoding="utf-8"))
    for lvl in ("regioes", "municipios"):
        for aid, dd in SIN[lvl].items():
            if aid in DATA[lvl]:
                DATA[lvl][aid]["sinan"] = dd
    DATA["meta"]["sinan_doencas"] = SIN["meta"]["doencas"]
    DATA["meta"]["fonte_sinan"] = SIN["meta"]["fonte"]

# ---------- HTML ----------
def js(o):
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))

morb_options = ('<optgroup label="Morbidade (SIH/SUS)">'
                '<option value="taxa_internacao">Internações hospitalares</option>'
                '<option value="causas_internacao">Causas de internação (CID-10)</option>'
                '</optgroup>') if HAS_MORB else ''

sinan_options = ''
if HAS_SINAN:
    grupos = {}
    for slug, m in DATA["meta"]["sinan_doencas"].items():
        grupos.setdefault(m["grupo"], []).append((slug, m["titulo"]))
    for grupo, items in grupos.items():
        opts = ''.join(f'<option value="sinan_{slug}">{tit}</option>' for slug, tit in items)
        sinan_options += f'<optgroup label="🦠 SINAN — {grupo}">{opts}</optgroup>'

html = f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Indicadores de Saúde — Goiás</title>
<style>
:root{{--bg:#f6f8fa;--card:#fff;--ink:#1a2733;--muted:#5b6b7a;--line:#e2e8ee;--accent:#2a78d6;}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:"Segoe UI",system-ui,Arial,sans-serif;background:var(--bg);color:var(--ink);font-size:14px}}
header{{background:#0d2b45;color:#fff;padding:14px 22px}}
header h1{{margin:0;font-size:19px}} header p{{margin:3px 0 0;font-size:12.5px;color:#b9d0e6}}
.wrap{{display:flex;gap:16px;padding:16px;align-items:flex-start;flex-wrap:wrap}}
.mapcard{{position:relative;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;flex:1 1 540px;min-width:340px}}
.perbadge{{margin-left:auto;background:#0d2b45;color:#fff;padding:6px 14px;border-radius:20px;
  font-size:12.5px;font-weight:700;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.15)}}
.perbadge small{{font-weight:500;opacity:.8}}
.side{{flex:1 1 340px;min-width:300px;display:flex;flex-direction:column;gap:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.controls{{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:10px}}
.controls label{{font-size:12px;color:var(--muted);display:block;margin-bottom:3px;font-weight:600}}
select,.toggle button{{font:inherit}}
select{{padding:6px 8px;border:1px solid var(--line);border-radius:7px;background:#fff}}
.toggle{{display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden}}
.toggle button{{padding:6px 12px;border:0;background:#fff;cursor:pointer;color:var(--muted)}}
.toggle button.on{{background:var(--accent);color:#fff}}
#sexctl.off{{opacity:.4;pointer-events:none}}
.hint{{font-weight:400;font-size:10.5px;color:var(--muted)}}
svg{{width:100%;height:auto;display:block}}
path.feat{{stroke:#fff;stroke-width:.6;cursor:pointer;transition:opacity .1s}}
path.feat:hover{{stroke:#111;stroke-width:1.3}}
path.sel{{stroke:#111;stroke-width:1.8}}
.legend{{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:12px;color:var(--muted);flex-wrap:wrap}}
.grad{{height:14px;width:200px;border:1px solid #ccc;border-radius:3px}}
.hatchbox{{width:14px;height:14px;border:1px solid #ccc;border-radius:3px;
  background:repeating-linear-gradient(45deg,#e7ecf1,#e7ecf1 3px,#cdd6de 3px,#cdd6de 6px)}}
h2{{font-size:15px;margin:0 0 8px}} h3{{font-size:13px;margin:14px 0 6px;color:var(--accent)}}
.big{{font-size:30px;font-weight:700;line-height:1.1}} .unit{{font-size:12px;color:var(--muted)}}
.kv{{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px dashed var(--line);font-size:13px}}
.kv b{{font-weight:600}}
.bar{{height:9px;background:var(--accent);border-radius:3px}}
.causa{{display:grid;grid-template-columns:1fr auto;gap:3px 8px;align-items:center;font-size:12.5px;margin:2px 0}}
.crow{{margin:8px 0;font-size:12.5px}}
.crow .top{{display:flex;justify-content:space-between;gap:8px}}
.sbar{{height:10px;border-radius:3px;overflow:hidden;display:flex;background:#eef0f2;margin-top:3px}}
.sbar .sh{{background:#2a78d6}} .sbar .sm{{background:#e34948}}
.hm{{font-size:11px;color:#8a97a3;margin-top:2px}} .hm b{{font-weight:600}}
.hmleg{{font-size:11.5px;color:var(--muted);margin:6px 0 4px}}
.ast{{color:#c9821a;font-weight:700}}
.foot{{margin-top:10px;padding:8px 10px;background:#fff7e6;border:1px solid #ffe1a8;border-radius:7px;
  font-size:11px;color:#7a5a15;line-height:1.45}}
.flag{{background:#fff7e6;border:1px solid #ffe1a8;color:#8a5a00;padding:6px 9px;border-radius:7px;font-size:12px;margin-top:8px}}
details{{margin-top:6px}} summary{{cursor:pointer;font-weight:600;color:var(--accent);font-size:13px}}
.meth{{font-size:12.5px;color:var(--muted);line-height:1.5}}
.meth code{{background:#eef2f6;padding:1px 5px;border-radius:4px;font-size:11.5px}}
.pill{{display:inline-block;background:#eef4fb;color:var(--accent);border-radius:20px;padding:2px 9px;font-size:11px;font-weight:600}}
.searchbar{{background:#fff;border-bottom:1px solid var(--line);padding:12px 22px}}
.search-inner{{position:relative;max-width:560px;margin:0 auto}}
#busca{{width:100%;padding:10px 16px;border:1px solid var(--line);border-radius:24px;font-size:14px;outline:none}}
#busca:focus{{border-color:var(--accent);box-shadow:0 0 0 3px rgba(42,120,214,.12)}}
#resultados{{position:absolute;left:0;right:0;top:46px;background:#fff;border:1px solid var(--line);border-radius:10px;box-shadow:0 6px 22px rgba(0,0,0,.14);z-index:30;max-height:340px;overflow:auto;display:none}}
#resultados .r{{padding:9px 14px;cursor:pointer;display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid #f0f3f6}}
#resultados .r:hover{{background:#eef4fb}}
#resultados .tag{{font-size:10.5px;color:#fff;background:var(--accent);border-radius:10px;padding:1px 9px;align-self:center;white-space:nowrap}}
#resultados .tag.mun{{background:#59a14f}}
.verficha{{margin-top:14px;background:var(--accent);color:#fff;border:0;padding:9px 16px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:600}}
.verficha:hover{{background:#1f5fb0}}
.modal{{position:fixed;inset:0;background:rgba(10,25,40,.55);display:none;align-items:flex-start;justify-content:center;z-index:60;padding:24px;overflow:auto}}
.modal.open{{display:flex}}
.modal-box{{background:var(--card);border-radius:14px;max-width:840px;width:100%;padding:24px 28px;position:relative;box-shadow:0 12px 44px rgba(0,0,0,.32)}}
#fecharFicha{{position:absolute;top:14px;right:16px;border:0;background:#eef2f6;width:34px;height:34px;border-radius:50%;cursor:pointer;font-size:15px;color:#333}}
#fecharFicha:hover{{background:#dce4ec}}
.ficha-titulo{{font-size:25px;font-weight:700}}
.ficha-sub{{color:var(--muted);font-size:13px;margin:2px 0 8px}}
.ficha-sec{{font-size:15px;font-weight:700;margin:20px 0 10px;padding-bottom:5px;border-bottom:2px solid var(--line)}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:10px}}
.tile{{background:#f7f9fb;border:1px solid var(--line);border-radius:10px;padding:10px 13px}}
.tile-v{{font-size:20px;font-weight:700;line-height:1.15}}
.tile-l{{font-size:11.5px;color:var(--muted);margin-top:2px}}
.tile-u{{font-size:11px;color:var(--accent);margin-top:1px}}
.tile.h{{border-left:4px solid #2a78d6}} .tile.h .tile-v{{color:#1f5fb0}}
.tile.m{{border-left:4px solid #e34948}} .tile.m .tile-v{{color:#c0392b}}
.sexbar{{height:16px;border-radius:4px;overflow:hidden;display:flex;margin-top:12px;background:#eef0f2}}
.sexbar .sh{{background:#2a78d6}} .sexbar .sm{{background:#e34948}}
.sexbar-lbl{{display:flex;justify-content:space-between;font-size:12px;margin-top:5px;font-weight:600}}
.ficha h4{{font-size:11.5px;margin:16px 0 6px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
.tc{{margin:6px 0;font-size:12.5px}}
.tc-top{{display:flex;justify-content:space-between;gap:8px}}
.tc-bar{{height:7px;background:#eef0f2;border-radius:3px;overflow:hidden;margin-top:2px}}
.tc-bar div{{height:100%;background:var(--accent)}}
.tc-r{{font-size:11px;color:var(--muted);margin-top:1px}}
.munlist{{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0}}
.munchip{{background:#eef4fb;border:1px solid #d7e3f0;border-radius:16px;padding:4px 11px;font-size:12px;cursor:pointer;color:#1f5fb0}}
.munchip:hover{{background:#dce9f7}}
.munchip small{{color:#8a97a3;margin-left:5px}}
</style></head><body>
<header>
  <h1>Indicadores de Saúde — Estado de Goiás</h1>
  <p>Demografia (Censo 2022) · Mortalidade (SIM/SINASC {DATA['meta']['ano']}){(' · Morbidade (SIH ' + DATA['meta']['periodo_morb'] + ')') if HAS_MORB else ''} · metodologia: livro verde IDB/RIPSA 3ª ed.</p>
</header>
<div class="searchbar"><div class="search-inner">
  <input id="busca" type="text" autocomplete="off" placeholder="🔎 Buscar município ou região de saúde e ver a ficha completa…">
  <div id="resultados"></div>
</div></div>
<div class="wrap">
  <div class="mapcard">
    <div class="controls">
      <div><label>Nível</label>
        <div class="toggle" id="lvl">
          <button data-lvl="reg" class="on">Regiões de saúde</button>
          <button data-lvl="mun">Municípios</button>
        </div></div>
      <div><label>Indicador</label>
        <select id="ind">
          <optgroup label="Demografia (Censo 2022)">
            <option value="populacao">População</option>
            <option value="razao_sexo">Razão de sexo / % mulheres</option>
          </optgroup>
          <optgroup label="Mortalidade (SIM/SINASC)">
            <option value="mortalidade_infantil">Mortalidade infantil</option>
            <option value="mortalidade_materna">Mortalidade materna</option>
            <option value="causas">Causas de óbito (CID-10)</option>
          </optgroup>
          <optgroup label="♀ Saúde da mulher e gênero">
            <option value="pct_cesarea">Cesáreas (%)</option>
            <option value="gravidez_adolescencia">Gravidez na adolescência (%)</option>
            <option value="prenatal_adequado">Pré-natal adequado (%)</option>
            <option value="baixo_peso">Baixo peso ao nascer (%)</option>
            <option value="cancer_mama">Mortalidade câncer de mama</option>
            <option value="cancer_colo">Mortalidade câncer colo do útero</option>
          </optgroup>
          <optgroup label="🚨 Violência (óbitos — SIM)">
            <option value="feminicidio">Homicídios de mulheres (feminicídio)</option>
          </optgroup>
          {morb_options}
          {sinan_options}
        </select></div>
      <div id="sexctl"><label>Sexo <span id="sexhint" class="hint"></span></label>
        <div class="toggle" id="sexf">
          <button data-s="ambos" class="on">Ambos</button>
          <button data-s="h">Homens</button>
          <button data-s="m">Mulheres</button>
        </div></div>
      <div class="perbadge" id="per"></div>
    </div>
    <svg viewBox="0 0 {W} {H}" id="map">
      <g id="g-reg"></g><g id="g-mun" style="display:none"></g>
      <g id="g-lbl"></g>
    </svg>
    <div class="legend" id="legend"></div>
  </div>
  <div class="side">
    <div class="card" id="panel"></div>
    <div class="card" id="method"></div>
  </div>
</div>
<div id="ficha" class="modal"><div class="modal-box"><button id="fecharFicha" title="Fechar">✕</button><div id="ficha-conteudo"></div></div></div>
<script>
const REGP={js(reg_paths)},REGC={js(reg_cent)},MUNP={js(mun_paths)},MUNC={js(mun_cent)};
const NOMES={js(NOMES_REG)};
const DATA={js(DATA)};
const RAMP=[[234,242,251],[198,219,239],[107,174,214],[49,130,189],[8,81,156]]; // azul sequencial
const GRAY=[240,239,236],RED=[227,73,72],BLUE=[42,120,214];                    // divergente
function lerp(a,b,t){{return a.map((v,i)=>Math.round(v+(b[i]-v)*t))}}
function ramp(t){{t=Math.max(0,Math.min(1,t));const s=t*(RAMP.length-1);const i=Math.floor(s);
  if(i>=RAMP.length-1)return RAMP[RAMP.length-1];return lerp(RAMP[i],RAMP[i+1],s-i)}}
function rgb(c){{return 'rgb('+c[0]+','+c[1]+','+c[2]+')'}}
// escala divergente em torno de 100 (razao de sexo): <100 vermelho (mais mulheres), >100 azul
function divcolor(v,mid,maxdev){{const t=Math.max(-1,Math.min(1,(v-mid)/maxdev));
  return t>0?lerp(GRAY,BLUE,t):lerp(GRAY,RED,-t)}}
const MINDEN=100; // denominador minimo p/ taxa confiavel (nascidos vivos)
function scaleOf(){{return indic==='razao_sexo'?'div':'seq'}}
function isDemo(){{return indic==='populacao'||indic==='razao_sexo'}}
function isMorb(){{return indic==='taxa_internacao'||indic==='causas_internacao'}}
const INDS_MULHER=['pct_cesarea','gravidez_adolescencia','prenatal_adequado','baixo_peso','cancer_mama','cancer_colo','feminicidio'];
function isMulher(){{return INDS_MULHER.includes(indic);}}
// denominador populacional (mulheres) -> sempre confiaveis (nao usam nascidos vivos)
function isMulherPop(){{return indic==='cancer_mama'||indic==='cancer_colo'||indic==='feminicidio';}}
function isSinan(){{return indic.indexOf('sinan_')===0;}}
function sinanArr(d){{const k=indic.slice(6);return (d.sinan&&d.sinan[k])?d.sinan[k]:null;}}
function sinanMeta(){{return (DATA.meta.sinan_doencas||{{}})[indic.slice(6)]||{{}};}}
// rotulo de periodo/fonte do indicador atual (para o selo)
function periodoLabel(){{
  if(isDemo())return '<small>Censo IBGE</small> 2022';
  if(isMorb())return '<small>SIH/SUS</small> '+DATA.meta.periodo_morb;
  if(isSinan())return '<small>SINAN</small> '+(sinanMeta().ano||'');
  return '<small>SIM/SINASC</small> '+DATA.meta.ano;
}}

let level='reg', indic='populacao', selId=null, sexf='ambos';

// --- suporte a filtro de sexo e taxa por 100 mil (causas de obito/internacao) ---
function isCausa(){{return indic==='causas'||indic==='causas_internacao'}}
function sexFilterable(){{return isCausa()||isSinan()}}
function sexKey(){{return sexf==='h'?1:(sexf==='m'?2:0)}}   // indice em [total,h,m]
function popOf(d){{return sexf==='h'?d.homens:(sexf==='m'?d.mulheres:d.populacao)}}
function causaObj(d){{return indic==='causas_internacao'?d.causas_internacao:d.causas}}
function totalSexo(d){{const o=causaObj(d)||{{}};const k=sexKey();let s=0;for(const c in o)s+=o[c][k];return s;}}
function per100k(n,d){{const p=popOf(d);return p?Math.round(n/p*100000*10)/10:null;}}
function sexNome(){{return sexf==='h'?'homens':(sexf==='m'?'mulheres':'ambos os sexos')}}

function feats(){{return level==='reg'?DATA.regioes:DATA.municipios}}
function paths(){{return level==='reg'?REGP:MUNP}}
function cents(){{return level==='reg'?REGC:MUNC}}
function nomeOf(id){{const d=feats()[id];return d?d.nome:id}}

// valor usado no choropleth
function valueOf(d){{
  if(isCausa())return per100k(totalSexo(d),d);   // taxa por 100 mil (sexo filtrado)
  if(isSinan()){{const a=sinanArr(d);return a?per100k(a[sexKey()],d):null;}}
  return d[indic];
}}
// demografia, causas, morbidade e SINAN usam denominador populacional (sempre confiavel);
// taxas de mortalidade/saude-da-mulher dependem de nascidos vivos
function reliable(d){{return (indic==='causas'||isDemo()||isMorb()||isSinan()||isMulherPop())?true:(d.nascidos_vivos>=MINDEN)}}

function drawMap(){{
  const gR=document.getElementById('g-reg'),gM=document.getElementById('g-mun');
  gR.innerHTML=Object.keys(REGP).map(id=>`<path class="feat" id="f-${{id}}" data-id="${{id}}" d="${{REGP[id]}}"></path>`).join('');
  gM.innerHTML=Object.keys(MUNP).map(id=>`<path class="feat" id="f-${{id}}" data-id="${{id}}" d="${{MUNP[id]}}"></path>`).join('');
  document.querySelectorAll('path.feat').forEach(p=>{{
    p.onclick=()=>select(p.dataset.id);
    p.onmouseenter=()=>hover(p.dataset.id);
  }});
}}

function colorize(){{
  const f=feats();const ids=Object.keys(paths()).filter(id=>f[id]);
  const vals=ids.filter(id=>reliable(f[id])).map(id=>valueOf(f[id])).filter(v=>v!=null);
  const mn=Math.min(...vals),mx=Math.max(...vals);
  const div=scaleOf()==='div';
  const maxdev=div?Math.max(...vals.map(v=>Math.abs(v-100)))||1:0;
  ids.forEach(id=>{{
    const el=document.getElementById('f-'+id);if(!el)return;
    const d=f[id];const v=valueOf(d);
    if(!reliable(d)||v==null){{el.style.fill='url(#hatch)';}}
    else if(div){{el.style.fill=rgb(divcolor(v,100,maxdev));}}
    else{{const t=mx>mn?(v-mn)/(mx-mn):.5;el.style.fill=rgb(ramp(t));}}
  }});
  // legenda
  let unit=isSinan()?'casos por 100.000 hab.':DATA.meta.indicadores[indic].unidade;
  if(indic==='causas')unit='óbitos por 100.000 hab.';
  else if(indic==='causas_internacao')unit='internações por 100.000 hab.';
  let lg;
  if(div){{
    const lo=100-maxdev,hi=100+maxdev;
    const stops=[lo,(lo+100)/2,100,(hi+100)/2,hi].map(v=>rgb(divcolor(v,100,maxdev))).join(',');
    lg=`<span style="color:#c0392b">${{fmt(lo)}} ◄ mais mulheres</span>`
      +`<div class="grad" style="background:linear-gradient(90deg,${{stops}})"></div>`
      +`<span style="color:#1f5fb0">mais homens ► ${{fmt(hi)}}</span><span>&nbsp;(${{unit}}; cinza=100)</span>`;
  }} else {{
    const stops=[0,.25,.5,.75,1].map(t=>rgb(ramp(t))).join(',');
    lg=`<span>${{fmt(mn)}}</span><div class="grad" style="background:linear-gradient(90deg,${{stops}})"></div><span>${{fmt(mx)}}</span><span>&nbsp;${{unit}}</span>`;
    if(!isDemo()&&!isMorb()&&!isCausa()&&!isSinan()&&!isMulherPop())lg+=`<span style="margin-left:10px"><span class="hatchbox"></span> denominador baixo (&lt;${{MINDEN}} nasc.)</span>`;
  }}
  document.getElementById('legend').innerHTML=lg;
  // rotulos numericos so p/ regioes
  const gl=document.getElementById('g-lbl');
  if(level==='reg'){{
    gl.innerHTML=ids.map(id=>{{const c=REGC[id];return `<text x="${{c[0]}}" y="${{c[1]}}" font-size="9" text-anchor="middle" fill="#12324e" style="pointer-events:none;font-weight:600">${{nomeOf(id)}}</text>`}}).join('');
  }} else gl.innerHTML='';
}}
function fmt(v){{if(v==null)return '—';return (Math.round(v*10)/10).toLocaleString('pt-BR')}}
function fmtInt(v){{return (v||0).toLocaleString('pt-BR')}}

function hover(id){{ /* reservado p/ tooltip futuro */ }}

function select(id){{
  selId=id;
  document.querySelectorAll('path.sel').forEach(p=>p.classList.remove('sel'));
  const el=document.getElementById('f-'+id);if(el)el.classList.add('sel');
  panel(id);
}}

// renderiza lista de causas (capitulo CID-10) com taxa/100 mil e divisao por sexo
function renderCausas(obj,d){{
  const cs=Object.entries(obj||{{}});
  if(!cs.length)return '<p class="meth">Sem registros no período.</p>';
  const k=sexKey();
  cs.sort((a,b)=>b[1][k]-a[1][k]);                 // ordena pelo sexo selecionado
  const mx=Math.max(1,...cs.map(c=>c[1][k]));
  let out = sexf==='ambos'
    ? `<div class="hmleg"><span style="color:#1f5fb0">■ homens</span> &nbsp; <span style="color:#c0392b">■ mulheres</span> &nbsp;<span style="opacity:.7">· nº bold = taxa/100 mil hab.</span></div>`
    : `<div class="hmleg">Filtrado: <b>${{sexNome()}}</b> · nº bold = taxa/100 mil hab.</div>`;
  let temNota=false;
  out+=cs.map(([cap,v])=>{{
    const t=v[0],hh=v[1],mm=v[2],cnt=v[k],rate=per100k(cnt,d);
    // capitulo XV (gravidez/parto/puerperio) com registro masculino = provavel erro de digitacao
    const gravMasc=cap.indexOf('Gravidez')>=0 && hh>0;
    if(gravMasc && sexf!=='m')temNota=true;
    let bar;
    if(sexf==='ambos'){{
      const den=(hh+mm)||1;
      bar=`<div class="sbar" style="width:${{Math.max(3,Math.round(t/mx*100))}}%">`
         +`<div class="sh" style="width:${{Math.round(hh/den*100)}}%"></div>`
         +`<div class="sm" style="width:${{Math.round(mm/den*100)}}%"></div></div>`;
    }} else {{
      const col=sexf==='h'?'#2a78d6':'#e34456';
      bar=`<div class="sbar" style="width:${{Math.max(3,Math.round(cnt/mx*100))}}%">`
         +`<div style="width:100%;background:${{col}}"></div></div>`;
    }}
    const ast=gravMasc?'<span class="ast">*</span>':'';
    const info = sexf==='ambos'
      ? `<span style="color:#1f5fb0">♂ ${{fmtInt(hh)}}${{ast}}</span> &nbsp; <span style="color:#c0392b">♀ ${{fmtInt(mm)}}</span> &nbsp;·&nbsp; ${{fmtInt(t)}} casos`
      : `${{fmtInt(cnt)}}${{sexf==='h'?ast:''}} casos`;
    return `<div class="crow"><div class="top"><span>${{cap}}</span><b>${{fmt(rate)}}</b></div>${{bar}}`
      +`<div class="hm">${{info}}</div></div>`;
  }}).join('');
  if(temNota)out+=`<div class="foot"><span class="ast">*</span> Registros masculinos em “Gravidez, parto e puerpério” representam ≈0,18% do capítulo — provavelmente <b>erro de digitação</b> no campo sexo do SUS (o campo registra o sexo, não a identidade de gênero).</div>`;
  return out;
}}

function panel(id){{
  const d=feats()[id];const p=document.getElementById('panel');
  if(!d){{p.innerHTML='<h2>Selecione uma área no mapa</h2><p class="meth">Clique numa região ou município para ver os indicadores.</p>';return;}}
  const sub=level==='reg'?`Região de saúde · ${{d.macrorregiao}} · ${{d.n_municipios}} municípios`:`Município · região ${{NOMES[d.regiao_id]||d.regiao_id}}`;
  let h=`<h2>${{d.nome}}</h2><div class="meth" style="margin-bottom:10px">${{sub}}</div>`;
  if(indic==='causas'){{
    const cnt=totalSexo(d),rate=per100k(cnt,d);
    h+=`<div class="big">${{fmt(rate)}}</div><div class="unit">óbitos por 100.000 hab. · ${{sexNome()}} · ${{DATA.meta.ano}}</div>`;
    h+=`<div style="margin-top:10px">`+kv(`Óbitos (${{sexNome()}})`,fmtInt(cnt))+kv('População base',fmtInt(popOf(d)))+`</div>`;
    h+=`<h3>Por capítulo da CID-10 — taxa /100 mil</h3>`;
    h+=renderCausas(d.causas,d);
  }} else if(indic==='populacao'){{
    h+=`<div class="big">${{fmtInt(d.populacao)}}</div><div class="unit">habitantes (Censo 2022)</div>`;
    h+=`<div style="margin-top:12px">`
      +kv('Mulheres',`${{fmtInt(d.mulheres)}} <span class="pill">${{fmt(d.pct_mulheres)}}%</span>`)
      +kv('Homens',`${{fmtInt(d.homens)}} <span class="pill">${{fmt(100-d.pct_mulheres)}}%</span>`)
      +kv('Razão de sexo',`${{fmt(d.razao_sexo)}} <span class="unit">H/100 M</span>`)+`</div>`;
  }} else if(indic==='razao_sexo'){{
    const fem=d.razao_sexo<100;
    h+=`<div class="big" style="color:${{fem?'#c0392b':'#1f5fb0'}}">${{fmt(d.razao_sexo)}}</div>`
      +`<div class="unit">homens por 100 mulheres · <b>${{fem?'maioria feminina':'maioria masculina'}}</b></div>`;
    h+=`<div style="margin-top:12px">`
      +kv('% de mulheres',`<b>${{fmt(d.pct_mulheres)}}%</b>`)
      +kv('Mulheres',fmtInt(d.mulheres))+kv('Homens',fmtInt(d.homens))
      +kv('População',fmtInt(d.populacao))+`</div>`;
    h+=`<div class="meth" style="margin-top:8px"><b>Escala:</b> <span style="color:#c0392b">vermelho</span> = mais mulheres (razão &lt;100); <span style="color:#1f5fb0">azul</span> = mais homens (&gt;100); cinza = equilíbrio (100).</div>`;
  }} else if(indic==='taxa_internacao'){{
    const per=DATA.meta.periodo_morb;
    h+=`<div class="big">${{fmt(d.taxa_internacao)}}</div><div class="unit">internações SUS por 1.000 hab. · ${{per}}</div>`;
    h+=`<div style="margin-top:12px">`
      +kv('Internações',`${{fmtInt(d.internacoes)}} <span class="pill">${{fmtInt(d.internacoes_transmissiveis)}} transmissíveis</span>`)
      +kv('Óbitos hospitalares',`${{fmtInt(d.obitos_hospitalares)}} <span class="pill">letalidade ${{fmt(d.letalidade_hosp)}}%</span>`)
      +kv('Valor SUS pago',`R$ ${{fmtInt(Math.round(d.valor_total))}}`)
      +kv('População (2022)',fmtInt(d.populacao))+`</div>`;
    h+=`<div class="meth" style="margin-top:8px"><b>Transmissíveis:</b> internações por doenças infecciosas e parasitárias (Cap. I da CID-10, A00–B99).</div>`;
  }} else if(indic==='causas_internacao'){{
    const cnt=totalSexo(d),rate=per100k(cnt,d);
    h+=`<div class="big">${{fmt(rate)}}</div><div class="unit">internações por 100.000 hab. · ${{sexNome()}} · ${{DATA.meta.periodo_morb}}</div>`;
    h+=`<div style="margin-top:10px">`+kv(`Internações (${{sexNome()}})`,fmtInt(cnt))+kv('População base',fmtInt(popOf(d)))+`</div>`;
    h+=`<h3>Por capítulo da CID-10 (diagnóstico principal) — taxa /100 mil</h3>`;
    h+=renderCausas(d.causas_internacao,d);
  }} else if(isMulher()){{
    const val=d[indic],m=DATA.meta.indicadores[indic];
    h+=`<div class="big">${{fmt(val)}}</div><div class="unit">${{m.unidade}} · ${{DATA.meta.ano}}</div>`;
    h+=`<div style="margin-top:12px">`;
    if(indic==='cancer_mama')h+=kv('Óbitos por câncer de mama',fmtInt(d.obitos_cancer_mama))+kv('População feminina',fmtInt(d.mulheres));
    else if(indic==='cancer_colo')h+=kv('Óbitos por câncer do colo',fmtInt(d.obitos_cancer_colo))+kv('População feminina',fmtInt(d.mulheres));
    else if(indic==='feminicidio')h+=kv('Óbitos de mulheres por agressão',fmtInt(d.obitos_feminicidio))+kv('População feminina',fmtInt(d.mulheres));
    else{{const cnt=Math.round(val/100*d.nascidos_vivos);h+=kv('Casos (estimado)',fmtInt(cnt))+kv('Nascidos vivos',fmtInt(d.nascidos_vivos));}}
    h+=`</div>`;
    if(!reliable(d))h+=`<div class="flag">⚠️ Denominador baixo (${{fmtInt(d.nascidos_vivos)}} nascidos vivos): taxa/percentual <b>instável</b> — veja as contagens absolutas.</div>`;
    if(indic==='feminicidio')h+=`<div class="meth" style="margin-top:8px"><b>Proxy:</b> óbitos de mulheres por agressão (CID-10 X85–Y09). Não existe CID específico de feminicídio.</div>`;
    if(indic==='prenatal_adequado')h+=`<div class="meth" style="margin-top:8px">Aqui, <b>valores maiores são melhores</b> (mais gestantes com 7+ consultas).</div>`;
  }} else if(isSinan()){{
    const a=sinanArr(d)||[0,0,0],sm=sinanMeta();
    const cnt=a[sexKey()],rate=per100k(cnt,d);
    h+=`<div class="big">${{fmt(rate)}}</div><div class="unit">casos por 100.000 hab. · ${{sexNome()}} · ${{sm.titulo}} (${{sm.ano||''}})</div>`;
    h+=`<div style="margin-top:12px">`+kv(`Casos (${{sexNome()}})`,fmtInt(cnt));
    if(sexf==='ambos')h+=`<div class="kv"><span>Por sexo</span><b><span style="color:#1f5fb0">♂ ${{fmtInt(a[1])}}</span> &nbsp; <span style="color:#c0392b">♀ ${{fmtInt(a[2])}}</span></b></div>`;
    h+=kv('População base',fmtInt(popOf(d)))+`</div>`;
    if(sexf==='ambos'&&(a[1]+a[2])>0){{
      const pm=Math.round(a[2]/(a[1]+a[2])*100);
      h+=`<div class="sexbar"><div class="sh" style="width:${{100-pm}}%"></div><div class="sm" style="width:${{pm}}%"></div></div>`
        +`<div class="sexbar-lbl"><span style="color:#1f5fb0">♂ ${{100-pm}}%</span><span style="color:#c0392b">${{pm}}% ♀</span></div>`;
    }}
    if(sm.single_sex)h+=`<div class="meth" style="margin-top:8px">Agravo específico de <b>${{sm.single_sex==='F'?'mulheres':'homens'}}</b>.</div>`;
    if(indic==='sinan_violencia')h+=`<div class="meth" style="margin-top:8px">Notificações de <b>violência interpessoal/autoprovocada</b> (doméstica, física, sexual, psicológica). O recorte por sexo é central para o estudo de gênero.</div>`;
  }} else {{
    const val=d[indic];const unit=DATA.meta.indicadores[indic].unidade;
    h+=`<div class="big">${{fmt(val)}}</div><div class="unit">${{unit}}</div>`;
    h+=`<div style="margin-top:12px">`;
    if(indic==='mortalidade_infantil'){{
      h+=kv('Óbitos &lt;1 ano',fmtInt(d.obitos_infantis))+kv('Nascidos vivos',fmtInt(d.nascidos_vivos));
    }} else {{
      h+=kv('Óbitos maternos (total)',`${{fmtInt(d.obitos_maternos)}} <span class="pill">${{fmtInt(d.obitos_maternos_tardios)}} tardias</span>`)
        +kv('Nascidos vivos',fmtInt(d.nascidos_vivos));
    }}
    h+=`</div>`;
    if(!reliable(d))h+=`<div class="flag">⚠️ Denominador baixo (${{fmtInt(d.nascidos_vivos)}} nascidos vivos): a taxa é <b>estatisticamente instável</b> — interprete pelas contagens absolutas.</div>`;
    if(indic==='mortalidade_materna')h+=`<div class="meth" style="margin-top:8px"><b>Tardias (O96/O97):</b> mortes maternas ocorridas mais de 42 dias após o fim da gestação. Estão <b>incluídas</b> no total; a definição estrita as excluiria.</div>`;
  }}
  h+=`<button class="verficha" onclick="abrirFicha('${{level}}','${{id}}')">📋 Ver ficha completa →</button>`;
  p.innerHTML=h;
}}
function kv(k,v){{return `<div class="kv"><span>${{k}}</span><b>${{v}}</b></div>`}}

function methodology(){{
  const M=DATA.meta;
  let titulo,definicao,nota='',formula,fonteDados,reproduzir;
  if(isSinan()){{
    const sm=sinanMeta();
    titulo=sm.titulo+' (SINAN)';
    definicao='Casos notificados de '+sm.titulo+' entre residentes de Goiás, por 100.000 habitantes (denominador: Censo 2022).';
    if(sm.single_sex)nota='Agravo específico de '+(sm.single_sex==='F'?'mulheres':'homens')+'.';
    formula='casos notificados (por local de residência) ÷ população × 100.000';
    fonteDados=M.fonte_sinan;
    reproduzir=`<p style="margin-top:8px">1. Baixe do DATASUS (portal <code>datasus.saude.gov.br</code>, Fonte = <b>SINAN</b>) o arquivo do agravo — costuma ser nacional (<code>&lt;AGRAVO&gt;BR&lt;AA&gt;.dbc</code>) — e salve em <code>Dados/</code>.<br>
       2. Rode <code>python -m pipeline.build_sinan</code> (decodifica, filtra residentes de GO por <code>ID_MN_RESI</code> e agrega por município/região e sexo).<br>
       3. Gere o mapa: <code>python -m pipeline.build_mapa</code>.</p>`;
    document.getElementById('method').innerHTML=`<h2>📖 Metodologia — ${{titulo}}</h2><div class="meth">
      <p><b>Definição:</b> ${{definicao}}</p><p><b>Fórmula:</b> ${{formula}}.</p>
      <p><b>Fonte dos dados:</b> ${{fonteDados}}</p>${{nota?`<p><b>Nota:</b> ${{nota}}</p>`:''}}
      <p><b>Referência metodológica:</b> ${{M.referencia_metodologica}}</p>
      <details><summary>Como reproduzir estes números</summary>${{reproduzir}}</details></div>`;
    return;
  }}
  const m=DATA.meta.indicadores[indic];
  formula={{
    populacao:'contagem de pessoas residentes (Censo 2022), agregada por município e região',
    razao_sexo:'população masculina ÷ população feminina × 100 (Censo 2022)',
    mortalidade_infantil:'óbitos de menores de 1 ano ÷ nascidos vivos × 1.000',
    mortalidade_materna:'óbitos maternos (CID-10 O00–O99) ÷ nascidos vivos × 100.000',
    causas:'taxa = óbitos ÷ população × 100.000, por capítulo da CID-10 (com filtro por sexo)',
    taxa_internacao:'internações hospitalares pagas pelo SUS ÷ população × 1.000',
    causas_internacao:'taxa = internações ÷ população × 100.000, por capítulo do diagnóstico principal (com filtro por sexo)',
    cancer_mama:'óbitos por câncer de mama (CID C50) ÷ população feminina × 100.000',
    cancer_colo:'óbitos por câncer do colo do útero (CID C53) ÷ população feminina × 100.000',
    feminicidio:'óbitos de mulheres por agressão (CID X85–Y09) ÷ população feminina × 100.000',
    pct_cesarea:'partos cesáreos ÷ total de nascidos vivos × 100',
    gravidez_adolescencia:'nascidos de mães de 10–19 anos ÷ total de nascidos vivos × 100',
    prenatal_adequado:'nascidos cujas mães fizeram 7+ consultas de pré-natal ÷ total × 100',
    baixo_peso:'nascidos com peso inferior a 2.500g ÷ total de nascidos × 100'
  }}[indic];
  fonteDados=isMorb()?M.fonte_morb:(isDemo()?M.fonte_demografia:M.fonte);
  if(isMorb()){{
    reproduzir=`<p style="margin-top:8px">1. Baixe do DATASUS (portal <code>datasus.saude.gov.br</code>) os arquivos <b>RD (AIH Reduzida)</b> do SIH/SUS de Goiás — são <b>mensais</b> (<code>RDGO&lt;AAMM&gt;.dbc</code>) — e salve em <code>Dados/</code>.<br>
       2. Rode <code>python -m pipeline.build_morbidade</code> (decodifica os <code>.dbc</code>, filtra residentes de GO e agrega por município e região). Detecta automaticamente todos os meses presentes.<br>
       3. Gere o mapa: <code>python -m pipeline.build_mapa</code>.<br>
       Internações atribuídas ao <b>município de residência</b> (MUNIC_RES); denominador populacional do Censo 2022.</p>`;
  }} else if(isDemo()){{
    reproduzir=`<p style="margin-top:8px">1. Os dados de sexo vêm do <b>Censo IBGE 2022</b> via API SIDRA (tabela 9514) — o pipeline baixa e cacheia automaticamente em <code>Dados/censo2022_sexo_go.json</code>.<br>
       2. Rode <code>python -m pipeline.build_indicadores</code> (agrega por município de residência e por região de saúde).<br>
       3. Gere o mapa: <code>python -m pipeline.build_mapa</code>.</p>`;
  }} else {{
    reproduzir=`<p style="margin-top:8px">1. Baixe do DATASUS (portal <code>datasus.saude.gov.br</code>) os arquivos de Goiás do ano ${{M.ano}}:
       <code>DOGO${{M.ano}}.dbc</code> (SIM/óbitos) e <code>DNGO${{M.ano}}.dbc</code> (SINASC/nascidos), e salve em <code>Dados/</code>.<br>
       2. Rode o pipeline: <code>python -m pipeline.build_indicadores</code> (decodifica os <code>.dbc</code> e agrega por município e por região).<br>
       3. Gere este mapa: <code>python -m pipeline.build_mapa</code>.<br>
       Os óbitos são atribuídos ao <b>município de residência</b> (CODMUNRES) e agregados às 18 regiões de saúde.</p>`;
  }}
  const html=`<h2>📖 Metodologia — ${{m.titulo}}</h2>
    <div class="meth">
    <p><b>Definição:</b> ${{m.definicao}}</p>
    <p><b>Fórmula:</b> ${{formula}}.</p>
    <p><b>Fonte dos dados:</b> ${{fonteDados}}</p>
    ${{m.nota?`<p><b>Nota:</b> ${{m.nota}}</p>`:''}}
    <p><b>Referência metodológica:</b> ${{M.referencia_metodologica}}</p>
    <details><summary>Como reproduzir estes números</summary>${{reproduzir}}</details></div>`;
  document.getElementById('method').innerHTML=html;
}}

function refresh(){{
  document.getElementById('per').innerHTML='📅 '+periodoLabel();
  const sc=document.getElementById('sexctl');
  sc.classList.toggle('off',!sexFilterable());
  document.getElementById('sexhint').textContent=sexFilterable()?'':'(só causas)';
  colorize();methodology();
  if(selId&&feats()[selId])panel(selId);else panel(null);
}}

document.getElementById('lvl').addEventListener('click',e=>{{
  const b=e.target.closest('button');if(!b)return;
  level=b.dataset.lvl;
  document.querySelectorAll('#lvl button').forEach(x=>x.classList.toggle('on',x===b));
  document.getElementById('g-reg').style.display=level==='reg'?'':'none';
  document.getElementById('g-mun').style.display=level==='mun'?'':'none';
  selId=null;document.querySelectorAll('path.sel').forEach(p=>p.classList.remove('sel'));
  refresh();
}});
document.getElementById('ind').addEventListener('change',e=>{{indic=e.target.value;refresh();}});
document.getElementById('sexf').addEventListener('click',e=>{{
  const b=e.target.closest('button');if(!b)return;
  sexf=b.dataset.s;
  document.querySelectorAll('#sexf button').forEach(x=>x.classList.toggle('on',x===b));
  refresh();
}});

// pattern de hachura p/ denominador baixo
document.getElementById('map').insertAdjacentHTML('afterbegin',
 '<defs><pattern id="hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">'+
 '<rect width="6" height="6" fill="#e7ecf1"/><rect width="3" height="6" fill="#cdd6de"/></pattern></defs>');

// ---- busca de municipios/regioes ----
const IDX=[];
for(const id in DATA.regioes)IDX.push({{id,tipo:'reg',nome:DATA.regioes[id].nome}});
for(const id in DATA.municipios)IDX.push({{id,tipo:'mun',nome:DATA.municipios[id].nome}});
function norm(s){{return (s||'').normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();}}
const busca=document.getElementById('busca'),resultados=document.getElementById('resultados');
function mostraResultados(){{
  const q=norm(busca.value.trim());
  if(!q){{resultados.style.display='none';return;}}
  const res=IDX.filter(x=>norm(x.nome).includes(q)).sort((a,b)=>{{
    const ai=norm(a.nome).startsWith(q)?0:1,bi=norm(b.nome).startsWith(q)?0:1;
    if(ai!==bi)return ai-bi;
    if(a.tipo!==b.tipo)return a.tipo==='reg'?-1:1;
    return a.nome.localeCompare(b.nome);
  }}).slice(0,14);
  resultados.innerHTML = res.length
    ? res.map(x=>`<div class="r" data-id="${{x.id}}" data-t="${{x.tipo}}"><span>${{x.nome}}</span><span class="tag ${{x.tipo==='mun'?'mun':''}}">${{x.tipo==='reg'?'Região de saúde':'Município'}}</span></div>`).join('')
    : '<div class="r" style="cursor:default;color:#999">Nada encontrado</div>';
  resultados.style.display='block';
}}
busca.addEventListener('input',mostraResultados);
busca.addEventListener('focus',mostraResultados);
resultados.addEventListener('click',e=>{{
  const r=e.target.closest('.r');if(!r||!r.dataset.id)return;
  abrirFicha(r.dataset.t,r.dataset.id);busca.value='';resultados.style.display='none';
}});
document.addEventListener('click',e=>{{if(!e.target.closest('.search-inner'))resultados.style.display='none';}});

// ---- ficha completa (perfil do municipio/regiao) ----
function tile(v,l,u,cls){{return `<div class="tile ${{cls||''}}"><div class="tile-v">${{v}}</div><div class="tile-l">${{l}}</div>${{u?`<div class="tile-u">${{u}}</div>`:''}}</div>`;}}
function topCausas(obj,pop){{
  const cs=Object.entries(obj||{{}}).slice(0,6);
  if(!cs.length)return '<p class="meth">Sem registros.</p>';
  const mx=Math.max(1,...cs.map(c=>c[1][0]));
  return cs.map(([cap,v])=>{{
    const t=v[0],hh=v[1],mm=v[2],den=(hh+mm)||1,r=pop?Math.round(t/pop*100000*10)/10:0;
    return `<div class="tc"><div class="tc-top"><span>${{cap}}</span><b>${{fmtInt(t)}}</b></div>`
      +`<div class="sbar" style="width:${{Math.max(3,Math.round(t/mx*100))}}%">`
      +`<div class="sh" style="width:${{Math.round(hh/den*100)}}%"></div>`
      +`<div class="sm" style="width:${{Math.round(mm/den*100)}}%"></div></div>`
      +`<div class="tc-r">${{fmt(r)}}/100 mil &nbsp;·&nbsp; <span style="color:#1f5fb0">♂${{fmtInt(hh)}}</span> <span style="color:#c0392b">♀${{fmtInt(mm)}}</span></div></div>`;
  }}).join('');
}}
function sinanFicha(d){{
  if(!d.sinan||!DATA.meta.sinan_doencas)return '';
  const grupos={{}};
  for(const slug in DATA.meta.sinan_doencas){{
    const meta=DATA.meta.sinan_doencas[slug];
    (grupos[meta.grupo]=grupos[meta.grupo]||[]).push([slug,meta]);
  }}
  let h='';
  for(const g in grupos){{
    h+=`<div style="font-weight:700;font-size:12px;margin:12px 0 4px;color:#2a4a6b">${{g}}</div>`;
    h+=grupos[g].map(([slug,meta])=>{{
      const a=d.sinan[slug]||[0,0,0];
      const rate=d.populacao?Math.round(a[0]/d.populacao*100000*10)/10:0;
      return `<div class="tc"><div class="tc-top"><span>${{meta.titulo}} <small style="color:#9aa7b3">${{meta.ano}}</small></span><b>${{fmtInt(a[0])}}</b></div>`
        +`<div class="tc-r">${{fmt(rate)}}/100 mil hab. &nbsp;·&nbsp; <span style="color:#1f5fb0">♂${{fmtInt(a[1])}}</span> <span style="color:#c0392b">♀${{fmtInt(a[2])}}</span></div></div>`;
    }}).join('');
  }}
  return h;
}}
function abrirFicha(lvl,id){{
  const d=(lvl==='reg'?DATA.regioes:DATA.municipios)[id];if(!d)return;
  const sub=lvl==='reg'?`Região de saúde · ${{d.macrorregiao}} · ${{d.n_municipios}} municípios`
                       :`Município · Região de saúde ${{NOMES[d.regiao_id]||d.regiao_id}}`;
  const obR=d.populacao?Math.round(d.obitos_total/d.populacao*100000*10)/10:null;
  let h=`<div class="ficha"><div class="ficha-titulo">${{d.nome}}</div><div class="ficha-sub">${{sub}}</div>`;
  if(lvl==='reg'){{
    const muns=Object.entries(DATA.municipios).filter(([mid,md])=>md.regiao_id===id)
      .sort((a,b)=>b[1].populacao-a[1].populacao);
    h+=`<div class="ficha-sec">🗺️ Municípios que compõem a região (${{muns.length}})</div><div class="munlist">`
      +muns.map(([mid,md])=>`<button class="munchip" onclick="abrirFicha('mun','${{mid}}')">${{md.nome}} <small>${{fmtInt(md.populacao)}}</small></button>`).join('')+`</div>`;
  }}
  const pctH=Math.round((100-d.pct_mulheres)*10)/10;
  h+=`<div class="ficha-sec">👥 Demografia — Censo IBGE 2022</div><div class="tiles">`
    +tile(fmtInt(d.populacao),'População','habitantes')
    +tile(fmtInt(d.mulheres)+' · '+fmt(d.pct_mulheres)+'%','Mulheres','','m')
    +tile(fmtInt(d.homens)+' · '+fmt(pctH)+'%','Homens','','h')
    +tile(fmt(d.razao_sexo),'Razão de sexo','homens/100 mulheres')+`</div>`;
  h+=`<div class="sexbar"><div class="sh" style="width:${{pctH}}%"></div><div class="sm" style="width:${{d.pct_mulheres}}%"></div></div>`
    +`<div class="sexbar-lbl"><span style="color:#1f5fb0">♂ Homens ${{fmt(pctH)}}%</span>`
    +`<span style="color:#c0392b">Mulheres ${{fmt(d.pct_mulheres)}}% ♀</span></div>`;
  h+=`<div class="ficha-sec">⚰️ Mortalidade — SIM/SINASC ${{DATA.meta.ano}}</div><div class="tiles">`
    +tile(fmt(d.mortalidade_infantil),'Mortalidade infantil','por 1.000 nascidos')
    +tile(fmt(d.mortalidade_materna),'Mortalidade materna','por 100.000 nascidos')
    +tile(fmtInt(d.obitos_total),'Óbitos (total)',obR!=null?fmt(obR)+' por 100 mil':'')
    +tile(fmtInt(d.nascidos_vivos),'Nascidos vivos','')+`</div>`;
  h+=`<div class="meth" style="margin-top:8px">Óbitos &lt;1 ano: <b>${{fmtInt(d.obitos_infantis)}}</b> · Óbitos maternos: <b>${{fmtInt(d.obitos_maternos)}}</b> (${{fmtInt(d.obitos_maternos_tardios)}} tardias)</div>`;
  h+=`<h4>Principais causas de óbito</h4>`+topCausas(d.causas,d.populacao);
  h+=`<div class="ficha-sec">♀ Saúde da mulher e gênero — ${{DATA.meta.ano}}</div><div class="tiles">`
    +tile(fmt(d.pct_cesarea)+'%','Partos cesáreos','','m')
    +tile(fmt(d.gravidez_adolescencia)+'%','Gravidez na adolescência','mães 10–19 anos','m')
    +tile(fmt(d.prenatal_adequado)+'%','Pré-natal adequado','7+ consultas')
    +tile(fmt(d.baixo_peso)+'%','Baixo peso ao nascer','<2.500g')
    +tile(fmtInt(d.obitos_cancer_mama),'Óbitos câncer de mama',fmt(d.cancer_mama)+'/100 mil mulh.','m')
    +tile(fmtInt(d.obitos_cancer_colo),'Óbitos câncer colo útero',fmt(d.cancer_colo)+'/100 mil mulh.','m')
    +tile(fmtInt(d.obitos_feminicidio),'Homicídios de mulheres',fmt(d.feminicidio)+'/100 mil mulh.','m')+`</div>`
    +`<div class="meth" style="margin-top:6px;font-size:11px">Feminicídio = proxy (óbitos de mulheres por agressão, CID X85–Y09).</div>`;
  if(d.internacoes!=null){{
    h+=`<div class="ficha-sec">🏥 Morbidade hospitalar — SIH ${{DATA.meta.periodo_morb}}</div><div class="tiles">`
      +tile(fmtInt(d.internacoes),'Internações',fmt(d.taxa_internacao)+' por 1.000 hab.')
      +tile(fmtInt(d.internacoes_transmissiveis),'Transmissíveis','infecciosas (Cap. I)')
      +tile(fmtInt(d.obitos_hospitalares),'Óbitos hospitalares','letalidade '+fmt(d.letalidade_hosp)+'%')
      +tile('R$ '+fmtInt(Math.round(d.valor_total)),'Valor SUS pago','')+`</div>`;
    h+=`<h4>Principais causas de internação</h4>`+topCausas(d.causas_internacao,d.populacao);
  }}
  if(d.sinan){{
    h+=`<div class="ficha-sec">🦠 Doenças e agravos (SINAN)</div>`
      +`<div class="meth" style="margin-bottom:2px">Casos notificados de residentes · nº = total no ano · taxa por 100 mil hab. · <span style="color:#1f5fb0">♂ homens</span> <span style="color:#c0392b">♀ mulheres</span>.</div>`
      +sinanFicha(d);
  }}
  h+=`<div class="meth" style="margin-top:14px;font-size:11px">Fontes: IBGE Censo 2022 · DATASUS SIM/SINASC ${{DATA.meta.ano}}${{d.internacoes!=null?' · SIH '+DATA.meta.periodo_morb:''}}${{d.sinan?' · SINAN (vários anos)':''}}.</div></div>`;
  document.getElementById('ficha-conteudo').innerHTML=h;
  document.getElementById('ficha').classList.add('open');
}}
const modalFicha=document.getElementById('ficha');
document.getElementById('fecharFicha').addEventListener('click',()=>modalFicha.classList.remove('open'));
modalFicha.addEventListener('click',e=>{{if(e.target===modalFicha)modalFicha.classList.remove('open');}});
document.addEventListener('keydown',e=>{{if(e.key==='Escape')modalFicha.classList.remove('open');}});

drawMap();refresh();panel(null);
</script></body></html>"""

dst = os.path.join(HERE, "mapa_indicadores_goias.html")
open(dst, "w", encoding="utf-8").write(html)
print("OK ->", dst, "| KB:", round(len(html)/1024))
