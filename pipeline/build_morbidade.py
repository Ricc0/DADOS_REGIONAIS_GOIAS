# -*- coding: utf-8 -*-
"""
Pipeline de morbidade hospitalar (SIH/SUS) — Goias. Fase 2a.

Entrada : Dados/RDGO<AAMM>.dbc  (AIH Reduzida; um ou varios meses)
Saida   : morbidade_go.json  (internacoes por regiao de saude e por municipio)

Indicadores:
  - Taxa de internacao hospitalar  (por 1.000 habitantes)
  - Internacoes por capitulo da CID-10 (diagnostico principal)
  - Internacoes por doencas transmissiveis (Cap. I, A00-B99) — em destaque
Denominador populacional: Censo IBGE 2022.
"""
import os, glob, json, re
from collections import defaultdict, Counter
from dbfread import DBF

from pipeline.dbc import dbc_to_dbf
from pipeline.build_indicadores import capitulo_cid, carrega_regioes, merge_causas
from pipeline.demografia import carrega as carrega_sexo

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DADOS = os.path.join(HERE, "Dados")

MESES = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"]

def transmissivel(cid):
    """Doenca transmissivel = Cap. I da CID-10 (A00-B99)."""
    return str(cid or "")[:1].upper() in ("A", "B")

def ensure_dbf():
    arqs = sorted(glob.glob(os.path.join(DADOS, "RDGO*.dbc")))
    dbfs = []
    for dbc in arqs:
        dbf = dbc[:-4] + ".dbf"
        if not os.path.exists(dbf):
            print("decodificando", os.path.basename(dbc), "...")
            dbc_to_dbf(dbc, dbf)
        dbfs.append(dbf)
    return dbfs

def taxa(n, d, fator):
    return round(n / d * fator, 1) if d else None

def build():
    muni_reg, reg_nome, reg_macro, muni_nome = carrega_regioes()
    sexo = carrega_sexo()
    pop = {c: sexo.get(c, {}).get("homens", 0) + sexo.get(c, {}).get("mulheres", 0)
           for c in muni_reg}

    intern = Counter(); transm = Counter(); morte = Counter()
    valor = defaultdict(float)
    # municipio -> capitulo -> [total, homens, mulheres]  (SIH: SEXO 1=M, 3=F)
    causa = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
    meses = set()

    for dbf in ensure_dbf():
        for r in DBF(dbf, encoding="latin-1", load=False):
            m = str(r["MUNIC_RES"] or "")
            if m not in muni_reg:
                continue
            meses.add(f'{r["ANO_CMPT"]}{str(r["MES_CMPT"]).zfill(2)}')
            intern[m] += 1
            cid = str(r["DIAG_PRINC"] or "")
            arr = causa[m][capitulo_cid(cid)]
            arr[0] += 1
            s = str(r["SEXO"])
            if s == "1":
                arr[1] += 1
            elif s == "3":
                arr[2] += 1
            if transmissivel(cid):
                transm[m] += 1
            if str(r["MORTE"]) in ("1", "1.0"):
                morte[m] += 1
            valor[m] += float(r["VAL_TOT"] or 0)

    # periodo legivel
    ms = sorted(meses)
    def lbl(a):
        return f"{MESES[int(a[4:6]) - 1]}/{a[:4]}"
    periodo = lbl(ms[0]) if len(ms) == 1 else f"{lbl(ms[0])}–{lbl(ms[-1])}"
    ano = ms[0][:4] if ms else "?"

    def rec(cods):
        it = sum(intern[c] for c in cods); tr = sum(transm[c] for c in cods)
        mo = sum(morte[c] for c in cods); vl = sum(valor[c] for c in cods)
        pp = sum(pop[c] for c in cods)
        cc = merge_causas([causa[c] for c in cods])
        return {
            "internacoes": it, "internacoes_transmissiveis": tr,
            "obitos_hospitalares": mo, "valor_total": round(vl, 2),
            "populacao": pp,
            "taxa_internacao": taxa(it, pp, 1000),
            "letalidade_hosp": taxa(mo, it, 100),
            "causas_internacao": cc,
        }

    municipios = {}
    for cod6, rid in muni_reg.items():
        d = rec([cod6]); d["nome"] = muni_nome[cod6]; d["regiao_id"] = rid
        municipios[cod6] = d
    regioes = {}
    for rid in sorted(set(muni_reg.values())):
        cods = [c for c, r in muni_reg.items() if r == rid]
        d = rec(cods); d["nome"] = reg_nome[rid]; d["macrorregiao"] = reg_macro[rid]
        d["n_municipios"] = len(cods)
        regioes[rid] = d

    meta = {
        "periodo": periodo, "ano": ano,
        "fonte": "DATASUS — SIH/SUS (AIH Reduzida). Denominador: Censo IBGE 2022.",
        "referencia_metodologica": "Indicadores Basicos para a Saude no Brasil, 3a ed. "
                                   "(OPAS/MS, 2026) — Fichas de Qualificacao (MRB, morbidade hospitalar).",
        "indicadores": {
            "taxa_internacao": {
                "titulo": "Taxa de internação hospitalar (SUS)",
                "definicao": f"Internações hospitalares pagas pelo SUS por 1.000 habitantes, "
                             f"por local de residência (período: {periodo}).",
                "unidade": "por 1.000 hab.", "fonte": "SIH/SUS + IBGE", "escala": "seq",
            },
            "causas_internacao": {
                "titulo": "Internações por capítulo da CID-10",
                "definicao": "Distribuição das internações segundo o capítulo do diagnóstico "
                             "principal (CID-10). Destaque para doenças transmissíveis (Cap. I).",
                "unidade": "internações", "fonte": "SIH/SUS", "escala": "seq",
            },
        },
    }
    out = {"meta": meta, "regioes": regioes, "municipios": municipios}
    dst = os.path.join(HERE, "morbidade_go.json")
    json.dump(out, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out, dst

if __name__ == "__main__":
    out, dst = build()
    print("OK ->", dst, "| periodo:", out["meta"]["periodo"])
    ti = sum(r["internacoes"] for r in out["regioes"].values())
    tt = sum(r["internacoes_transmissiveis"] for r in out["regioes"].values())
    tm = sum(r["obitos_hospitalares"] for r in out["regioes"].values())
    pop = sum(r["populacao"] for r in out["regioes"].values())
    print(f"Internações (GO residentes): {ti} | transmissíveis: {tt} | óbitos hosp.: {tm}")
    print(f"Taxa GO: {round(ti/pop*1000,1)} /1.000 hab (no período)")
    print(f"\n{'Região':<20}{'Intern':>8}{'Taxa':>7}{'Transm':>8}{'Letal%':>8}")
    for rid, d in sorted(out["regioes"].items(), key=lambda x: -x[1]['internacoes']):
        print(f"{d['nome'][:19]:<20}{d['internacoes']:>8}{str(d['taxa_internacao']):>7}"
              f"{d['internacoes_transmissiveis']:>8}{str(d['letalidade_hosp']):>8}")
