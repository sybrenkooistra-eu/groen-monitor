"""
Groen Politieke Monitor
Wekelijks script dat de 7 belangrijkste politieke dossiers in België/Vlaanderen
opzoekt en analyseert of/hoe Groen hierop zichtbaar was.
Stuurt een email-rapport op maandagochtend.
"""

import os
import smtplib
import time
import re
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parsedate_to_datetime

import anthropic

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
EMAIL_FROM    = os.environ["EMAIL_FROM"]
EMAIL_TO      = os.environ["EMAIL_TO"]
SMTP_HOST     = os.environ["SMTP_HOST"]
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]


# ── Google News RSS ───────────────────────────────────────────────────────────

# Zoekqueries voor Google News — when:7d beperkt tot afgelopen week
# Bewust breed en thematisch gehouden — geen specifieke dossiers invullen vooraf
GOOGLE_NEWS_QUERIES = [
    # Breed Belgisch politiek nieuws
    "België politiek when:7d",
    "Vlaamse regering when:7d",
    "federale regering when:7d",
    "Kamer parlement when:7d",
    "Vlaams Parlement when:7d",
    # Generieke politieke termen
    "Wetstraat when:7d",
    "minister België when:7d",
    "staatssecretaris België when:7d",
    "oppositie coalitie België when:7d",
    # Politieke namen — federaal
    "De Wever when:7d",
    "Verlinden when:7d",
    "Rousseau when:7d",
    "Bouchez when:7d",
    "Van Peteghem when:7d",
    "Theo Francken when:7d",
    # Politieke namen — Vlaams
    "Weyts when:7d",
    "Brouns when:7d",
    "Gennez when:7d",
    "Zuhal Demir when:7d",
    # Groen
    "Aimen Horch when:7d",
    "Groen partij when:7d",
    "Van Hecke Groen when:7d",
    "Bogdan Vanden Berghe when:7d",
    "Nadia Naji when:7d",
    "Meyrem Almaci when:7d",
    # PVDA
    "Hedebouw when:7d",
    "Aouariri when:7d",
    "PVDA when:7d",
    # Vlaams Belang
    "Van Grieken when:7d",
    "Vlaams Belang when:7d",
    # Sociale en economische thema's — breed
    "besparing sociale maatregel België when:7d",
    "fiscaliteit belastingen België when:7d",
    "openbaar vervoer mobiliteit Vlaanderen when:7d",
    # Eco-populistisch radarscherm — structureel
    "vermogen rijken belastingen België when:7d",
    "fiscaal voordeel subsidie bedrijven België when:7d",
    # Progressief radarscherm
    "Palestina België politiek when:7d",
    "LGBT rechten België when:7d",
    "rechtsstaat democratie België when:7d",
    "extreemrechts Vlaams Belang when:7d",
    "racisme discriminatie België when:7d",
    "asiel migratie mensenrechten België when:7d",
    "hittegolf België when:7d",
    "klimaat België when:7d",
    "klimaatbeleid Vlaanderen when:7d",
    "PFAS vervuiling België when:7d",
    "milieu luchtkwaliteit water België when:7d",
]

BASE_RSS = "https://news.google.com/rss/search?q={query}&hl=nl&gl=BE&ceid=BE:nl"


def fetch_google_news(query: str) -> list[dict]:
    """Haalt artikelen op via Google News RSS voor een specifieke query."""
    articles = []
    try:
        encoded = urllib.parse.quote(query)
        url = BASE_RSS.format(query=encoded)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
        for item in root.findall(".//item"):
            title   = item.findtext("title", "").strip()
            desc    = item.findtext("description", "").strip()
            link    = item.findtext("link", "").strip()
            pubdate = item.findtext("pubDate", "").strip()
            source_el = item.find("source")
            source = source_el.text if source_el is not None else ""
            if title and link:
                articles.append({
                    "title":  title,
                    "body":   re.sub(r'<[^>]+>', '', desc)[:500],  # HTML strippen
                    "url":    link,
                    "date":   pubdate,
                    "source": source,
                })
    except Exception as e:
        print(f"Google News fout voor '{query}': {e}")
    return articles


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def get_date_range() -> tuple[str, str]:
    today = datetime.today()
    last_monday = today - timedelta(days=today.weekday() + 7)
    last_sunday  = last_monday + timedelta(days=6)
    return last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d")


def count_article_frequency(articles: list[dict]) -> list[dict]:
    """Scoort artikelen op basis van hoe vaak gelijkaardige onderwerpen terugkomen."""
    stopwords = {"de", "het", "een", "van", "in", "op", "en", "voor", "dat", "is",
                 "met", "te", "aan", "er", "ook", "maar", "om", "niet", "zijn", "dit",
                 "bij", "over", "als", "wordt", "heeft", "na", "door", "nog", "al",
                 "naar", "uit", "die", "ze", "we", "hij", "haar", "hun"}

    def tokenize(text):
        return [w.lower() for w in re.findall(r'\b\w{4,}\b', text) if w.lower() not in stopwords]

    all_words = []
    for a in articles:
        all_words.extend(tokenize(a["title"]))
    word_freq = Counter(all_words)

    for a in articles:
        a["_score"] = sum(word_freq[w] for w in tokenize(a["title"]))

    return sorted(articles, key=lambda x: x["_score"], reverse=True)


# ── Nieuwsverzameling ─────────────────────────────────────────────────────────

def gather_raw_news() -> str:
    """Verzamelt nieuws via Google News RSS (recente artikelen, afgelopen week)."""
    date_from, date_to = get_date_range()
    week_label = f"{date_from} t/m {date_to}"
    print(f"Nieuws verzamelen voor week {week_label}...")

    all_articles = []
    seen_urls = set()

    for query in GOOGLE_NEWS_QUERIES:
        articles = fetch_google_news(query)
        for article in articles:
            if article["url"] in seen_urls:
                continue
            seen_urls.add(article["url"])
            all_articles.append(article)
        print(f"  '{query}': {len(articles)} artikelen")
        time.sleep(1)  # Beleefd wachten

    print(f"Totaal: {len(all_articles)} unieke artikelen.")

    ranked = count_article_frequency(all_articles)
    top10  = ranked[:10]
    rest   = ranked[10:]

    news_text = f"NIEUWSOVERZICHT WEEK {week_label}\n\n"
    news_text += "=== TOP 10 MEEST GECITEERDE ONDERWERPEN ===\n\n"
    for i, a in enumerate(top10, 1):
        news_text += (
            f"[TOP {i}] {a['date']} | {a['source']}\n"
            f"TITEL: {a['title']}\n"
            f"INHOUD: {a['body']}\n"
            f"URL: {a['url']}\n\n"
        )

    news_text += "=== OVERIGE BERICHTEN ===\n\n"
    for i, a in enumerate(rest, 1):
        news_text += (
            f"[{i}] {a['date']} | {a['source']}\n"
            f"TITEL: {a['title']}\n"
            f"INHOUD: {a['body'][:250]}\n"
            f"URL: {a['url']}\n\n"
        )

    with open("debug_nieuws.txt", "w") as f:
        f.write(news_text)
    print("📄 debug_nieuws.txt opgeslagen.")
    return news_text


# ── Prompts ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Je bent een politiek analist voor Groen, de Vlaamse groene partij.
Je taak: analyseer wekelijks nieuws en lever een gestructureerd rapport af in HTML.

── SELECTIECRITERIA VOOR DOSSIERS ──────────────────────────────────────────
Een dossier is politiek-maatschappelijk relevant als minstens één van deze criteria geldt:
1. PARLEMENTAIR GEWICHT: debat in Kamer of Vlaams Parlement, parlementaire vragen, stemming
2. REGERINGSBESLISSING: concrete maatregel, beleidswijziging of budgettaire keuze
3. MAATSCHAPPELIJKE IMPACT: raakt aantoonbaar het dagelijks leven van grote groepen mensen
4. COALITIEDYNAMIEK: spanningen, breuken of onverwachte posities binnen de regeringscoalitie
5. PUBLIEK DEBAT: breed opgepikt in meerdere media, maatschappelijke verontwaardiging

Niet relevant: uitspraken zonder beleidsconsequentie, puur partijpolitiek geprofileer,
buitenlands nieuws zonder directe Belgische impact, lokale feiten-diversa.

Rangschik de 7 dossiers op politiek-maatschappelijk gewicht, zwaarste eerst.
Vermeld per dossier kort waarom het relevant is (welk criterium).

── GROEN-ZICHTBAARHEID ──────────────────────────────────────────────────────
- De partijleider van Groen is Aimen Horch — primaire referentie
- Andere Groen-politici (Van Hecke, Buyst, Vanden Berghe, e.a.) zijn secundair
- Groen reageert geregeld maar haalt soms minder media dan grotere partijen
- Vier niveaus:
  * 🟢 Prominent: Groen domineert of co-domineert het debat
  * 🟡 Zichtbaar: substantiële reactie, opgepikt in meerdere media
  * 🟠 Enigszins: één medium of een korte quote
  * 🔴 Niet zichtbaar: geen traceerbare Groen-reactie
- Wees concreet: wie zei wat, in welk medium
- Bij 🟠 of 🔴: geef aan of het een strategische kans was en waarom

── RADARSCHERM 1: ECO-POPULISTISCH ─────────────────────────────────────────
Speelde er een dossier over: vermogen van de rijken, fiscale privileges, bedrijfssubsidies,
belastingontwijking via vennootschappen of Luxemburg-constructies, of de tegenstelling
tussen besparingen op gewone mensen en voordelen voor vermogende families/bedrijven?
→ Speelde dit: ja/nee + concrete inhoud
→ Groen-zichtbaarheid (zelfde vier niveaus)
→ Zo niet zichtbaar: hoe had Groen dit kunnen claimen?

── RADARSCHERM 2: KLIMAAT & MILIEU ──────────────────────────────────────────
Speelde er een klimaat- of milieugerelateerd dossier? Denk aan: recordtemperaturen,
hittegolven, overstromingen, droogte, vertraging van klimaatbeleid, besparingen op
renovatiesteun of energietransitie, PFAS-vervuiling, luchtkwaliteit, watervervuiling,
of andere milieuschandalen met gezondheidsimpact.
LET OP: hitte en extreme temperaturen zijn ALTIJD een klimaatdossier, ook als het
nieuws het woord "klimaat" niet expliciet gebruikt.
→ Speelde dit: ja/nee + concrete inhoud
→ Claimde Groen de oplossingsruimte, bleef het reactief, of was het afwezig?
→ Zichtbaarheidsniveau (zelfde vier niveaus)
→ Zo niet zichtbaar: gemiste kans of terecht geen prioriteit?

── RADARSCHERM 3: PROGRESSIEF ───────────────────────────────────────────────
Speelde er een cultureel-progressief dossier? Denk aan: Palestina/buitenlands beleid
met mensenrechtendimensie, LGBTQ+-rechten, bedreigingen van de rechtsstaat of democratie,
anti-extreem-rechts, racisme en discriminatie, asiel en migratie vanuit mensenrechtenperspectief,
persvrijheid, academische vrijheid.
→ Speelde dit: ja/nee + concrete inhoud
→ Groen-zichtbaarheid (zelfde vier niveaus) — dit is traditioneel Groen-terrein
→ Zo niet zichtbaar: gemiste kans of terecht geen prioriteit?

- Schrijf in het Nederlands
- Output: alleen HTML (geen markdown, geen uitleg errond)
- VERPLICHT: het rapport bevat altijd exact zes onderdelen:
  (1) koptekst, (2) zeven dossiers met bronlinks, (3) radarscherm eco-populistisch,
  (4) radarscherm klimaat & milieu, (5) radarscherm progressief, (6) strategische slotnotitie.
  Alle drie de radarschermen zijn ALTIJD aanwezig, ook als er geen relevant dossier speelde."""

ANALYSIS_PROMPT = """Analyseer onderstaand nieuwsoverzicht en genereer een volledig HTML email-rapport.

De nieuwsdata is opgedeeld in:
- TOP 10: de meest geciteerde onderwerpen van de week — ankerpunten voor je analyse
- OVERIGE BERICHTEN: achtergrondsignaal voor context en radarschermen

Het rapport bevat ALTIJD exact deze vijf onderdelen:

1. Koptekst met weekdatum

2. Zeven politieke dossiers (zwaarste eerst), elk met:
   - Titel
   - Relevant criterium (parlementair gewicht / regeringsbeslissing / maatschappelijke impact / coalitiedynamiek / publiek debat)
   - Samenvatting (2-3 zinnen)
   - Bronlink: <a href="URL" style="color:#3d8c40">Bron →</a>
   - Groen-zichtbaarheid: wie, welke lijn, welk medium
   - Kleurcode: 🟢 prominent | 🟡 zichtbaar | 🟠 enigszins | 🔴 niet zichtbaar

3. RADARSCHERM ECO-POPULISTISCH (ALTIJD aanwezig, oranje linkerborder #e87c2a):
   - Ja/nee: speelde dit?
   - Zo ja: concrete inhoud + bronlink
   - Groen-zichtbaarheid + kleurcode
   - Zo niet zichtbaar: hoe had Groen dit kunnen claimen?
   - Zo geen dossier: "Geen eco-populistisch dossier deze week" + gemiste kans?

4. RADARSCHERM KLIMAAT & MILIEU (ALTIJD aanwezig, blauw-groene linkerborder #1a7a6e):
   - Ja/nee: speelde dit? (hitte = altijd klimaat; PFAS/vervuiling = altijd milieu)
   - Zo ja: concrete inhoud + bronlink
   - Claimde Groen de oplossingsruimte of bleef het reactief?
   - Kleurcode
   - Zo geen dossier: "Geen klimaat/milieudossier deze week" + gemiste kans?

5. RADARSCHERM PROGRESSIEF (ALTIJD aanwezig, paarse linkerborder #7c3aed):
   - Ja/nee: speelde er een cultureel-progressief dossier?
   - Zo ja: concrete inhoud + bronlink
   - Groen-zichtbaarheid + kleurcode (dit is traditioneel Groen-terrein)
   - Zo niet zichtbaar: gemiste kans?
   - Zo geen dossier: "Geen progressief dossier deze week" + gemiste kans?

6. Strategische slotnotitie: kansen voor komende week (max 5 bullets)

HTML-opmaak (inline CSS, email-compatibel):
- Achtergrond: #f5f5f0, tekst: #1a1a1a, max-width: 640px
- Groen accent: #3d8c40
- Dossierkaarten: witte achtergrond, lichte schaduw, 12px border-radius
- Radarschermen: witte achtergrond, 6px linkerborder in accentkleur, opvallend blok
- Mobiel leesbaar

NIEUWSDATA:
{news_text}"""


# ── Analyse en email ──────────────────────────────────────────────────────────

def analyze_with_claude(news_text: str) -> str:
    print("Claude analyseert het nieuws...")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": ANALYSIS_PROMPT.format(news_text=news_text)}],
    )
    if message.stop_reason == "max_tokens":
        print("⚠️  WAARSCHUWING: output werd afgekapt — verhoog max_tokens indien nodig.")
    return message.content[0].text


def send_email(html_body: str, week_label: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🌿 Groen Politieke Monitor — week {week_label}"
    msg["From"]    = EMAIL_FROM
    msg["To"]      = EMAIL_TO
    msg.attach(MIMEText("Zie HTML-versie van dit rapport.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    print(f"Email versturen naar {EMAIL_TO}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    print("Email verzonden.")


# ── Hoofdprogramma ────────────────────────────────────────────────────────────

def main():
    date_from, date_to = get_date_range()
    week_label = f"{date_from} / {date_to}"
    news_text   = gather_raw_news()
    html_report = analyze_with_claude(news_text)
    send_email(html_report, week_label)
    print("✅ Klaar.")


if __name__ == "__main__":
    main()
