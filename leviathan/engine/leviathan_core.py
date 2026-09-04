import requests, json, time, os, re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime
import random

EDGE_URL   = os.environ.get("EDGE_URL",    "http://localhost:8003/v1/chat/completions")
BRAIN_URL  = os.environ.get("BRAIN_URL",   "http://localhost:8004/v1/chat/completions")
MESH_FILE  = os.environ.get("MESH_FILE",   "/app/public/mesh.json")
LOGS_FILE  = os.environ.get("LOGS_FILE",   "/app/public/logs.json")
TRIGGER_FILE = os.environ.get("TRIGGER_FILE", "/app/public/trigger.json")

FEEDS = [
    {"url": "http://feeds.bbci.co.uk/news/world/rss.xml", "pub": "BBC NEWS", "region": "GLOBAL"},
    {"url": "https://www.cbsnews.com/latest/rss/world", "pub": "CBS NEWS", "region": "USA"},
    {"url": "https://www.aljazeera.com/xml/rss/all.xml", "pub": "AL JAZEERA", "region": "MIDDLE EAST"},
    {"url": "https://www.channelnewsasia.com/rssfeed/8395986", "pub": "CNA SINGAPORE", "region": "ASIA"}
]
HEADERS = {'User-Agent': 'Mozilla/5.0'}

def log_terminal(message, severity="info"):
    print(f"[{severity.upper()}] {message}")
    try:
        state = {"logs": []}
        if os.path.exists(LOGS_FILE):
            try: state = json.load(open(LOGS_FILE, 'r'))
            except: pass
        if "logs" not in state: state["logs"] = []
        state["logs"].append({"id": str(time.time()), "timestamp": datetime.now().strftime("%H:%M:%S"), "message": message, "severity": severity})
        state["logs"] = state["logs"][-50:]
        with open(LOGS_FILE, 'w') as f: json.dump(state, f, indent=4)
    except: pass

def extract_text(element): return element.text if element is not None else ""

def fetch_rss(url, region, pub_name):
    articles = []
    try:
        res = requests.get(url, headers=HEADERS, timeout=5)
        items = ET.fromstring(res.content).findall('.//item')[:3] 
        for i in items:
            title = extract_text(i.find('title'))
            desc = extract_text(i.find('description'))
            link = extract_text(i.find('link'))
            author_raw = extract_text(i.find('dc:creator')) or extract_text(i.find('author'))
            author = author_raw if author_raw else f"{pub_name} News Desk"
            
            pubDate_raw = extract_text(i.find('pubDate'))
            formatted_date = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
            if pubDate_raw:
                try: formatted_date = parsedate_to_datetime(pubDate_raw).strftime("%A, %B %d, %Y at %I:%M %p")
                except: pass
            
            articles.append({"src": pub_name, "vec": region, "intel": title, "desc": desc, "link": link, "author": author, "date": formatted_date})
    except: pass
    return articles

def check_topic_alignment(headline_a, headline_b):
    try:
        prompt = f"Headline 1: {headline_a}\nHeadline 2: {headline_b}\nAre these reporting on the exact same event? Answer strictly 'YES' or 'NO'."
        res = requests.post(EDGE_URL, json={"model": "default", "messages": [{"role": "user", "content": prompt}], "max_tokens": 10, "temperature": 0.1}, timeout=10).json()
        return "YES" in res['choices'][0]['message']['content'].strip().upper()
    except: return False

def process_topic_cluster(intel_batch, region):
    try:
        is_multi = len(intel_batch) > 1
        combined_text = "\n".join([f"- {s['intel']}: {s.get('desc', '')}" for s in intel_batch])
        sources = ", ".join(list(set([s['src'] for s in intel_batch])))
        
        if is_multi: edge_prompt = f"Reports from {sources}:\n{combined_text}\n\nTask: Write a single, unbiased, 2-sentence tactical summary of the underlying event."
        else: edge_prompt = f"Raw Intel from {sources}:\n{combined_text}\n\nProvide a concise 2-sentence tactical summary."
            
        edge_res = requests.post(EDGE_URL, json={"model": "default", "messages": [{"role": "user", "content": edge_prompt}], "max_tokens": 100, "temperature": 0.2}, timeout=45).json()
        summary = edge_res['choices'][0]['message']['content'].strip()

        brain_prompt = f"""Global Intel Summary: {summary}
Analyze the global supply chain risk. Does this threaten any international data center, logistics hub, or factory? Name the potentially affected facility and explain the risk in 2 sentences. 
CRITICAL: You MUST end your response with exactly one of these tags indicating the risk level: [RISK: CRITICAL], [RISK: MODERATE], [RISK: LOW], or [RISK: NONE]."""
        
        brain_res = requests.post(BRAIN_URL, json={"model": "default", "messages": [{"role": "user", "content": brain_prompt}], "max_tokens": 150, "temperature": 0.2}, timeout=60).json()
        raw_analysis = brain_res['choices'][0]['message']['content'].strip()

        risk_level = "NONE"
        if "[RISK: CRITICAL]" in raw_analysis.upper(): risk_level = "CRITICAL"
        elif "[RISK: MODERATE]" in raw_analysis.upper(): risk_level = "MODERATE"
        elif "[RISK: LOW]" in raw_analysis.upper(): risk_level = "LOW"
        
        clean_analysis = re.sub(r'\[RISK: .*?\]', '', raw_analysis, flags=re.IGNORECASE).strip()

        primary_art = intel_batch[0]
        return {
            "src": "GLOBAL SYNDICATE" if is_multi else primary_art['src'],
            "vec": region, "intel": f"Cross-Verified: {primary_art['intel']}" if is_multi else primary_art['intel'],
            "sev": "critical" if risk_level == "CRITICAL" else "warning", "summary": summary, "analysis": clean_analysis,
            "date": primary_art.get("date", datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")),
            "author": primary_art.get("author", "Aggregated") if is_multi else primary_art.get("author", f"{primary_art['src']} Staff"),
            "link": primary_art.get("link", "#"), "riskLevel": risk_level
        }
    except Exception as e:
        log_terminal(f"AI Pipeline dropped intel: {e}", "error")
        return None

def collaborative_global_sync(active_mesh):
    log_terminal("INITIATING MULTI-AGENT COLLABORATIVE SYNC...", "warning")
    threats = [s for s in active_mesh if s.get("riskLevel") in ["CRITICAL", "MODERATE", "LOW"]]
    if not threats: return None

    threat_text = "\n".join([f"- [{t['riskLevel']}] {t['src']}: {t['intel']}" for t in threats])
    
    # PASS THE EXACT DATE DOWN TO THE FRONTEND
    sources_list = [{"src": t['src'], "link": t['link'], "intel": t['intel'], "date": t.get('date', 'Live Feed')} for t in threats]

    try:
        prompt_32 = f"Current active world threats:\n{threat_text}\nAs the OSINT Analyst, write a 1-paragraph synthesis of the current global geopolitical stability based ONLY on these reports."
        res_32 = requests.post(EDGE_URL, json={"model": "default", "messages": [{"role": "user", "content": prompt_32}], "max_tokens": 150, "temperature": 0.3}, timeout=60).json()
        geo_state = res_32['choices'][0]['message']['content'].strip()

        prompt_40 = f"""Geopolitical Analyst Report:\n{geo_state}\n\nAs the Supply Chain Architect, respond to this report. Write a 1-paragraph strategic assessment on how these specific conditions are currently impacting our global AI infrastructure network.
CRITICAL: You MUST end your response with exactly one of these tags indicating the OVERALL consensus risk level of the entire global network right now: [GLOBAL_RISK: CRITICAL], [GLOBAL_RISK: MODERATE], [GLOBAL_RISK: LOW], or [GLOBAL_RISK: NONE]."""
        
        res_40 = requests.post(BRAIN_URL, json={"model": "default", "messages": [{"role": "user", "content": prompt_40}], "max_tokens": 150, "temperature": 0.3}, timeout=60).json()
        supply_state_raw = res_40['choices'][0]['message']['content'].strip()

        overall_risk = "LOW"
        if "[GLOBAL_RISK: CRITICAL]" in supply_state_raw.upper(): overall_risk = "CRITICAL"
        elif "[GLOBAL_RISK: MODERATE]" in supply_state_raw.upper(): overall_risk = "MODERATE"
        elif "[GLOBAL_RISK: NONE]" in supply_state_raw.upper(): overall_risk = "NONE"

        clean_supply_state = re.sub(r'\[GLOBAL_RISK: .*?\]', '', supply_state_raw, flags=re.IGNORECASE).strip()

        # CAPTURE THE EXACT TIMESTAMP OF THE EVALUATION
        eval_timestamp = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

        log_terminal(f"MULTI-AGENT SYNC COMPLETE. Global Risk: {overall_risk}", "warning")
        return {
            "timestamp": eval_timestamp,
            "agent32_geopolitics": geo_state,
            "agent40_supply_chain": clean_supply_state,
            "overallRiskLevel": overall_risk,
            "sources": sources_list
        }
    except Exception as e:
        log_terminal(f"Sync Failed: {e}", "error")
        return None

def consume_trigger():
    """Returns True if a pending (unprocessed) trigger exists, and marks it consumed."""
    if not os.path.exists(TRIGGER_FILE):
        return False
    try:
        data = json.load(open(TRIGGER_FILE, 'r'))
        if data.get('processed', True):
            return False
        data['processed'] = True
        with open(TRIGGER_FILE, 'w') as f: json.dump(data, f)
        return True
    except:
        return False

def run_engine():
    print("--- Leviathan Core: IDLE — awaiting trigger ---")
    verified_mesh = []
    seen_intel = set()

    while True:
        if not consume_trigger():
            time.sleep(5)
            continue

        log_terminal("ANALYSIS TRIGGERED — fetching intel feeds...", "warning")

        raw_signals = []
        for feed in FEEDS: raw_signals.extend(fetch_rss(feed["url"], feed["region"], feed["pub"]))
        new_signals = [sig for sig in raw_signals if sig['intel'] not in seen_intel]

        if new_signals:
            topic_clusters = []
            for sig in new_signals[:4]:
                added_to_cluster = False
                for cluster in topic_clusters:
                    if check_topic_alignment(sig['intel'], cluster[0]['intel']):
                        cluster.append(sig)
                        added_to_cluster = True
                        break
                if not added_to_cluster: topic_clusters.append([sig])
                seen_intel.add(sig['intel'])

            for cluster in topic_clusters:
                synthesized_data = process_topic_cluster(cluster, cluster[0]['vec'])
                if synthesized_data: verified_mesh.insert(0, synthesized_data)

        verified_mesh = verified_mesh[:15]

        global_summary = collaborative_global_sync(verified_mesh) if verified_mesh else None

        if verified_mesh:
            state = {"timestamp": datetime.now().strftime("%H:%M:%S"), "mesh_intel": verified_mesh}
            if not global_summary and os.path.exists(MESH_FILE):
                try:
                    old_state = json.load(open(MESH_FILE, "r"))
                    if "global_summary" in old_state: global_summary = old_state["global_summary"]
                except: pass

            if global_summary: state["global_summary"] = global_summary

            try:
                with open(MESH_FILE, "w") as f: json.dump(state, f, indent=4)
                log_terminal(f"MESH UPDATED: {len(verified_mesh)} items active.", "info")
            except: pass

if __name__ == "__main__":
    run_engine()
