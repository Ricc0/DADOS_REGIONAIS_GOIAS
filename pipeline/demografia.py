# -*- coding: utf-8 -*-
"""
Dados demograficos (Censo IBGE 2022) por municipio de Goias — populacao por sexo.

Fonte: IBGE / API SIDRA, tabela 9514 (populacao residente por sexo).
Cacheia em Dados/censo2022_sexo_go.json (chave = codigo municipio 6 digitos).
"""
import os, json, urllib.request, socket

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(HERE, "Dados", "censo2022_sexo_go.json")
URL = ("https://apisidra.ibge.gov.br/values/t/9514/n6/in%20n3%2052/v/93/p/2022"
       "/c2/allxt/c287/100362/c286/113635")

def _fetch():
    socket.setdefaulttimeout(120)
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req).read().decode("utf-8", "ignore"))
    out = {}
    for r in data[1:]:
        cod6 = r["D1C"][:6]
        d = out.setdefault(cod6, {"homens": 0, "mulheres": 0})
        if r["D4N"] == "Homens":
            d["homens"] = int(r["V"])
        elif r["D4N"] == "Mulheres":
            d["mulheres"] = int(r["V"])
    return out

def carrega(force=False):
    """Retorna {cod6: {homens, mulheres}}. Usa cache se existir."""
    if os.path.exists(CACHE) and not force:
        return json.load(open(CACHE, encoding="utf-8"))
    dados = _fetch()
    json.dump(dados, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return dados

if __name__ == "__main__":
    d = carrega(force=True)
    th = sum(v["homens"] for v in d.values())
    tm = sum(v["mulheres"] for v in d.values())
    print(f"OK -> {CACHE}")
    print(f"municipios: {len(d)} | Homens: {th} | Mulheres: {tm} | Total: {th+tm}")
