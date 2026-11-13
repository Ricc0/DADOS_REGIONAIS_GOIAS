# -*- coding: utf-8 -*-
"""
Decodificador de arquivos .dbc do DATASUS (puro-Python, sem dependencias).

Um .dbc e um arquivo .dbf cujo bloco de registros foi comprimido com o
algoritmo PKWare DCL ("implode"). Aqui reimplementamos o "blast"
(descompressao DCL, port do blast.c da zlib) e reconstruimos o .dbf.

Uso:
    from pipeline.dbc import dbc_to_dbf
    dbc_to_dbf("Dados/DOGO2024.dbc", "Dados/DOGO2024.dbf")
"""

MAXBITS = 13

# Representacoes compactas das tabelas de Huffman (do blast.c):
# cada byte = (n_simbolos-1)<<4 | comprimento_em_bits
_LITLEN = bytes([
    11,124,8,7,28,7,188,13,76,4,10,8,12,10,12,10,8,23,8,9,7,6,7,8,7,6,55,8,
    23,24,12,11,7,9,11,12,6,7,22,5,7,24,6,11,9,6,7,22,7,11,38,7,9,8,25,11,8,
    11,9,12,8,12,5,38,5,38,5,11,7,5,6,21,6,10,53,8,7,24,10,27,44,253,253,253,
    252,252,252,13,12,45,12,45,12,61,12,45,44,173])
_LENLEN = bytes([2,35,36,53,38,23])
_DISTLEN = bytes([2,20,53,230,247,151,248])

_BASE = [3,2,4,5,6,7,8,9,10,12,16,24,40,72,136,264]
_EXTRA = [0,0,0,0,0,0,0,0,1,2,3,4,5,6,7,8]


def _construct(rep):
    """Constroi (count, symbol) a partir da representacao compacta."""
    length = []
    for b in rep:
        n = (b >> 4) + 1
        bitlen = b & 15
        length.extend([bitlen] * n)
    nsym = len(length)
    count = [0] * (MAXBITS + 1)
    for l in length:
        count[l] += 1
    offs = [0] * (MAXBITS + 2)
    offs[1] = 0
    for l in range(1, MAXBITS):
        offs[l + 1] = offs[l] + count[l]
    symbol = [0] * nsym
    for s in range(nsym):
        if length[s] != 0:
            symbol[offs[length[s]]] = s
            offs[length[s]] += 1
    return count, symbol


_LITCODE = _construct(_LITLEN)
_LENCODE = _construct(_LENLEN)
_DISTCODE = _construct(_DISTLEN)


class _Blast:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.bitbuf = 0
        self.bitcnt = 0
        self.out = bytearray()

    def bits(self, need):
        val = self.bitbuf
        while self.bitcnt < need:
            val |= self.data[self.pos] << self.bitcnt
            self.pos += 1
            self.bitcnt += 8
        self.bitbuf = val >> need
        self.bitcnt -= need
        return val & ((1 << need) - 1)

    def decode(self, code_table):
        count, symbol = code_table
        code = first = index = 0
        length = 1
        ci = 1
        bitbuf = self.bitbuf
        left = self.bitcnt
        while True:
            while left > 0:
                left -= 1
                code |= (bitbuf & 1) ^ 1   # bit invertido (DCL)
                bitbuf >>= 1
                c = count[ci]
                ci += 1
                if code < first + c:
                    self.bitbuf = bitbuf
                    self.bitcnt = (self.bitcnt - length) & 7
                    return symbol[index + (code - first)]
                index += c
                first += c
                first <<= 1
                code <<= 1
                length += 1
                if length > MAXBITS:
                    raise ValueError("codigo Huffman invalido no .dbc")
            # recarrega um byte
            left = (MAXBITS + 1) - length
            if left <= 0:
                raise ValueError("estouro de codigo no .dbc")
            bitbuf = self.data[self.pos]
            self.pos += 1
            if left > 8:
                left = 8

    def run(self):
        lit = self.bits(8)
        if lit > 1:
            raise ValueError("flag de literal invalida")
        dict_bits = self.bits(8)
        if dict_bits < 4 or dict_bits > 6:
            raise ValueError("tamanho de dicionario invalido")
        out = self.out
        while True:
            if self.bits(1):
                # par comprimento+distancia
                sym = self.decode(_LENCODE)
                length = _BASE[sym] + self.bits(_EXTRA[sym])
                if length == 519:   # codigo de fim
                    break
                sbits = 2 if length == 2 else dict_bits
                dist = (self.decode(_DISTCODE) << sbits) + self.bits(sbits) + 1
                start = len(out) - dist
                if start < 0:
                    raise ValueError("distancia invalida no .dbc")
                for i in range(length):
                    out.append(out[start + i])
            else:
                # literal
                sym = self.decode(_LITCODE) if lit else self.bits(8)
                out.append(sym)
        return out


def blast(compressed):
    """Descomprime um bloco PKWare DCL, retornando bytearray."""
    return _Blast(bytes(compressed)).run()


def dbc_to_dbf(dbc_path, dbf_path=None):
    """Converte .dbc -> .dbf. Se dbf_path for None, retorna os bytes."""
    raw = open(dbc_path, "rb").read()
    header_size = raw[8] | (raw[9] << 8)
    record_size = raw[10] | (raw[11] << 8)
    n_records = raw[4] | (raw[5] << 8) | (raw[6] << 16) | (raw[7] << 24)
    expected = n_records * record_size
    out = bytearray(raw[:header_size])       # cabecalho DBF + descritores + 0x0D

    # o bloco comprimido comeca alguns bytes apos o cabecalho (o DATASUS insere
    # alguns bytes de controle). Localiza o primeiro inicio DCL valido:
    # byte de literal em {0,1} e byte de dicionario em {4,5,6}, validando pelo
    # tamanho descomprimido esperado.
    body = None
    for skip in range(0, 9):
        off = header_size + skip
        if raw[off] <= 1 and 4 <= raw[off + 1] <= 6:
            try:
                cand = blast(raw[off:])
            except ValueError:
                continue
            if len(cand) >= expected:
                body = cand
                break
    if body is None:
        raise ValueError("nao foi possivel localizar o bloco comprimido do .dbc")
    out += body[:expected]                     # garante tamanho exato dos registros
    out += b"\x1a"                             # marcador de fim de DBF
    if dbf_path:
        open(dbf_path, "wb").write(out)
        return dbf_path
    return bytes(out)


if __name__ == "__main__":
    import sys
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src[:-4] + ".dbf"
    dbc_to_dbf(src, dst)
    print("OK ->", dst)
