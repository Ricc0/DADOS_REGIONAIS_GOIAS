# -*- coding: utf-8 -*-
"""
Pipeline SINAN — doencas transmissiveis e agravos de notificacao (Goias). Fase 2b.

Entrada : Dados/<PREFIXO>BR<AA>.dbc  (arquivos nacionais do SINAN; filtramos GO)
Saida   : sinan_go.json  (casos por regiao/municipio, por sexo, por agravo)

Incidencia = casos (residentes de GO) / populacao (Censo 2022) x 100.000.
Cacheia o agregado de cada arquivo em Dados/cache_sinan_<arquivo>.json
(re-execucoes ficam rapidas; os nacionais sao grandes).
"""
import os, glob, json, time
from collections import defaultdict, Counter
from dbfread import DBF, FieldParser

from pipeline.dbc import dbc_to_dbf
from pipeline.build_indicadores import carrega_regioes

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(HERE, "Dados")

# prefixo (4 letras) -> (slug, titulo, grupo, single_sex)
AGRAVOS = {
    "DENG": ("dengue", "Dengue", "Arboviroses", None),
    "ZIKA": ("zika", "Zika", "Arboviroses", None),
    "CHIK": ("chik", "Chikungunya", "Arboviroses", None),
    "HANS": ("hanseniase", "Hanseníase", "Micobacterioses", None),
    "TUBE": ("tuberculose", "Tuberculose", "Micobacterioses", None),
    "SIFA": ("sifilis_adq", "Sífilis adquirida", "IST / HIV", None),
    "SIFG": ("sifilis_gest", "Sífilis em gestante", "IST / HIV", "F"),
    "SIFC": ("sifilis_cong", "Sífilis congênita", "IST / HIV", None),
    "HIVA": ("hiv_aids", "HIV / AIDS", "IST / HIV", None),
    "HIVG": ("hiv_gest", "HIV em gestante", "IST / HIV", "F"),
    "HIVE": ("hiv_exp", "HIV - exposição", "IST / HIV", None),
    "VIOL": ("violencia", "Violência interpessoal/autoprovocada", "Violência", None),
    "MENT": ("mental", "Transtorno mental (trabalho)", "Outros", None),
}

class Safe(FieldParser):
    def parseD(self, field, data):
        try: return super().parseD(field, data)
        except Exception: return None
    def parseN(self, field, data):
        try: return super().parseN(field, data)
        except Exception: return None

def ano_do_arquivo(base):
    d = base[-2:]
    return ("20" + d) if d.isdigit() else "?"

def processa_arquivo(dbc, muni_reg):
    """Retorna {'ano':..., 'mun':{cod6:[t,h,m]}} para residentes de GO (com cache)."""
    base = os.path.basename(dbc)[:-4]
    cache = os.path.join(DADOS, f"cache_sinan_{base}.json")
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(dbc):
        return json.load(open(cache, encoding="utf-8"))

    dbf = dbc[:-4] + ".dbf"
    if not os.path.exists(dbf) or os.path.getmtime(dbf) < os.path.getmtime(dbc):
        dbc_to_dbf(dbc, dbf)

    mun = defaultdict(lambda: [0, 0, 0])
    anos = Counter()
    for r in DBF(dbf, encoding="latin-1", load=False, parserclass=Safe):
        m = str(r.get("ID_MN_RESI") or "")
        if m not in muni_reg:
            continue
        anos[str(r.get("NU_ANO") or "")] += 1
        arr = mun[m]; arr[0] += 1
        s = str(r.get("CS_SEXO") or "")
        if s == "M": arr[1] += 1
        elif s == "F": arr[2] += 1
    ano = anos.most_common(1)[0][0] if anos else ano_do_arquivo(base)
    out = {"ano": ano, "mun": mun}
    json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return out

# tipos de violencia e relacao com agressor derivados da ficha VIOL (gênero)
VIOL_EXTRA = {
    "viol_sexual": ("Violência sexual", lambda r: str(r.get("VIOL_SEXU")) == "1"),
    "viol_fisica": ("Violência física", lambda r: str(r.get("VIOL_FISIC")) == "1"),
    "viol_psico": ("Violência psicológica", lambda r: str(r.get("VIOL_PSICO")) == "1"),
    "viol_parceiro": ("Violência por parceiro íntimo", lambda r: any(
        str(r.get(f)) == "1" for f in ("REL_CONJ", "REL_EXCON", "REL_NAMO", "REL_EXNAM"))),
    "viol_autoprov": ("Violência autoprovocada (autolesão)", lambda r: (
        str(r.get("REL_PROPRI")) == "1" or str(r.get("LES_AUTOP")) == "1")),
}

def processa_violencia(dbc, muni_reg):
    """VIOL: alem do total, gera recortes de tipo/relacao por municipio e sexo (com cache)."""
    base = os.path.basename(dbc)[:-4]
    cache = os.path.join(DADOS, f"cache_violrich_{base}.json")
    if os.path.exists(cache) and os.path.getmtime(cache) >= os.path.getmtime(dbc):
        return json.load(open(cache, encoding="utf-8"))
    dbf = dbc[:-4] + ".dbf"
    if not os.path.exists(dbf):
        dbc_to_dbf(dbc, dbf)
    slugs = ["violencia"] + list(VIOL_EXTRA)
    ag = {s: defaultdict(lambda: [0, 0, 0]) for s in slugs}
    anos = Counter()
    for r in DBF(dbf, encoding="latin-1", load=False, parserclass=Safe):
        m = str(r.get("ID_MN_RESI") or "")
        if m not in muni_reg:
            continue
        anos[str(r.get("NU_ANO") or "")] += 1
        s = str(r.get("CS_SEXO") or "")
        idx = 1 if s == "M" else (2 if s == "F" else None)
        def add(slug):
            arr = ag[slug][m]; arr[0] += 1
            if idx: arr[idx] += 1
        add("violencia")
        for slug, (_, cond) in VIOL_EXTRA.items():
            if cond(r):
                add(slug)
    ano = anos.most_common(1)[0][0] if anos else ano_do_arquivo(base)
    out = {"ano": ano, "agravos": {s: ag[s] for s in slugs}}
    json.dump(out, open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    return out

def build():
    muni_reg, reg_nome, reg_macro, muni_nome = carrega_regioes()

    # descobre arquivos SINAN presentes
    arquivos = {}
    for dbc in sorted(glob.glob(os.path.join(DADOS, "*.dbc"))):
        pref = os.path.basename(dbc)[:4].upper()
        if pref in AGRAVOS:
            arquivos[pref] = dbc

    doencas = {}          # slug -> meta
    dados_mun = defaultdict(dict)   # cod6 -> {slug:[t,h,m]}
    for pref, dbc in arquivos.items():
        slug, titulo, grupo, single = AGRAVOS[pref]
        t0 = time.time()
        if pref == "VIOL":
            res = processa_violencia(dbc, muni_reg)
            tits = {"violencia": "Violência (total)"}
            tits.update({k: v[0] for k, v in VIOL_EXTRA.items()})
            for sl, munmap in res["agravos"].items():
                doencas[sl] = {"titulo": tits[sl], "grupo": "Violência", "ano": res["ano"],
                               "escala": "seq", "single_sex": None}
                for cod6, arr in munmap.items():
                    dados_mun[cod6][sl] = arr
            tv = sum(v[0] for v in res["agravos"]["violencia"].values())
            print(f"  Violência: {tv} casos GO ({res['ano']}) + {len(VIOL_EXTRA)} recortes [{time.time()-t0:.0f}s]")
            continue
        res = processa_arquivo(dbc, muni_reg)
        casos = sum(v[0] for v in res["mun"].values())
        print(f"  {titulo}: {casos} casos GO ({res['ano']}) [{time.time()-t0:.0f}s]")
        doencas[slug] = {"titulo": titulo, "grupo": grupo, "ano": res["ano"],
                         "escala": "seq", "single_sex": single}
        for cod6, arr in res["mun"].items():
            dados_mun[cod6][slug] = arr

    def vazio(): return [0, 0, 0]
    # ---- municipios ----
    municipios = {}
    for cod6, rid in muni_reg.items():
        municipios[cod6] = {slug: dados_mun.get(cod6, {}).get(slug, vazio()) for slug in doencas}
    # ---- regioes ----
    regioes = {}
    for rid in sorted(set(muni_reg.values())):
        cods = [c for c, r in muni_reg.items() if r == rid]
        agg = {}
        for slug in doencas:
            t = h = m = 0
            for c in cods:
                v = dados_mun.get(c, {}).get(slug)
                if v: t += v[0]; h += v[1]; m += v[2]
            agg[slug] = [t, h, m]
        regioes[rid] = agg

    meta = {
        "fonte": "DATASUS — SINAN (agravos de notificação). Denominador: Censo IBGE 2022.",
        "referencia_metodologica": "Indicadores Basicos para a Saude no Brasil, 3a ed. (OPAS/MS, 2026) — MRB.",
        "doencas": doencas,
    }
    out = {"meta": meta, "regioes": regioes, "municipios": municipios}
    dst = os.path.join(HERE, "sinan_go.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out, dst

if __name__ == "__main__":
    print("Processando SINAN (arquivos grandes na 1a vez podem demorar)...")
    out, dst = build()
    print("OK ->", dst)
    print("Agravos:", ", ".join(d["titulo"] for d in out["meta"]["doencas"].values()))
