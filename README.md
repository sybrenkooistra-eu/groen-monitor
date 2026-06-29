# Groen Politieke Monitor

Wekelijks script dat elke maandagochtend een email stuurt met:
- De 7 belangrijkste politieke dossiers van de afgelopen week (België/Vlaanderen)
- Per dossier: of en hoe Groen zichtbaar was (wie, welke lijn, waar opgepikt)
- Een kleurcodering: 🟢 goed zichtbaar / 🟡 beperkt / 🔴 niet zichtbaar
- Een strategische slotnotitie voor de komende week

## Setup

### 1. Repository aanmaken op GitHub

```bash
# Maak een nieuwe (private) repo aan op github.com, dan:
git clone https://github.com/JOUW-GEBRUIKERSNAAM/groen-monitor.git
cd groen-monitor

# Kopieer de bestanden hierin
# (monitor.py, requirements.txt, .github/workflows/weekly_monitor.yml)

git add .
git commit -m "Initiële setup Groen monitor"
git push
```

### 2. GitHub Secrets instellen

Ga naar je repository → **Settings → Secrets and variables → Actions → New repository secret**

Voeg deze secrets toe:

| Secret naam       | Waarde                                      |
|-------------------|---------------------------------------------|
| `ANTHROPIC_API_KEY` | Je Anthropic API key (console.anthropic.com) |
| `EMAIL_FROM`      | Afzenderadres (bv. groen.monitor@gmail.com) |
| `EMAIL_TO`        | Ontvangstadres (bv. sybren@groen.be)        |
| `SMTP_HOST`       | bv. `smtp.gmail.com`                        |
| `SMTP_PORT`       | `587`                                       |
| `SMTP_USER`       | Zelfde als EMAIL_FROM                       |
| `SMTP_PASSWORD`   | App-wachtwoord (zie hieronder)              |

### 3. Gmail app-wachtwoord instellen (aanbevolen)

Gebruik **geen** gewoon Gmail-wachtwoord maar een app-wachtwoord:
1. Ga naar [myaccount.google.com/security](https://myaccount.google.com/security)
2. Zet **2-stapsverificatie** aan
3. Ga naar **App-wachtwoorden** → genereer een wachtwoord voor "Mail"
4. Gebruik dat 16-cijferig wachtwoord als `SMTP_PASSWORD`

### 4. Handmatig testen

Je kan de workflow handmatig triggeren via:
GitHub repo → **Actions → Groen Politieke Monitor → Run workflow**

Of lokaal testen:
```bash
pip install -r requirements.txt

export ANTHROPIC_API_KEY="sk-..."
export EMAIL_FROM="..."
export EMAIL_TO="..."
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="..."
export SMTP_PASSWORD="..."

python monitor.py
```

## Aanpassen

- **Andere ontvangers**: voeg meerdere adressen toe aan `EMAIL_TO` (kommagescheiden, pas het script aan)
- **Andere zoektermen**: pas de `queries` lijst aan in `gather_raw_news()`
- **Andere tijdstip**: pas de cron-expressie aan in de workflow (`0 6 * * 1` = maandag 07:00 CET)
- **Meer dossiers**: pas de prompt aan in `ANALYSIS_PROMPT`

## Kosten

Elke run gebruikt ~1 Claude API-aanroep (claude-sonnet-4-6, ~3000-4000 tokens output).
Geschatte kost: **< €0,10 per week**.
