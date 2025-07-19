# wiraai-scraper
WiraAI Scraper
A unified pipeline for automated competitor‐price scraping, supplier‐offer ingestion, and dynamic pricing recommendations for your e-commerce site. Built with Python, Supabase, and GitHub Actions.

🚀 Features
Torob Web Scraper

Crawls product listings on Torob to collect competitor prices, seller names, and product URLs.

Stores results in Supabase under competitor_prices.

Supplier Offer Ingestion

Watches a Telegram bot for forwarded supplier messages (caption + product photo).

Automatically downloads each image, sends it to an OCR pipeline (BLIP2 via HuggingFace), and captures both the original caption and the “box text.”

Queues new offers in Supabase table supplier_queue for downstream matching.

Fuzzy–Semantic Matching

Periodic job matches incoming supplier offers to your scraped product catalog (products table) using fuzzy‐string (RapidFuzz) and optional semantic embeddings.

Automatically flags and enqueues high‐confidence matches into review_queue for final human approval.

Pricing Engine

Combines competitor and supplier data plus your minimum‐profit rules to compute “recommended selling price” per product.

Updates your own store (WooCommerce or custom) via REST or direct DB.

Dashboard & Human‐in‐the‐Loop

React + Tailwind frontend to review ambiguous matches, approve orders, and manually adjust pricing.

Real‐time view of “Recommend to Stock” items, margin calculations, and order links.

Fully Automated

GitHub Actions cron jobs:

torob-scrape.yml: run the Torob crawler every 3 hours.

telegram-ingest.yml: poll Telegram bot hourly for new supplier offers.

match-offers.yml: run fuzzy/semantic matcher nightly.

pricing-engine.yml: update prices in your e-shop daily.

Slack/Telegram/email notifications for new “Recommend to Stock” items.

📦 Project Structure
python
Copy
Edit
.
├── crawler.py              # Torob product/price scraper
├── supplier_ingest/
│   └── ingest.py           # Telegram‐based image ingestion & OCR (BLIP2)
├── matcher.py              # Fuzzy + semantic matching to products
├── pricing_engine.py       # Compute recommended prices & update site
├── ui/                     # React/Tailwind frontend for Human‐in‐the‐Loop
└── .github/
    └── workflows/
        ├── torob-scrape.yml
        ├── telegram-ingest.yml
        ├── match-offers.yml
        └── pricing-engine.yml
🔧 Installation & Configuration
Clone & install dependencies

bash
Copy
Edit
git clone https://github.com/mostafakhajezade/wiraai-scraper.git
cd wiraai-scraper
pip install -r requirements.txt
Set up Supabase

Create a Supabase project.

Run the provided SQL schema (db/schema.sql) to create tables:

products, competitor_prices

ingest_state

supplier_queue

review_queue

ambiguous_matches

Environment Variables

Name	Description
SUPABASE_URL	Your Supabase project URL
SUPABASE_SERVICE_ROLE_KEY	Supabase service‐role key (for full insert/update privileges)
TELEGRAM_BOT_TOKEN	Token from your Telegram Bot (@BotFather)
HUGGINGFACE_TOKEN	(Optional) HF API key for BLIP2 vision‐to‐text
TELEGRAM_CHANNEL_ID	(Optional) if ingesting from a channel via a user‐session client

GitHub Secrets

Add all of the above as GitHub repository secrets under Settings → Secrets.

⚙️ Usage
1. Torob Crawler
bash
Copy
Edit
python crawler.py
Scrapes Torob product catalog & competitor prices.

Populates products and competitor_prices.

2. Supplier Ingest
bash
Copy
Edit
cd supplier_ingest
python ingest.py
Polls Telegram for new photo messages.

Runs BLIP2 OCR to read product‐box text.

Inserts into supplier_queue.

3. Matcher
bash
Copy
Edit
python matcher.py
Fetches pending supplier offers.

Computes fuzzy‐string similarity vs. your Torob‐scraped products.

Enqueues high‐confidence matches in review_queue.

4. Pricing Engine
bash
Copy
Edit
python pricing_engine.py
Joins competitor prices & supplier costs.

Applies margin rules to suggest selling prices.

Updates your e-shop via API or DB.

📈 Automation (GitHub Actions)
All scripts are wired up to run on schedule:

Torob scrape (every 3 hours)

Telegram ingest (hourly)

Offer matching (nightly)

Pricing updates (daily)

See .github/workflows/*.yml for details.

🛠️ Customization
Change minimum profit in pricing_engine.py.

Add new channels (WhatsApp / Instagram) by extending supplier_ingest/ingest.py.

Swap OCR engine by swapping hf_ocr with your own vision‐to‐text model.

🤝 Contributing
Fork → Clone → Create feature branch

Run tests (if any) and lint

Submit a Pull Request

📜 License
MIT © 2025 Mostafa Khajezade