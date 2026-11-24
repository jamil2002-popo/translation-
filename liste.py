import asyncio, base64, json, time, requests, edge_tts
U = "https://translate.googleapis.com/translate_a"
noms = requests.get(f"{U}/l", params={"client": "gtx", "hl": "en"}, timeout=30).json()["tl"]
print(len(noms), "langues")
ok = {}
for code in noms:
    try:
        r = requests.post(f"{U}/single", params={"client": "gtx", "sl": "en", "tl": code, "dt": "t"},
                          data={"q": "God loves you. Read chapter 6, verse 14."}, timeout=30)
        r.raise_for_status()
        ok[code] = "".join(x[0] for x in r.json()[0] if x[0])
    except Exception as e:
        ok[code] = None
        print("ECHEC", code, e)
    time.sleep(0.15)
voix = asyncio.run(edge_tts.list_voices())
v = [[x["ShortName"], x["Locale"], x["Gender"]] for x in voix]
data = json.dumps({"noms": noms, "ok": ok, "voix": v}, ensure_ascii=False).encode()
b = base64.b64encode(data).decode()
for i in range(0, len(b), 3000):
    print("DATA", b[i:i+3000])
