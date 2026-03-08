"""端到端 ASR 链路测试"""
import http.client, json, sys

def post(path, label):
    audio = open(path, "rb").read()
    fname = path.split("/")[-1]
    bd = "----Boundary99"
    header = f"--{bd}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"{fname}\"\r\nContent-Type: audio/webm\r\n\r\n"
    body = header.encode() + audio + f"\r\n--{bd}--\r\n".encode()
    c = http.client.HTTPConnection("localhost", 8002, timeout=60)
    c.request("POST", "/v1/speech/recognize", body=body,
               headers={"Content-Type": f"multipart/form-data; boundary={bd}"})
    r = c.getresponse()
    data = r.read().decode("utf-8", errors="replace")
    c.close()
    if r.status == 200:
        d = json.loads(data)
        print(f"[OK] {label}")
        print(f"     intent={d['intent']}  conf={d['confidence']}  risk={d['risk_level']}")
        print(f"     text=\"{d['raw_text']}\"")
    else:
        print(f"[{r.status}] {label}")
        print(f"     {data[:200]}")
    print()

post("data/collected/CALL_NURSE_002.wav",   "CALL_NURSE   (WebM)")
post("data/collected/EMERGENCY_001.wav",    "EMERGENCY    (WebM)")
post("data/collected/HEALTH_ALERT_001.wav", "HEALTH_ALERT (WebM)")
post("data/samples/CALL_FAMILY_001.wav",    "CALL_FAMILY  (WAV)")
