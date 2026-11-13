# -*- coding: utf-8 -*-
"""
Pipeline reprodutivel — Indicadores de mortalidade de Goias (Fase 1).

Entrada  : Dados/DOGO<ANO>.dbc (SIM, obitos) e Dados/DNGO<ANO>.dbc (SINASC).
Saida    : indicadores_go.json  (indicadores por regiao de saude e por municipio)

Indicadores (definicoes conforme o livro verde IDB/RIPSA 3a ed.):
  - Taxa de mortalidade infantil  (MRT) : obitos <1 ano / nascidos vivos * 1000
  - Razao de mortalidade materna  (MRT) : obitos maternos / nascidos vivos * 100000
  - Mortalidade proporcional por causa (capitulos CID-10)  (MRT)

Fontes: SIM e SINASC (DATASUS); denominadores de nascidos vivos do proprio SINASC.
"""
import os, csv, json, sys
from collections import defaultdict, Counter
from dbfread import DBF

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(HERE, "Dados")
MACRO = os.path.join(HERE, "shapefile_das_regionais_de_saude_sus-master", "macroregiao_de_saude.csv")
ANO = os.environ.get("ANO", "2024")

# ---- capitulos CID-10 (rotulo curto por faixa de codigo) ----
# cada entrada: (letra, ini, fim, rotulo). Codigo ex.: 'I219' -> letra 'I', num 21.
CID_CAP = [
    ("A", 0, 99, "I. Infecciosas e parasitarias"), ("B", 0, 99, "I. Infecciosas e parasitarias"),
    ("C", 0, 99, "II. Neoplasias"), ("D", 0, 48, "II. Neoplasias"),
    ("D", 50, 89, "III. Sangue e imunitarios"),
    ("E", 0, 90, "IV. Endocrinas e metabolicas"),
    ("F", 0, 99, "V. Transtornos mentais"),
    ("G", 0, 99, "VI. Sistema nervoso"),
    ("H", 0, 59, "VII. Olho"), ("H", 60, 95, "VIII. Ouvido"),
    ("I", 0, 99, "IX. Aparelho circulatorio"),
    ("J", 0, 99, "X. Aparelho respiratorio"),
    ("K", 0, 93, "XI. Aparelho digestivo"),
    ("L", 0, 99, "XII. Pele"),
    ("M", 0, 99, "XIII. Osteomuscular"),
    ("N", 0, 99, "XIV. Geniturinario"),
    ("O", 0, 99, "XV. Gravidez, parto e puerperio"),
    ("P", 0, 96, "XVI. Afeccoes perinatais"),
    ("Q", 0, 99, "XVII. Malformacoes congenitas"),
    ("R", 0, 99, "XVIII. Sintomas e sinais mal definidos"),
    ("S", 0, 99, "XIX. Lesoes e envenenamentos"), ("T", 0, 98, "XIX. Lesoes e envenenamentos"),
    ("V", 0, 99, "XX. Causas externas"), ("W", 0, 99, "XX. Causas externas"),
    ("X", 0, 99, "XX. Causas externas"), ("Y", 0, 98, "XX. Causas externas"),
    ("Z", 0, 99, "XXI. Fatores que influenciam a saude"),
    ("U", 0, 99, "XXII. Codigos especiais"),
]

def capitulo_cid(causabas):
    s = str(causabas or "").strip().upper()
    if len(s) < 2 or not s[0].isalpha():
        return "Nao classificado"
    letra = s[0]
    try:
        num = int(s[1:3])
    except ValueError:
        return "Nao classificado"
    for L, ini, fim, rot in CID_CAP:
        if letra == L and ini <= num <= fim:
            return rot
    return "Nao classificado"

def menor_1_ano(idade):
    """IDADE SIM: 1o digito = unidade (0=min,1=hora,2=dia,3=mes,4=ano,5=>100 anos)."""
    s = str(idade or "").zfill(3)
    u, v = s[0], s[1:]
    if u in ("0", "1", "2", "3"):
        return True
    if u == "4" and v == "00":
        return True
    return False

def obito_materno(rec):
    """Morte materna: causa basica no Cap. XV (O00-O99). (definicao simplificada MVP)."""
    return str(rec.get("CAUSABAS") or "")[:1].upper() == "O"

def agressao(cid):
    """Obito por agressao/homicidio (CID-10 X85-Y09)."""
    s = str(cid or "").upper()
    if len(s) < 2 or not s[0].isalpha():
        return False
    try:
        n = int(s[1:3])
    except ValueError:
        return False
    return (s[0] == "X" and 85 <= n <= 99) or (s[0] == "Y" and 0 <= n <= 9)

def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None

# ---- 1) mapeamento municipio (6 digitos) -> regiao de saude + nomes ----
def carrega_regioes():
    muni_reg = {}; reg_nome = {}; reg_macro = {}; muni_nome = {}
    for r in csv.DictReader(open(MACRO, encoding="utf-8"), delimiter=";"):
        if r["sg_uf"] != "GO":
            continue
        cod6 = r["cod_municipio"]
        rid = r["cod_regiao_de_saude"]
        muni_reg[cod6] = rid
        reg_nome[rid] = r["regiao_de_saude"].title()
        reg_macro[rid] = r["macrorregiao_de_saude"].replace("MACRORREGIAO ", "").title()
        muni_nome[cod6] = r["no_municipio"].replace("GO - ", "").strip().title()
    return muni_reg, reg_nome, reg_macro, muni_nome

# ---- 2) agrega contagens por municipio ----
def agrega():
    muni_reg, reg_nome, reg_macro, muni_nome = carrega_regioes()

    # saude da mulher / genero: contadores por municipio
    mulher = defaultdict(lambda: {"cesarea": 0, "adol": 0, "prenatal": 0, "bpeso": 0,
                                  "cmama": 0, "ccolo": 0, "femin": 0})

    nasc = Counter()
    for r in DBF(os.path.join(DADOS, f"DNGO{ANO}.dbf"), encoding="latin-1", load=False):
        m = str(r["CODMUNRES"] or "")
        if m not in muni_reg:
            continue
        nasc[m] += 1
        w = mulher[m]
        if str(r["PARTO"]) == "2":
            w["cesarea"] += 1                 # parto cesareo
        idade = _int(r["IDADEMAE"])
        if idade is not None and 10 <= idade < 20:
            w["adol"] += 1                    # mae adolescente
        if str(r["CONSULTAS"]) == "4":
            w["prenatal"] += 1                # 7+ consultas de pre-natal
        pz = _int(r["PESO"])
        if pz is not None and 0 < pz < 2500:
            w["bpeso"] += 1                   # baixo peso ao nascer

    inf = Counter(); mat = Counter(); mat_tard = Counter(); obt = Counter()
    # municipio -> capitulo -> [total, homens, mulheres]  (SIM: SEXO 1=M, 2=F)
    causa = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    for r in DBF(os.path.join(DADOS, f"DOGO{ANO}.dbf"), encoding="latin-1", load=False):
        m = str(r["CODMUNRES"] or "")
        if m not in muni_reg:
            continue
        obt[m] += 1
        if menor_1_ano(r["IDADE"]):
            inf[m] += 1
        if obito_materno(r):
            mat[m] += 1
            if str(r.get("CAUSABAS") or "")[:3].upper() in ("O96", "O97"):
                mat_tard[m] += 1          # mortes maternas tardias (>42 dias)
        cb = str(r["CAUSABAS"] or "").upper()
        s = str(r["SEXO"])
        if cb[:3] == "C50":
            mulher[m]["cmama"] += 1           # cancer de mama
        elif cb[:3] == "C53":
            mulher[m]["ccolo"] += 1           # cancer do colo do utero
        if agressao(cb) and s == "2":
            mulher[m]["femin"] += 1           # feminicidio (proxy: agressao, sexo fem.)
        arr = causa[m][capitulo_cid(cb)]
        arr[0] += 1
        if s == "1":
            arr[1] += 1
        elif s == "2":
            arr[2] += 1

    return (muni_reg, reg_nome, reg_macro, muni_nome, nasc, inf, mat, mat_tard,
            obt, causa, mulher)

def taxa(n, d, fator):
    return round(n / d * fator, 1) if d else None

def merge_causas(dicts):
    """Soma varios {cap:[t,h,m]} e retorna dict ordenado por total desc."""
    acc = {}
    for dd in dicts:
        for cap, v in dd.items():
            a = acc.setdefault(cap, [0, 0, 0])
            a[0] += v[0]; a[1] += v[1]; a[2] += v[2]
    return {cap: v for cap, v in sorted(acc.items(), key=lambda kv: -kv[1][0])}

def build():
    (muni_reg, reg_nome, reg_macro, muni_nome,
     nasc, inf, mat, mat_tard, obt, causa, mulher) = agrega()

    # ---- demografia (Censo IBGE 2022, por sexo) ----
    from pipeline.demografia import carrega as carrega_sexo
    sexo = carrega_sexo()

    def demo(cod_list):
        h = sum(sexo.get(c, {}).get("homens", 0) for c in cod_list)
        m = sum(sexo.get(c, {}).get("mulheres", 0) for c in cod_list)
        pop = h + m
        return h, m, pop

    def smulher(cods, nv, popM):
        a = {k: 0 for k in ("cesarea", "adol", "prenatal", "bpeso", "cmama", "ccolo", "femin")}
        for c in cods:
            for k in a:
                a[k] += mulher[c][k]
        return {
            "pct_cesarea": taxa(a["cesarea"], nv, 100),
            "gravidez_adolescencia": taxa(a["adol"], nv, 100),
            "prenatal_adequado": taxa(a["prenatal"], nv, 100),
            "baixo_peso": taxa(a["bpeso"], nv, 100),
            "obitos_cancer_mama": a["cmama"], "obitos_cancer_colo": a["ccolo"],
            "obitos_feminicidio": a["femin"],
            "cancer_mama": taxa(a["cmama"], popM, 100000),
            "cancer_colo": taxa(a["ccolo"], popM, 100000),
            "feminicidio": taxa(a["femin"], popM, 100000),
        }

    # ---- municipios ----
    municipios = {}
    for cod6, rid in muni_reg.items():
        nv, oi, om, omt, ot = nasc[cod6], inf[cod6], mat[cod6], mat_tard[cod6], obt[cod6]
        h, m, pop = demo([cod6])
        municipios[cod6] = {
            "nome": muni_nome[cod6], "regiao_id": rid,
            "populacao": pop, "homens": h, "mulheres": m,
            "pct_mulheres": taxa(m, pop, 100), "razao_sexo": taxa(h, m, 100),
            "nascidos_vivos": nv, "obitos_total": ot,
            "obitos_infantis": oi,
            "obitos_maternos": om, "obitos_maternos_tardios": omt,
            "mortalidade_infantil": taxa(oi, nv, 1000),
            "mortalidade_materna": taxa(om, nv, 100000),
            "causas": merge_causas([causa[cod6]]),
        }
        municipios[cod6].update(smulher([cod6], nv, m))

    # ---- regioes (agrega municipios) ----
    regioes = {}
    for rid in sorted(set(muni_reg.values())):
        cods = [c for c, r in muni_reg.items() if r == rid]
        nv = sum(nasc[c] for c in cods); oi = sum(inf[c] for c in cods)
        om = sum(mat[c] for c in cods); omt = sum(mat_tard[c] for c in cods)
        ot = sum(obt[c] for c in cods)
        h, m, pop = demo(cods)
        cc = merge_causas([causa[c] for c in cods])
        regioes[rid] = {
            "nome": reg_nome[rid], "macrorregiao": reg_macro[rid],
            "n_municipios": len(cods),
            "populacao": pop, "homens": h, "mulheres": m,
            "pct_mulheres": taxa(m, pop, 100), "razao_sexo": taxa(h, m, 100),
            "nascidos_vivos": nv, "obitos_total": ot,
            "obitos_infantis": oi,
            "obitos_maternos": om, "obitos_maternos_tardios": omt,
            "mortalidade_infantil": taxa(oi, nv, 1000),
            "mortalidade_materna": taxa(om, nv, 100000),
            "causas": cc,
        }
        regioes[rid].update(smulher(cods, nv, m))

    # ---- metadados dos indicadores (fonte: livro verde IDB/RIPSA 3a ed.) ----
    meta = {
        "ano": ANO,
        "fonte": "DATASUS — SIM (obitos) e SINASC (nascidos vivos)",
        "referencia_metodologica": "Indicadores Basicos para a Saude no Brasil: conceitos e "
                                   "aplicacoes, 3a ed. (OPAS/MS, 2026) — Fichas de Qualificacao (MRT/DEM).",
        "fonte_demografia": "IBGE — Censo Demografico 2022 (populacao residente por sexo, "
                            "via API SIDRA, tabela 9514).",
        "indicadores": {
            "populacao": {
                "titulo": "Populacao residente (Censo 2022)",
                "definicao": "Numero de pessoas residentes, por local de residencia (Censo IBGE 2022).",
                "unidade": "habitantes", "fonte": "IBGE (Censo 2022)", "escala": "seq",
            },
            "razao_sexo": {
                "titulo": "Razao de sexo",
                "definicao": "Numero de homens para cada 100 mulheres (Censo IBGE 2022). "
                             "Valores acima de 100 = predominio masculino; abaixo de 100 = feminino.",
                "unidade": "homens por 100 mulheres", "fonte": "IBGE (Censo 2022)", "escala": "div",
            },
            "mortalidade_infantil": {
                "titulo": "Taxa de mortalidade infantil",
                "definicao": "Obitos de menores de 1 ano por 1.000 nascidos vivos, por local de residencia.",
                "unidade": "por 1.000 nascidos vivos", "fonte": "SIM + SINASC",
            },
            "mortalidade_materna": {
                "titulo": "Razao de mortalidade materna",
                "definicao": "Obitos maternos (causas do Cap. XV da CID-10, O00-O99) por 100.000 "
                             "nascidos vivos, por local de residencia. Inclui as mortes maternas "
                             "TARDIAS (O96/O97, ocorridas mais de 42 dias apos o termino da gestacao), "
                             "que sao contabilizadas e destacadas a parte.",
                "unidade": "por 100.000 nascidos vivos", "fonte": "SIM + SINASC",
                "nota": "Total inclui tardias (O96/O97). A definicao estrita de morte materna "
                        "exclui as tardias.",
            },
            "causas": {
                "titulo": "Obitos por capitulo da CID-10",
                "definicao": "Distribuicao dos obitos segundo o capitulo da causa basica (CID-10).",
                "unidade": "obitos", "fonte": "SIM",
            },
            "cancer_mama": {
                "titulo": "Mortalidade por cancer de mama",
                "definicao": "Obitos por cancer de mama (CID-10 C50) por 100.000 mulheres.",
                "unidade": "por 100.000 mulheres", "fonte": "SIM + IBGE", "escala": "seq", "grupo": "mulher",
            },
            "cancer_colo": {
                "titulo": "Mortalidade por cancer do colo do utero",
                "definicao": "Obitos por cancer do colo do utero (CID-10 C53) por 100.000 mulheres.",
                "unidade": "por 100.000 mulheres", "fonte": "SIM + IBGE", "escala": "seq", "grupo": "mulher",
            },
            "feminicidio": {
                "titulo": "Homicidios de mulheres (proxy de feminicidio)",
                "definicao": "Obitos de mulheres por agressao (CID-10 X85-Y09) por 100.000 mulheres. "
                             "Proxy: nao existe CID especifico de feminicidio.",
                "unidade": "por 100.000 mulheres", "fonte": "SIM + IBGE", "escala": "seq", "grupo": "mulher",
            },
            "pct_cesarea": {
                "titulo": "Proporcao de partos cesareos",
                "definicao": "Percentual de nascidos vivos por parto cesareo (SINASC).",
                "unidade": "% dos partos", "fonte": "SINASC", "escala": "seq", "grupo": "mulher",
            },
            "gravidez_adolescencia": {
                "titulo": "Gravidez na adolescencia",
                "definicao": "Percentual de nascidos vivos de maes de 10 a 19 anos (SINASC).",
                "unidade": "% dos nascidos", "fonte": "SINASC", "escala": "seq", "grupo": "mulher",
            },
            "prenatal_adequado": {
                "titulo": "Pre-natal adequado (7+ consultas)",
                "definicao": "Percentual de nascidos vivos cujas maes fizeram 7 ou mais consultas de "
                             "pre-natal (SINASC). Quanto maior, melhor.",
                "unidade": "% dos nascidos", "fonte": "SINASC", "escala": "seq", "grupo": "mulher",
            },
            "baixo_peso": {
                "titulo": "Baixo peso ao nascer",
                "definicao": "Percentual de nascidos vivos com peso inferior a 2.500g (SINASC).",
                "unidade": "% dos nascidos", "fonte": "SINASC", "escala": "seq", "grupo": "mulher",
            },
        },
    }

    out = {"meta": meta, "regioes": regioes, "municipios": municipios}
    dst = os.path.join(HERE, "indicadores_go.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out, dst

if __name__ == "__main__":
    from pipeline.dbc import dbc_to_dbf
    # garante os .dbf decodificados
    for pref in (f"DOGO{ANO}", f"DNGO{ANO}"):
        dbf = os.path.join(DADOS, pref + ".dbf")
        if not os.path.exists(dbf):
            print("decodificando", pref, "...")
            dbc_to_dbf(os.path.join(DADOS, pref + ".dbc"), dbf)
    out, dst = build()
    print("OK ->", dst)
    print(f"\nMortalidade por regiao de saude — Goias {ANO}")
    print(f"{'Regiao':<20}{'N.viv':>7}{'Ob.inf':>7}{'TMI':>7}{'Ob.mat':>7}{'RMM':>7}")
    for rid, d in sorted(out["regioes"].items(), key=lambda x: -x[1]['nascidos_vivos']):
        print(f"{d['nome'][:19]:<20}{d['nascidos_vivos']:>7}{d['obitos_infantis']:>7}"
              f"{str(d['mortalidade_infantil']):>7}{d['obitos_maternos']:>7}{str(d['mortalidade_materna']):>7}")
