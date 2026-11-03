"""Atualiza cotacoes.json com gado (Notícias Agrícolas / Scot / Cepea) e cacau (precodocacau.com.br).

Roda no GitHub Actions (ver .github/workflows/cotacoes.yml). Uso:
  python scripts/atualizar.py            # atualiza cotacoes.json
  python scripts/atualizar.py --dry-run  # só mostra o que faria
"""
import datetime
import json
import re
import sys
import urllib.request

from bs4 import BeautifulSoup

TZ = datetime.timezone(datetime.timedelta(hours=-3))
ARQ = "cotacoes.json"
URL_GADO = "https://www.noticiasagricolas.com.br/cotacoes/boi-gordo"
URL_IBI = "https://precodocacau.com.br/cotacao/cacau-ibirapitanga/"
URL_REG = "https://precodocacau.com.br/cotacao/"
URL_HOME = "https://precodocacau.com.br/"
ESTADOS = ["SP", "MG", "GO", "MS", "BA", "MT", "PR", "PA", "RO", "TO", "AC", "MA", "RJ", "RR", "RS", "SC"]
NUM = r"-?\d{1,3}(?:\.\d{3})*,\d{2}"
log = []


def texto(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (cotacoes-sul-bahia; +https://github.com/leangestao/cotacoes-sul-bahia)"})
    raw = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
    s = BeautifulSoup(raw, "html.parser")
    for t in s(["script", "style", "noscript", "svg"]):
        t.decompose()
    linhas = [l.strip() for l in s.get_text("\n").split("\n")]
    return "\n".join(l for l in linhas if l)


def num(s):
    v = float(s.replace(".", "").replace(",", "."))
    return int(v) if v == int(v) else v


def iso(ddmmaaaa):
    d, m, a = ddmmaaaa.split("/")
    return f"{a}-{m}-{d}"


def var_pct(bloco):
    """Converte '▲ 2,14%' / '▼ 3,18%' / '0,00%' / '+2,14%' em número com sinal."""
    m = re.search(r"([▲▼+\-]?)\s*(\d+,\d+)%", bloco)
    if not m:
        return None
    v = num(m.group(2))
    return -v if m.group(1) in ("▼", "-") else v


# ---------------------------------------------------------------- GADO
def secao(t, titulo):
    """Trecho entre o título da tabela e o 'Atualizado em' seguinte."""
    i = t.find(titulo)
    if i < 0:
        return None, None
    m = re.search(r"Atualizado em:\s*(\d{2}/\d{2}/\d{4})", t[i:])
    if not m:
        return None, None
    return t[i:i + m.start()], iso(m.group(1))


def linha_estado(sec, uf):
    m = re.search(r"\n" + re.escape(uf) + r"\*?\n(" + NUM + r")\n", sec)
    return num(m.group(1)) if m else None


def gado():
    t = texto(URL_GADO)
    out = {}  # data -> campos

    def put(data, k, v):
        if data and v is not None:
            out.setdefault(data, {})[k] = v

    sec, dt = secao(t, "Macho Nelore Reposição - Bezerro (12 M 240 kg 8@)")
    if sec:
        put(dt, "bez_nel_ba", linha_estado(sec, "BA"))
        vals = [linha_estado(sec, uf) for uf in ESTADOS]
        if all(v is not None for v in vals):
            put(dt, "bez_media_br", round(sum(vals) / len(vals), 2))
        else:
            log.append("média BR: faltam estados " + str([u for u, v in zip(ESTADOS, vals) if v is None]))
    sec, dt = secao(t, "Macho Mestiço Reposição - Bezerro (12M 205 Kg 7@)")
    if sec:
        put(dt, "bez_mes_ba", linha_estado(sec, "BA"))
    sec, dt = secao(t, "Macho Nelore Reposição - Desmama (8 M 195 kg 6,5@)")
    if sec:
        put(dt, "desm_nel_ba", linha_estado(sec, "BA"))
    sec, dt = secao(t, "Mercado Físico - Scot Consultoria")
    if sec:
        m = re.search(r"\nBA Sul\n(" + NUM + r")\n", sec)
        put(dt, "boi_ba_sul", num(m.group(1)) if m else None)
    sec, dt = secao(t, "Bezerro Esalq/BM&F Bovespa - MS")
    if sec:
        m = re.search(r"\n(\d{2}/\d{2}/\d{4})\n(" + NUM + r")\n", sec)
        if m:
            put(iso(m.group(1)), "bez_cepea_ms", num(m.group(2)))
    return out


# ---------------------------------------------------------------- CACAU
def hora(t):
    m = re.search(r"Atualizado\s*\n?\s*(?:Hoje|hoje)\s+às\s+(\d{2}:\d{2})", t)
    return m.group(1) if m else None


def cacau():
    a = texto(URL_IBI)
    res = {}
    m = re.search(r"cotado a\s*\n?R\$ (" + NUM + r")\s*\n?\s*por arroba de 15 kg hoje \((\d{2}/\d{2}/\d{4})\)", a)
    if not m:
        raise RuntimeError("cacau: não achei preço/data na página de Ibirapitanga")
    res["data"] = iso(m.group(2))
    res["conv"] = num(m.group(1))
    res["hora"] = hora(a)
    m = re.search(r"\nCertificado\nR\$ (" + NUM + r")", a)
    res["cert"] = num(m.group(1)) if m else None
    hist = {}
    i = a.find("Histórico do cacau")
    for m in re.finditer(r"(\d{2}/\d{2}/\d{4})\nR\$ (" + NUM + r")", a[i:] if i >= 0 else ""):
        hist.setdefault(iso(m.group(1)), num(m.group(2)))
    res["hist"] = hist

    # NY (página inicial)
    try:
        c = texto(URL_HOME)
        m = re.search(r"Cacau NY[\s\S]{0,60}?US\$\s*([\d.]+)", c)
        res["ny"] = int(m.group(1).replace(".", "")) if m else None
    except Exception as e:  # NY é opcional
        log.append(f"NY: {e}")
        res["ny"] = None

    # Cidades (página por região)
    try:
        d = texto(URL_REG)
        hd = hora(d)
        i = d.find("Cacau na Bahia")
        j = d.find("Cacau no Pará", i)
        bloco = d[i:j if j > 0 else None]
        cidades = []
        for m in re.finditer(r"\n([^\n]+)\nmercado físico · Bahia\nR\$ (" + NUM + r")\n([^\n]*%)", bloco):
            cidades.append({"nome": m.group(1), "conv": num(m.group(2)), "var": var_pct(m.group(3))})
        mb = re.search(r"Cacau · Bahia\nCacau ·\nBA\nR\$ ([\d.]+)\n,(\d{2})\n([^\n]*%)", d)
        mc = re.search(r"Certificado ·\nBahia\nBA\nR\$ ([\d.]+)\n,(\d{2})", d)
        if len(cidades) >= 10 and mb:
            res["cidades"] = {
                "data": res["data"], "hora": hd,
                "bahia": num(mb.group(1) + "," + mb.group(2)),
                "bahia_cert": num(mc.group(1) + "," + mc.group(2)) if mc else res["cert"],
                "bahia_var": var_pct(mb.group(3)),
                "fonte": URL_REG, "cidades": cidades,
            }
        else:
            log.append(f"cidades: só {len(cidades)} encontradas / bahia={'ok' if mb else 'não achada'}")
    except Exception as e:
        log.append(f"cidades: {e}")
    return res


# ---------------------------------------------------------------- MESCLA
def main():
    dry = "--dry-run" in sys.argv
    agora = datetime.datetime.now(TZ)
    hoje = agora.strftime("%Y-%m-%d")
    d = json.load(open(ARQ, encoding="utf-8"))
    cot = {c["data"]: c for c in d["cotacoes"]}
    mud = []

    def item(data):
        if data not in cot:
            cot[data] = {"data": data}
            d["cotacoes"].append(cot[data])
        return cot[data]

    def setv(data, k, v):
        if v is None:
            return
        it = item(data)
        if it.get(k) != v:
            mud.append(f"{data} {k}: {it.get(k)} → {v}")
            it[k] = v

    try:
        for data, campos in gado().items():
            for k, v in campos.items():
                setv(data, k, v)
    except Exception as e:
        log.append(f"GADO falhou: {e}")

    try:
        c = cacau()
        print("cacau:", {k: v for k, v in c.items() if k not in ("hist", "cidades")})
        data = c["data"]
        hora_gravada = cot.get(data, {}).get("cacau_hora")
        if data > hoje:
            log.append(f"cacau: data {data} no futuro, ignorada")
        elif hora_gravada and c["hora"] and c["hora"] < hora_gravada:
            log.append(f"cacau: hora {c['hora']} anterior à gravada {hora_gravada}")
        else:
            setv(data, "cacau_ba_conv", c["conv"])
            setv(data, "cacau_ba_cert", c["cert"])
            setv(data, "cacau_hora", c["hora"])
            if data == hoje:
                setv(data, "cacau_ny", c["ny"])
        # fechamento oficial pelo histórico
        for dt in sorted([x for x in c["hist"] if x < data], reverse=True)[:7]:
            it = cot.get(dt)
            if it and "cacau_ba_conv" in it and abs(it["cacau_ba_conv"] - c["hist"][dt]) > 0.01:
                mud.append(f"{dt} fechamento: {it['cacau_ba_conv']} → {c['hist'][dt]}")
                it["cacau_ba_conv"] = c["hist"][dt]
                it.pop("cacau_hora", None)
        novo = c.get("cidades")
        if novo and novo["hora"]:
            velho = d.get("cacau_cidades") or {}
            kn, kv = (novo["data"], novo["hora"]), (velho.get("data", ""), velho.get("hora", ""))
            if kn > kv or (kn == kv and novo != velho):
                mud.append(f"cidades {kv} → {kn}")
                d["cacau_cidades"] = novo
    except Exception as e:
        log.append(f"CACAU falhou: {e}")

    for l in log:
        print("AVISO:", l)
    if not mud:
        print("Nada mudou.")
        return
    print("\n".join(mud))
    if dry:
        return
    d["cotacoes"].sort(key=lambda c: c["data"])
    d["atualizadoEm"] = agora.isoformat(timespec="seconds")
    ordem = ["atualizadoEm", "fontes", "cacau_cidades", "cotacoes"]
    d = {**{k: d[k] for k in ordem if k in d}, **{k: v for k, v in d.items() if k not in ordem}}
    with open(ARQ, "w", encoding="utf-8") as f:
        f.write(json.dumps(d, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
